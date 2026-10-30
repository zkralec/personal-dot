"""PostgreSQL-authoritative scheduling with controlled time and fake providers."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from openai import APITimeoutError, APIConnectionError
import httpx
from rq.timeouts import JobTimeoutException

from personal_dot import jobs, notification_delivery
from personal_dot.db import SessionLocal
from personal_dot.jobs import execute_task
from personal_dot.models import NotificationDelivery, NotificationPolicy, Schedule, Task, TaskStatus, TaskType
from personal_dot.notification_delivery import deliver_notification
from personal_dot.notification_service import NotificationResult, NotificationService, TaskNotification, should_notify
from personal_dot.schedule_calculations import next_cron_occurrence
from personal_dot.scheduler import SchedulerService
from tests.test_check_in import create_note, provider, request_for
from tests.test_schedules import scheduler_with

FIRST = datetime(2030, 1, 1, 12, tzinfo=UTC)


async def create_schedule(client, note, **overrides):
    response = await client.post("/schedules", json={
        "name": "synthetic check-in", "schedule_type": "interval",
        "interval_seconds": 60, "start_at": FIRST.isoformat(),
        "task": request_for(note), **overrides,
    })
    assert response.status_code == 201, response.text
    return response.json()


async def enable(client, schedule):
    response = await client.patch("/schedules/" + schedule["id"], json={"enabled": True})
    assert response.status_code == 200, response.text


def task_for(schedule):
    with SessionLocal() as db:
        return db.scalar(select(Task).where(Task.schedule_id == uuid.UUID(schedule["id"])))


@pytest.mark.anyio
async def test_explicit_enable_pause_and_disabled_gap(client, provider, monkeypatch):
    from personal_dot import schedule_routes
    note = await create_note(client)
    schedule = await create_schedule(client, note)
    assert schedule["enabled"] is False
    rejected = await client.post("/schedules", json={
        "name": "must enable separately", "schedule_type": "interval",
        "interval_seconds": 60, "enabled": True, "task": request_for(note),
    })
    assert rejected.status_code == 422
    scheduler = scheduler_with([])
    assert scheduler.run_once(FIRST).tasks_created == 0
    await enable(client, schedule)
    assert scheduler.run_once(FIRST).tasks_created == 1
    await client.patch("/schedules/" + schedule["id"], json={"enabled": False})
    assert scheduler.run_once(FIRST + timedelta(days=1)).tasks_created == 0

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return FIRST + timedelta(days=1)
    monkeypatch.setattr(schedule_routes, "datetime", Clock)
    await enable(client, schedule)
    updated = (await client.get("/schedules/" + schedule["id"])).json()
    assert datetime.fromisoformat(updated["next_run_at"]) == FIRST + timedelta(days=1, minutes=1)
    assert not provider.requests


@pytest.mark.anyio
async def test_concurrent_schedulers_coalesce_downtime_and_database_rejects_duplicate(client, provider):
    note = await create_note(client)
    schedule = await create_schedule(client, note)
    await enable(client, schedule)
    now = FIRST + timedelta(days=100, seconds=35)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: scheduler_with([]).run_once(now), range(2)))
    assert sum(stats.tasks_created for stats in results) == 1
    task = task_for(schedule)
    assert task.scheduled_for == FIRST
    assert task.execution_metadata["schedule"]["coalesced_through"] == now.isoformat()
    with SessionLocal() as db:
        stored = db.get(Schedule, uuid.UUID(schedule["id"]))
        assert stored.next_run_at == FIRST + timedelta(days=100, minutes=1)
        duplicate = Task(type=task.type, status=TaskStatus.QUEUED, payload=task.payload,
                         schedule_id=task.schedule_id, scheduled_for=FIRST)
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()
    execute_task(str(task.id))
    execute_task(str(task.id))
    assert len(provider.requests) == 1


@pytest.mark.anyio
async def test_scheduled_snapshot_uses_current_notes_and_survives_deletion(client, provider):
    note = await create_note(client)
    schedule = await create_schedule(client, note)
    await enable(client, schedule)
    await client.patch("/memories/" + note["id"], json={"content": "Current synthetic project state"})
    scheduler_with([]).run_once(FIRST)
    task = task_for(schedule)
    assert task.payload["sources"][0]["content"] == "Current synthetic project state"
    await client.delete("/memories/" + note["id"])
    execute_task(str(task.id))
    assert len(provider.requests) == 1
    scheduler_with([]).run_once(FIRST + timedelta(minutes=1))
    history = (await client.get("/schedules/" + schedule["id"] + "/tasks")).json()
    assert len(history) == 2
    assert history[0]["status"] == "failed"
    assert history[0]["execution_metadata"]["execution_outcome"] == "invalid_inputs"
    assert len(provider.requests) == 1


@pytest.mark.anyio
async def test_scheduled_check_in_queue_loss_preserves_task_and_snapshot(client, provider):
    note = await create_note(client)
    schedule = await create_schedule(client, note)
    await enable(client, schedule)
    failed = scheduler_with([], fail_enqueue=True, requeue_after_seconds=5)
    assert failed.run_once(FIRST).errors == 1
    task = task_for(schedule)
    snapshot = task.payload
    await client.delete("/memories/" + note["id"])
    recovered = []
    restarted = scheduler_with(recovered, requeue_after_seconds=5)
    stats = restarted.run_once(FIRST + timedelta(seconds=6))
    assert stats.tasks_created == 0 and stats.tasks_enqueued == 1
    assert recovered == [str(task.id)]
    assert task_for(schedule).payload == snapshot
    execute_task(str(task.id))
    assert len(provider.requests) == 1


@pytest.mark.parametrize(("expression", "after", "expected"), [
    ("0 9 * * *", "2030-03-09T14:00:00+00:00", "2030-03-10T13:00:00+00:00"),
    ("30 2 * * *", "2030-03-09T07:30:00+00:00", "2030-03-11T06:30:00+00:00"),
    ("30 1 * * *", "2030-11-03T04:00:00+00:00", "2030-11-03T05:30:00+00:00"),
    ("30 1 * * *", "2030-11-03T05:30:00+00:00", "2030-11-04T06:30:00+00:00"),
    ("30 1 * * *", "2030-11-03T06:00:00+00:00", "2030-11-04T06:30:00+00:00"),
])
def test_new_york_dst_policy(expression, after, expected):
    assert next_cron_occurrence(expression, "America/New_York", datetime.fromisoformat(after)) == datetime.fromisoformat(expected)


@pytest.mark.anyio
async def test_project_overlap_skips_without_waiting_or_model_retry(client, provider):
    note = await create_note(client)
    schedule = await create_schedule(client, note)
    await enable(client, schedule)
    scheduler_with([]).run_once(FIRST)
    first = task_for(schedule)
    second = (await client.post("/tasks", json=request_for(note))).json()
    entered, release = Event(), Event()
    original = provider.create

    def blocked(**request):
        entered.set()
        assert release.wait(10)
        return original(**request)
    provider.create = blocked
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(execute_task, str(first.id))
        try:
            assert entered.wait(5)
            execute_task(second["id"])
            # Duplicate delivery of the running task must not mark it failed.
            execute_task(str(first.id))
        finally:
            release.set()
        future.result(timeout=10)
    skipped = (await client.get("/tasks/" + second["id"])).json()
    assert skipped["status"] == "failed"
    assert skipped["execution_metadata"]["execution_outcome"] == "skipped_overlap"
    assert len(provider.requests) == 1


@pytest.mark.anyio
async def test_late_model_completion_cannot_overwrite_uncertain_execution(client, provider):
    note = await create_note(client)
    task = (await client.post("/tasks", json=request_for(note))).json()
    task_id = uuid.UUID(task["id"])
    original = provider.create

    def interrupted(**request):
        with SessionLocal() as db:
            stored = db.get(Task, task_id)
            stored.started_at = datetime.now(UTC) - timedelta(days=1)
            db.commit()
        assert SchedulerService()._recover_stale_tasks(datetime.now(UTC)) == 1
        return original(**request)
    provider.create = interrupted
    execute_task(task["id"])
    execute_task(task["id"])
    completed = (await client.get("/tasks/" + task["id"])).json()
    assert completed["status"] == "uncertain" and completed["result"] is None
    assert len(provider.requests) == 1
    # Uncertainty terminates this occurrence, rather than pausing the project.
    # A future occurrence is a separately authorized request after lock release.
    provider.create = original
    schedule = await create_schedule(client, note)
    await enable(client, schedule)
    scheduler_with([]).run_once(FIRST)
    following = task_for(schedule)
    execute_task(str(following.id))
    assert len(provider.requests) == 2
    assert (await client.get("/tasks/" + str(following.id))).json()["status"] == "succeeded"
    assert (await client.get("/tasks/" + task["id"])).json()["status"] == "uncertain"


@pytest.mark.anyio
@pytest.mark.parametrize("error_class", [APITimeoutError, APIConnectionError, JobTimeoutException])
async def test_transport_failure_records_unknown_provider_outcome(client, provider, error_class):
    provider.error = (JobTimeoutException("synthetic timeout") if error_class == JobTimeoutException
                      else error_class(request=httpx.Request("POST", "https://synthetic.invalid")))
    note = await create_note(client)
    task = (await client.post("/tasks", json=request_for(note))).json()
    with pytest.raises(RuntimeError, match=r"^Task job failed \([a-z_]+\)$"):
        execute_task(task["id"])
    execute_task(task["id"])
    completed = (await client.get("/tasks/" + task["id"])).json()
    assert completed["status"] == "uncertain"
    assert completed["execution_metadata"]["request_outcome"] == "unknown"
    assert completed["error"] == "Project check-in request interrupted; provider outcome unknown; automatic execution retry disabled"
    assert len(provider.requests) == 1


class NotificationStub:
    def __init__(self, fails=0):
        self.calls = 0
        self.fails = fails

    def send_task_notification(self, notification):
        self.calls += 1
        if self.calls <= self.fails:
            raise RuntimeError("SYNTHETIC_PRIVATE_PROVIDER_ERROR")
        return NotificationResult(provider="stub", provider_request_id="synthetic-push")


@pytest.mark.anyio
@pytest.mark.parametrize("failures", [1, 10])
async def test_notification_retries_are_bounded_and_do_not_repeat_model(client, provider, monkeypatch, failures, caplog):
    stub = NotificationStub(failures)
    monkeypatch.setattr(jobs, "get_notification_service", lambda: stub)
    note = await create_note(client)
    task = (await client.post("/tasks", json=request_for(note, policy="on_completion"))).json()
    execute_task(task["id"])
    task_id = uuid.UUID(task["id"])
    with SessionLocal() as db:
        delivery = db.get(NotificationDelivery, task_id)
        first_retry = delivery.next_attempt_at
    assert not deliver_notification(task_id, now=first_retry - timedelta(seconds=1), service_factory=lambda: stub)
    deliver_notification(task_id, now=first_retry, service_factory=lambda: stub)
    deliver_notification(task_id, now=first_retry + timedelta(seconds=300), service_factory=lambda: stub)
    deliver_notification(task_id, now=first_retry + timedelta(days=1), service_factory=lambda: stub)
    execute_task(task["id"])
    completed = (await client.get("/tasks/" + task["id"])).json()
    assert completed["status"] == "succeeded"
    assert completed["execution_metadata"]["notification"]["delivery_status"] == ("sent" if failures == 1 else "exhausted")
    assert stub.calls == (2 if failures == 1 else 3)
    assert len(provider.requests) == 1
    assert "SYNTHETIC_PRIVATE_PROVIDER_ERROR" not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("claims", [1, 3])
async def test_commit_send_crash_gap_and_expired_notification_claim(client, provider, monkeypatch, claims):
    note = await create_note(client)
    task = (await client.post("/tasks", json=request_for(note, policy="always"))).json()
    monkeypatch.setattr(jobs, "_notify_terminal_task", lambda _: None)
    execute_task(task["id"])
    task_id = uuid.UUID(task["id"])
    with SessionLocal() as db:
        intent = db.get(NotificationDelivery, task_id)
        assert intent.status == "pending"
    # Simulate process death after recording a claim, before delivery audit.
    with SessionLocal() as db:
        intent = db.get(NotificationDelivery, task_id)
        intent.status = "sending"
        intent.attempt_count = claims
        intent.claim_token = uuid.uuid4()
        intent.next_attempt_at = FIRST
        intent.attempts = [{"status": "unknown", "attempted_at": FIRST.isoformat()} for _ in range(claims - 1)] + [{"status": "sending", "attempted_at": FIRST.isoformat()}]
        db.commit()
    stub = NotificationStub()
    assert deliver_notification(task_id, now=FIRST, service_factory=lambda: stub) is (claims == 1)
    with SessionLocal() as db:
        intent = db.get(NotificationDelivery, task_id)
        assert intent.status == ("sent" if claims == 1 else "exhausted")
        assert intent.attempt_count == (2 if claims == 1 else 3)
        assert intent.attempts[0]["status"] == "unknown"
    assert stub.calls == (1 if claims == 1 else 0)
    assert len(provider.requests) == 1


@pytest.mark.anyio
async def test_concurrent_notification_claims_send_once(client, provider, monkeypatch):
    note = await create_note(client)
    task = (await client.post("/tasks", json=request_for(note, policy="always"))).json()
    monkeypatch.setattr(jobs, "_notify_terminal_task", lambda _: None)
    execute_task(task["id"])
    entered, release = Event(), Event()
    stub = NotificationStub()
    original = stub.send_task_notification

    def blocked(notification):
        entered.set()
        assert release.wait(10)
        return original(notification)
    stub.send_task_notification = blocked
    task_id = uuid.UUID(task["id"])
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(deliver_notification, task_id, service_factory=lambda: stub)
        try:
            assert entered.wait(5)
            assert not deliver_notification(task_id, service_factory=lambda: stub)
        finally:
            release.set()
        assert future.result(timeout=10)
    assert stub.calls == 1


def test_uncertain_notification_is_honest_and_follows_failure_policy():
    messages = []

    class Provider:
        name = "stub"

        def send(self, message):
            messages.append(message)
            return NotificationResult(provider=self.name)

    NotificationService(Provider()).send_task_notification(TaskNotification(
        task_id=uuid.uuid4(), task_type=TaskType.PROJECT_CHECK_IN, status=TaskStatus.UNCERTAIN,
    ))
    assert "uncertain execution outcome" in messages[0].body
    assert should_notify(NotificationPolicy.ON_FAILURE, TaskStatus.UNCERTAIN)
    assert should_notify(NotificationPolicy.ALWAYS, TaskStatus.UNCERTAIN)
    assert not should_notify(NotificationPolicy.ON_COMPLETION, TaskStatus.UNCERTAIN)
    assert not should_notify(NotificationPolicy.NONE, TaskStatus.UNCERTAIN)
