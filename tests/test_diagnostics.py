"""Sensitive exception bodies must not escape through operational diagnostics."""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from rq.registry import FailedJobRegistry
from sqlalchemy.exc import OperationalError

from personal_dot import jobs, main, notification_routes
from personal_dot.agent_service import AgentExecutionError
from personal_dot.db import SessionLocal
from personal_dot.models import Task
from personal_dot.notification_service import (
    NotificationConfigurationError, NotificationDeliveryError,
    NotificationResult, NotificationService, PushoverProvider,
)
from personal_dot.config import Settings
from personal_dot.queue import get_queue, get_redis
from personal_dot.scheduler import SchedulerService
from personal_dot.structured_logging import JsonFormatter
from tests.test_tasks import run_queued_jobs

MARKER = "SYNTHETIC_SENSITIVE_DO_NOT_DISCLOSE_7c92"


def database_error():
    # Server error text and SQL literals leak even with hide_parameters=True.
    return OperationalError(f"SELECT '{MARKER}'", {"private": MARKER},
                            RuntimeError(MARKER), hide_parameters=True)


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["unexpected", "database", "typed_agent"])
async def test_task_failure_sanitizes_api_database_rq_logs_and_notification(client, monkeypatch, caplog, kind):
    error = {
        "unexpected": RuntimeError(MARKER), "database": database_error(),
        "typed_agent": AgentExecutionError(MARKER, {
            "request_id": "req_safe_correlation", "diagnostic": MARKER,
            "usage": {"total_tokens": 35, "private": MARKER},
        }),
    }[kind]
    def fail(task):
        raise error
    monkeypatch.setattr(jobs, "_perform", fail)
    messages = []
    class Provider:
        def send(self, message):
            messages.append(message)
            return NotificationResult(provider="pushover")
    monkeypatch.setattr(jobs, "get_notification_service", lambda: NotificationService(Provider()))
    created = (await client.post("/tasks", json={
        "type": "echo", "payload": {}, "notification_policy": "on_failure",
    })).json()
    run_queued_jobs()
    body = (await client.get("/tasks/" + created["id"])).json()
    assert body["status"] == "failed" and body["result"] is None
    assert "failed" in body["error"].lower()
    assert body["execution_metadata"]["notification"]["status"] == "sent"
    if kind == "typed_agent":
        assert body["execution_metadata"]["request_id"] == "req_safe_correlation"
        assert body["execution_metadata"]["usage"] == {"total_tokens": 35}
    with SessionLocal() as db:
        task = db.get(Task, uuid.UUID(created["id"]))
        assert MARKER not in task.error + json.dumps(task.execution_metadata)
    registry = FailedJobRegistry(queue=get_queue())
    failed = [get_queue().fetch_job(job_id) for job_id in registry.get_job_ids()]
    assert len(failed) == 1
    assert MARKER not in failed[0].exc_info
    assert MARKER not in json.dumps(body) + caplog.text + repr(messages)


@pytest.mark.anyio
async def test_enqueue_and_reconciliation_errors_remain_safe_and_retryable(client, monkeypatch, caplog):
    def fail(task_id):
        raise ConnectionError(MARKER)
    monkeypatch.setattr(main, "enqueue_task", fail)
    created = await client.post("/tasks", json={"type": "echo", "payload": {}})
    assert created.status_code == 202
    body = created.json()
    assert body["status"] == "queued" and "queue_unavailable" in body["enqueue_error"]
    now = datetime.fromisoformat(body["enqueue_attempted_at"]) + timedelta(minutes=2)
    scheduler = SchedulerService(enqueue_func=fail)
    assert scheduler.run_once(now).errors == 1
    body = (await client.get("/tasks/" + body["id"])).json()
    assert body["status"] == "queued" and "reconciliation will retry" in body["enqueue_error"]
    assert MARKER not in json.dumps(body) + caplog.text
    enqueued = []
    scheduler.enqueue_func = enqueued.append
    assert scheduler.run_once(now + timedelta(minutes=2)).tasks_enqueued == 1
    assert enqueued == [uuid.UUID(body["id"])]


@pytest.mark.anyio
async def test_schedule_materialization_database_failure_is_safe_without_enabling_schedule(client, monkeypatch, caplog):
    response = await client.post("/schedules", json={
        "name": "disabled synthetic", "enabled": False,
        "schedule_type": "interval", "interval_seconds": 60,
        "task": {"type": "echo", "payload": {}},
    })
    schedule_id = uuid.UUID(response.json()["id"])
    scheduler = SchedulerService()
    monkeypatch.setattr(scheduler, "_due_schedule_ids", lambda now: [schedule_id])
    def fail(*args):
        raise database_error()
    monkeypatch.setattr(scheduler, "_materialize_occurrence", fail)
    assert scheduler.run_once().errors == 1
    body = (await client.get("/schedules/" + str(schedule_id))).json()
    assert body["last_error"] == "Schedule materialization failed"
    assert body["enabled"] is False
    assert MARKER not in json.dumps(body) + caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["configuration", "delivery", "unexpected"])
async def test_notification_exception_bodies_never_reach_audit_api_or_logs(client, monkeypatch, caplog, kind):
    error = {"configuration": NotificationConfigurationError,
             "delivery": NotificationDeliveryError, "unexpected": RuntimeError}[kind](MARKER)
    class Service:
        def send_task_notification(self, notification):
            raise error
        def send_test_notification(self):
            raise error
    monkeypatch.setattr(jobs, "get_notification_service", lambda: Service())
    monkeypatch.setattr(notification_routes, "get_notification_service", lambda: Service())
    created = (await client.post("/tasks", json={
        "type": "echo", "payload": {}, "notification_policy": "on_completion",
    })).json()
    run_queued_jobs()
    body = (await client.get("/tasks/" + created["id"])).json()
    assert body["status"] == "succeeded" and body["result"] == {"echo": {}}
    assert body["execution_metadata"]["notification"]["error"] == "Notification delivery failed"
    response = await client.post("/notifications/test")
    assert response.status_code == (503 if kind == "configuration" else 502)
    assert MARKER not in json.dumps(body) + response.text + caplog.text


@pytest.mark.anyio
async def test_unhandled_api_database_failure_does_not_escape_to_server_logs(client, monkeypatch, caplog):
    def fail(*args):
        raise database_error()
    monkeypatch.setattr(SessionLocal.class_, "commit", fail)
    response = await client.post("/tasks", json={"type": "echo", "payload": {}})
    assert response.status_code == 503
    assert response.json() == {"detail": "operation unavailable"}
    assert MARKER not in response.text + caplog.text
    assert "api_operation_failed" in caplog.text or any(
        getattr(record, "event", None) == "api_operation_failed" for record in caplog.records)


@pytest.mark.anyio
async def test_worker_commit_failure_does_not_reach_rq_diagnostics(client, monkeypatch, caplog):
    created = (await client.post("/tasks", json={"type": "echo", "payload": {}})).json()
    original = SessionLocal.class_.commit
    calls = 0
    def commit(session):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise database_error()
        return original(session)
    monkeypatch.setattr(SessionLocal.class_, "commit", commit)
    run_queued_jobs()
    failed_ids = FailedJobRegistry(queue=get_queue()).get_job_ids()
    assert len(failed_ids) == 1
    assert "database_error" in get_queue().fetch_job(failed_ids[0]).exc_info
    assert MARKER not in get_queue().fetch_job(failed_ids[0]).exc_info + caplog.text
    body = (await client.get("/tasks/" + created["id"])).json()
    assert body["status"] == "running"  # The terminal transaction rolled back.
    assert MARKER not in json.dumps(body)


def test_scheduler_poll_database_failure_has_safe_log(monkeypatch, caplog):
    from personal_dot import scheduler
    def fail(*args):
        raise database_error()
    class StopPoll(BaseException):
        pass
    def stop(*args):
        raise StopPoll()
    monkeypatch.setattr(scheduler, "configure_logging", lambda *args: None)
    monkeypatch.setattr(scheduler.SchedulerService, "run_once", fail)
    monkeypatch.setattr(scheduler.time, "sleep", stop)
    with pytest.raises(StopPoll):
        scheduler.main()
    assert any(getattr(record, "event", None) == "scheduler_poll_failed" for record in caplog.records)
    assert MARKER not in caplog.text


@pytest.mark.anyio
async def test_provider_transport_error_chain_is_not_logged(client, monkeypatch, caplog):
    class Client:
        def post(self, *args, **kwargs):
            raise httpx.ConnectError(MARKER)
    provider = PushoverProvider(
        settings=Settings(_env_file=None, pushover_api_token="synthetic-token",
                          pushover_user_key="synthetic-user"), client=Client())
    monkeypatch.setattr(notification_routes, "get_notification_service", lambda: NotificationService(provider))
    response = await client.post("/notifications/test")
    assert response.status_code == 502
    assert MARKER not in response.text + caplog.text


def test_formatter_does_not_render_database_exception_or_chain():
    try:
        raise database_error()
    except OperationalError:
        import sys
        record = logging.LogRecord("test", logging.ERROR, __file__, 1,
                                   "Database operation failed", (), sys.exc_info())
    rendered = JsonFormatter("test").format(record)
    assert MARKER not in rendered
    assert json.loads(rendered)["error_class"] == "database_error"
