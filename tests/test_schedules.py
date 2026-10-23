import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from personal_dot.config import Settings
from personal_dot.db import SessionLocal
from personal_dot.jobs import execute_task
from personal_dot.models import Schedule, Task, TaskStatus, TaskType
from personal_dot.scheduler import SchedulerService


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def scheduler_with(
    enqueued: list[str],
    *,
    fail_enqueue: bool = False,
    requeue_after_seconds: int = 3600,
    stale_task_seconds: int = 900,
) -> SchedulerService:
    def enqueue(task_id) -> None:
        if fail_enqueue:
            raise ConnectionError("simulated Redis outage")
        enqueued.append(str(task_id))

    return SchedulerService(
        settings=Settings(
            scheduler_requeue_after_seconds=requeue_after_seconds,
            scheduler_stale_task_seconds=stale_task_seconds,
            rq_job_timeout_seconds=600,
        ),
        enqueue_func=enqueue,
    )


@pytest.mark.anyio
async def test_one_time_schedule_materializes_once_when_due(client) -> None:
    due_at = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    response = await client.post(
        "/schedules",
        json={
            "name": "one time",
            "schedule_type": "once",
            "run_at": iso(due_at),
            "task": {
                "type": "echo",
                "payload": {"message": "once"},
                "notification_policy": "on_completion",
            },
        },
    )
    assert response.status_code == 201
    schedule_id = response.json()["id"]
    enqueued: list[str] = []
    scheduler = scheduler_with(enqueued)

    before = scheduler.run_once(due_at - timedelta(seconds=1))
    assert before.tasks_created == 0
    due = scheduler.run_once(due_at)

    assert due.tasks_created == 1
    assert due.tasks_enqueued == 1
    assert len(enqueued) == 1
    schedule = (await client.get(f"/schedules/{schedule_id}")).json()
    assert schedule["enabled"] is False
    assert schedule["next_run_at"] is None
    assert datetime.fromisoformat(schedule["last_run_at"]) == due_at
    tasks = (await client.get(f"/schedules/{schedule_id}/tasks")).json()
    assert len(tasks) == 1
    assert tasks[0]["schedule_id"] == schedule_id
    assert tasks[0]["notification_policy"] == "on_completion"
    assert datetime.fromisoformat(tasks[0]["scheduled_for"]) == due_at


@pytest.mark.anyio
async def test_interval_and_cron_schedules_advance_from_occurrence(client) -> None:
    first = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
    interval_response = await client.post(
        "/schedules",
        json={
            "name": "interval",
            "schedule_type": "interval",
            "interval_seconds": 60,
            "start_at": iso(first),
            "task": {"type": "echo", "payload": {"message": "interval"}},
        },
    )
    assert interval_response.status_code == 201
    interval_id = interval_response.json()["id"]
    scheduler = scheduler_with([])

    scheduler.run_once(first)
    scheduler.run_once(first + timedelta(seconds=60))

    interval_schedule = (await client.get(f"/schedules/{interval_id}")).json()
    assert datetime.fromisoformat(interval_schedule["last_run_at"]) == first + timedelta(
        seconds=60
    )
    assert datetime.fromisoformat(interval_schedule["next_run_at"]) == first + timedelta(
        seconds=120
    )
    interval_tasks = (
        await client.get(f"/schedules/{interval_id}/tasks")
    ).json()
    assert len(interval_tasks) == 2

    cron_response = await client.post(
        "/schedules",
        json={
            "name": "cron",
            "schedule_type": "cron",
            "cron_expression": "*/5 * * * *",
            "timezone": "UTC",
            "task": {"type": "echo", "payload": {"message": "cron"}},
        },
    )
    assert cron_response.status_code == 201
    cron_id = cron_response.json()["id"]
    cron_first = datetime.fromisoformat(cron_response.json()["next_run_at"])

    scheduler.run_once(cron_first)

    cron_schedule = (await client.get(f"/schedules/{cron_id}")).json()
    cron_next = datetime.fromisoformat(cron_schedule["next_run_at"])
    assert cron_next == cron_first + timedelta(minutes=5)
    assert cron_next.tzinfo is not None


@pytest.mark.anyio
async def test_disabled_schedule_waits_until_enabled(client) -> None:
    due_at = datetime(2030, 1, 2, 12, 0, tzinfo=UTC)
    created = await client.post(
        "/schedules",
        json={
            "name": "toggle",
            "schedule_type": "interval",
            "interval_seconds": 60,
            "start_at": iso(due_at),
            "enabled": False,
            "task": {"type": "echo", "payload": {}},
        },
    )
    schedule_id = created.json()["id"]
    scheduler = scheduler_with([])

    scheduler.run_once(due_at)
    assert (await client.get(f"/schedules/{schedule_id}/tasks")).json() == []

    enabled = await client.patch(
        f"/schedules/{schedule_id}", json={"enabled": True}
    )
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    scheduler.run_once(due_at)
    assert len((await client.get(f"/schedules/{schedule_id}/tasks")).json()) == 1

    disabled = await client.patch(
        f"/schedules/{schedule_id}", json={"enabled": False}
    )
    assert disabled.json()["enabled"] is False
    scheduler.run_once(due_at + timedelta(seconds=60))
    assert len((await client.get(f"/schedules/{schedule_id}/tasks")).json()) == 1


@pytest.mark.anyio
async def test_scheduler_restart_recovers_persisted_unqueued_task(client) -> None:
    due_at = datetime(2030, 1, 3, 12, 0, tzinfo=UTC)
    created = await client.post(
        "/schedules",
        json={
            "name": "recover queue",
            "schedule_type": "once",
            "run_at": iso(due_at),
            "task": {"type": "echo", "payload": {"recover": True}},
        },
    )
    schedule_id = created.json()["id"]

    failed = scheduler_with([], fail_enqueue=True, requeue_after_seconds=60)
    first_stats = failed.run_once(due_at)
    assert first_stats.tasks_created == 1
    assert first_stats.errors == 1
    first_task = (await client.get(f"/schedules/{schedule_id}/tasks")).json()[0]
    assert first_task["status"] == "queued"
    assert "simulated Redis outage" in first_task["enqueue_error"]

    recovered_ids: list[str] = []
    restarted = scheduler_with(recovered_ids, requeue_after_seconds=60)
    second_stats = restarted.run_once(due_at + timedelta(seconds=61))

    assert second_stats.tasks_created == 0
    assert second_stats.tasks_enqueued == 1
    assert recovered_ids == [first_task["id"]]
    assert len((await client.get(f"/schedules/{schedule_id}/tasks")).json()) == 1


@pytest.mark.anyio
async def test_duplicate_scheduler_polls_create_one_occurrence(client) -> None:
    due_at = datetime(2030, 1, 4, 12, 0, tzinfo=UTC)
    created = await client.post(
        "/schedules",
        json={
            "name": "deduplicate",
            "schedule_type": "once",
            "run_at": iso(due_at),
            "task": {"type": "echo", "payload": {"dedupe": True}},
        },
    )
    schedule_id = created.json()["id"]
    enqueued: list[str] = []

    scheduler_with(enqueued).run_once(due_at)
    scheduler_with(enqueued).run_once(due_at)

    tasks = (await client.get(f"/schedules/{schedule_id}/tasks")).json()
    assert len(tasks) == 1
    assert enqueued == [tasks[0]["id"]]


@pytest.mark.anyio
async def test_stale_running_scheduled_task_is_recovered(client) -> None:
    due_at = datetime(2030, 1, 5, 12, 0, tzinfo=UTC)
    created = await client.post(
        "/schedules",
        json={
            "name": "recover worker",
            "schedule_type": "once",
            "run_at": iso(due_at),
            "task": {"type": "echo", "payload": {"worker": "restart"}},
        },
    )
    schedule_id = created.json()["id"]
    scheduler_with([]).run_once(due_at)

    with SessionLocal() as db:
        task = db.scalar(select(Task).where(Task.schedule_id == schedule_id))
        assert task is not None
        task.status = TaskStatus.RUNNING
        task.started_at = due_at
        db.commit()
        task_id = str(task.id)

    recovered: list[str] = []
    stats = scheduler_with(
        recovered, requeue_after_seconds=60, stale_task_seconds=900
    ).run_once(due_at + timedelta(seconds=901))

    assert stats.tasks_recovered == 1
    assert recovered == [task_id]
    with SessionLocal() as db:
        task = db.get(Task, uuid.UUID(task_id))
        assert task is not None
        assert task.status == TaskStatus.QUEUED


def test_duplicate_task_delivery_does_not_execute_twice() -> None:
    with SessionLocal() as db:
        task = Task(
            type=TaskType.ECHO,
            status=TaskStatus.QUEUED,
            payload={"value": 1},
        )
        db.add(task)
        db.commit()
        task_id = str(task.id)

    first = execute_task(task_id)
    second = execute_task(task_id)

    assert first == {"echo": {"value": 1}}
    assert second == first
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Task)) == 1
        task = db.get(Task, uuid.UUID(task_id))
        assert task is not None
        assert task.status == TaskStatus.SUCCEEDED


def test_stale_running_manual_task_is_recovered() -> None:
    started_at = datetime(2030, 1, 6, 12, 0, tzinfo=UTC)
    with SessionLocal() as db:
        task = Task(
            type=TaskType.ECHO,
            status=TaskStatus.RUNNING,
            payload={"source": "manual"},
            started_at=started_at,
        )
        db.add(task)
        db.commit()
        task_id = str(task.id)

    recovered: list[str] = []
    stats = scheduler_with(
        recovered, requeue_after_seconds=60, stale_task_seconds=900
    ).run_once(started_at + timedelta(seconds=901))

    assert stats.tasks_recovered == 1
    assert recovered == [task_id]
    with SessionLocal() as db:
        task = db.get(Task, uuid.UUID(task_id))
        assert task is not None
        assert task.schedule_id is None
        assert task.status == TaskStatus.QUEUED
