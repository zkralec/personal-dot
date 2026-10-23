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


WORKER_BOOTSTRAP = """
from types import SimpleNamespace
from personal_dot import check_in
from personal_dot.agent_service import AgentService
from personal_dot.config import Settings
from tests.test_check_in import StubResponses
from personal_dot.worker import main

responses = StubResponses()
original = responses.create
def create(**request):
    assert 'tools' not in request and 'tool_choice' not in request
    return original(**request)
responses.create = create
check_in.get_check_in_service = lambda: AgentService(
    settings=Settings(_env_file=None, openai_api_key='synthetic-key'),
    client=SimpleNamespace(responses=responses),
)
main()
"""


def test_manual_check_in_through_http_and_forked_worker(tmp_path: Path) -> None:
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    env = {
        **os.environ, "API_HOST": "127.0.0.1", "API_PORT": str(port),
        "OPENAI_API_KEY": "", "PUSHOVER_API_TOKEN": "", "PUSHOVER_USER_KEY": "",
        "RUN_OPENAI_INTEGRATION": "0",
    }
    base_url = f"http://127.0.0.1:{port}"

    def request(path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        headers = {} if data is None else {"Content-Type": "application/json"}
        with urllib.request.urlopen(
            urllib.request.Request(base_url + path, data=data, headers=headers), timeout=2
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
            created = request("/tasks", {
                "type": "project_check_in", "notification_policy": "none",
                "payload": {"project_id": "process-fixture", "note_ids": [note["id"]],
                            "priorities": ["Bound project check-in inputs."]},
            })
            assert created["status"] == "queued"
            worker = subprocess.Popen(
                [sys.executable, "-c", WORKER_BOOTSTRAP], env=env,
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
