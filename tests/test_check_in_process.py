"""Real HTTP and forked RQ processes, with the provider stubbed in the worker."""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from datetime import UTC, datetime, timedelta
import uuid

import pytest


WORKER_BOOTSTRAP = """
from types import SimpleNamespace
from personal_dot import check_in
from personal_dot.agent_service import AgentService
from personal_dot.config import Settings
from tests.test_check_in import StubResponses
from personal_dot.worker import main
from personal_dot.queue import get_redis

responses = StubResponses()
original = responses.create
def create(**request):
    assert 'tools' not in request and 'tool_choice' not in request
    get_redis().incr('synthetic:model-calls')
    return original(**request)
responses.create = create
check_in.get_check_in_service = lambda: AgentService(
    settings=Settings(_env_file=None, openai_api_key='synthetic-key'),
    client=SimpleNamespace(responses=responses),
)
main()
"""

NOTIFICATION_BOOTSTRAP = """
from personal_dot import jobs, notification_delivery
from personal_dot.queue import get_redis
from personal_dot.notification_service import NotificationResult
class StubNotification:
    def send_task_notification(self, notification):
        attempts = get_redis().incr('synthetic:notification:' + str(notification.task_id))
        if attempts == 1:
            raise RuntimeError('synthetic delivery failure')
        return NotificationResult(provider='stub', provider_request_id='synthetic-process-push')
jobs.get_notification_service = lambda: StubNotification()
notification_delivery.get_notification_service = lambda: StubNotification()
"""


@pytest.mark.parametrize("scheduled", [False, True])
def test_check_in_through_http_and_forked_worker(tmp_path: Path, scheduled: bool) -> None:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    env = {
        **os.environ, "API_HOST": "127.0.0.1", "API_PORT": str(port),
        "OPENAI_API_KEY": "", "PUSHOVER_API_TOKEN": "", "PUSHOVER_USER_KEY": "",
        "RUN_OPENAI_INTEGRATION": "0",
    }
    base_url = f"http://127.0.0.1:{port}"

    def request(path, payload=None, method=None):
        data = None if payload is None else json.dumps(payload).encode()
        headers = {} if data is None else {"Content-Type": "application/json"}
        with urllib.request.urlopen(
            urllib.request.Request(base_url + path, data=data, headers=headers, method=method), timeout=2
        ) as response:
            return json.load(response)

    processes = []
    with (tmp_path / "processes.log").open("w+") as log:
        try:
            api = subprocess.Popen(
                [sys.executable, "-m", "personal_dot.server"], env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            processes.append(api)
            for _ in range(80):
                try:
                    assert request("/health")["status"] == "ok"
                    break
                except (urllib.error.URLError, OSError):
                    assert api.poll() is None, "test API exited before startup"
                    time.sleep(0.1)
            else:
                raise AssertionError("test API did not start")
            note = request("/memories", {
                "type": "project_note", "content": "The check-in has no input-size guard yet.",
                "source": "synthetic-process-fixture",
            })
            task_request = {
                "type": "project_check_in", "notification_policy": "always" if scheduled else "none",
                "payload": {"project_id": "process-fixture", "note_ids": [note["id"]],
                            "priorities": ["Bound project check-in inputs."]},
            }
            if scheduled:
                schedule = request("/schedules", {
                    "name": "synthetic process schedule", "schedule_type": "once",
                    "run_at": (datetime.now(UTC) + timedelta(seconds=2)).isoformat(),
                    "task": task_request,
                })
                assert schedule["enabled"] is False
                request("/schedules/" + schedule["id"], {"enabled": True}, method="PATCH")
                scheduler = subprocess.Popen(
                    [sys.executable, "-c", NOTIFICATION_BOOTSTRAP + "\nfrom personal_dot.scheduler import main\nmain()"],
                    env={**env, "SCHEDULER_POLL_SECONDS": "0.1"}, stdout=log, stderr=subprocess.STDOUT,
                )
                processes.append(scheduler)
                for _ in range(100):
                    tasks = request("/schedules/" + schedule["id"] + "/tasks")
                    if tasks:
                        break
                    assert scheduler.poll() is None
                    time.sleep(0.1)
                assert len(tasks) == 1
                created = tasks[0]
            else:
                created = request("/tasks", task_request)
            assert created["status"] == "queued"
            worker = subprocess.Popen(
                [sys.executable, "-c", NOTIFICATION_BOOTSTRAP + WORKER_BOOTSTRAP], env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
            processes.append(worker)
            for _ in range(160):
                completed = request("/tasks/" + created["id"])
                if completed["status"] in {"succeeded", "failed"}:
                    break
                assert worker.poll() is None, "test worker exited before completion"
                time.sleep(0.1)
            assert completed["status"] == "succeeded", completed.get("error")
            assert completed["result"]["recommended_action"]["kind"] == "resolve_blocker"
            assert completed["execution_metadata"]["check_in"]["input_sha256"] == created["payload"]["input_sha256"]
            if scheduled:
                from personal_dot.db import SessionLocal
                from personal_dot.models import NotificationDelivery
                from personal_dot.queue import get_redis
                # Advance only the persisted delivery deadline, avoiding a
                # minute-long test; the actual scheduler performs the retry.
                for _ in range(50):
                    with SessionLocal() as db:
                        delivery = db.get(NotificationDelivery, uuid.UUID(created["id"]))
                        if delivery is not None and delivery.status == "pending" and delivery.attempt_count == 1:
                            delivery.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
                            db.commit()
                            break
                    time.sleep(0.1)
                else:
                    raise AssertionError("first notification failure was not persisted")
                for _ in range(100):
                    completed = request("/tasks/" + created["id"])
                    audit = completed["execution_metadata"].get("notification", {})
                    if audit.get("delivery_status") == "sent":
                        break
                    time.sleep(0.1)
                assert audit["attempt_count"] == 2 and audit["delivery_status"] == "sent"
                assert get_redis().get('synthetic:model-calls') == b'1'
                assert len(request("/schedules/" + schedule["id"] + "/tasks")) == 1
                assert request("/schedules/" + schedule["id"])["enabled"] is False
                log.flush()
                print("Scheduled HTTP/RQ lifecycle log:\n" + (tmp_path / "processes.log").read_text()[-6000:])
            else:
                assert "notification" not in completed["execution_metadata"]
            assert request("/tasks/" + created["id"] + "/tool-calls") == []
        except Exception:
            log.flush()
            raise AssertionError("isolated HTTP/worker workflow failed:\n" + (tmp_path / "processes.log").read_text()) from None
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
