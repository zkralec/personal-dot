"""Exercise execution ownership with PostgreSQL and synthetic handlers only."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from sqlalchemy import func, select

from personal_dot import jobs
from personal_dot.agent_runtime import AgentPaused
from personal_dot.config import Settings
from personal_dot.db import SessionLocal
from personal_dot.models import Note, Task, TaskStatus, TaskType
from personal_dot.scheduler import SchedulerService
from tests.test_tools import FakeTurnService, runtime_for, turn
from personal_dot.agent_service import AgentToolCall


def scheduler():
    return SchedulerService(settings=Settings(
        scheduler_stale_task_seconds=900, rq_job_timeout_seconds=600,
        scheduler_requeue_after_seconds=60,
    ), enqueue_func=lambda task_id: None)


def outcome(kind):
    if kind == "failed":
        raise RuntimeError("synthetic handler failure")
    if kind == "waiting_for_approval":
        return AgentPaused(state={"new": True}, metadata={"waiting_for_approval": True})
    return jobs.TaskExecutionResult(result={"owner": "new"}, metadata={"success": True})


@pytest.mark.anyio
@pytest.mark.parametrize("recover_resume", [False, True])
@pytest.mark.parametrize("fail_final", [False, True])
async def test_delayed_approval_resume_is_not_stale(client, monkeypatch, recover_resume, fail_final):
    service = FakeTurnService([
        turn(response_id="pause", tool_call=AgentToolCall(
            call_id="save", name="save_note", arguments='{"content":"Approved once."}')),
        turn(response_id="done", output_text="Saved."),
    ])
    runtime = runtime_for(service)
    monkeypatch.setattr(jobs, "get_agent_runtime", lambda: runtime)
    created = await client.post("/tasks", json={"type": "agent", "payload": {"instruction": "Save."}})
    task_id = created.json()["id"]
    jobs.execute_task(task_id)
    with SessionLocal() as db, db.begin():
        task = db.get(Task, uuid.UUID(task_id))
        task.started_at = datetime.now(UTC) - timedelta(days=2)
    approval = (await client.get("/approvals?status=pending")).json()[0]
    await client.post(f"/approvals/{approval['id']}/approve", json={"reason": "Owner approval."})

    if recover_resume:
        # Recovered resumed work retains the approved continuation and reuses
        # its successful tool-call audit instead of repeating the local write.
        # Simulate the crash after the approved write but before the final turn.
        def crash_after_write(task):
            runtime._resume_pending(task.agent_state)
            with SessionLocal() as db, db.begin():
                db.get(Task, task.id).started_at = datetime.now(UTC) - timedelta(days=2)
            assert scheduler()._recover_stale_tasks(datetime.now(UTC)) == 1
            return AgentPaused(state={"obsolete": True}, metadata={"waiting_for_approval": True})
        with monkeypatch.context() as patch:
            patch.setattr(jobs, "_perform", crash_after_write)
            jobs.execute_task(task_id)
        with SessionLocal() as db:
            task = db.get(Task, uuid.UUID(task_id))
            assert task.status == TaskStatus.QUEUED
            assert task.agent_state["pending_tool_call_ids"]

    original_turn = service.create_turn
    def final_turn(input_items, tools):
        assert scheduler()._recover_stale_tasks(datetime.now(UTC)) == 0
        with SessionLocal() as db:
            task = db.get(Task, uuid.UUID(task_id))
            assert task.status == TaskStatus.RUNNING
            assert task.started_at > datetime.now(UTC) - timedelta(minutes=1)
            assert not task.execution_metadata.get("waiting_for_approval", False)
        if fail_final:
            raise RuntimeError("synthetic final-turn failure")
        return original_turn(input_items, tools)
    monkeypatch.setattr(service, "create_turn", final_turn)
    if fail_final:
        with pytest.raises(RuntimeError):
            jobs.execute_task(task_id)
    else:
        jobs.execute_task(task_id)
    result = (await client.get(f"/tasks/{task_id}")).json()
    assert result["status"] == ("failed" if fail_final else "succeeded")
    assert "waiting_for_approval" not in result["execution_metadata"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Note)) == 1
        assert db.get(Task, uuid.UUID(task_id)).agent_state is None


@pytest.mark.parametrize("old_outcome", ["succeeded", "failed", "waiting_for_approval"])
@pytest.mark.parametrize("new_state", ["queued", "running", "succeeded", "failed", "waiting_for_approval"])
def test_recovered_worker_cannot_write_over_new_execution(monkeypatch, old_outcome, new_state):
    with SessionLocal() as db, db.begin():
        task = Task(type=TaskType.ECHO, status=TaskStatus.QUEUED, payload={})
        db.add(task)
        db.flush()
        task_id = task.id
    old_entered, old_release, new_entered, new_release = (Event() for _ in range(4))
    calls = []
    owners = []
    notified = []
    monkeypatch.setattr(jobs, "_notify_terminal_task", notified.append)

    def perform(task):
        calls.append(task.started_at)
        owners.append(task.execution_id)
        assert task.execution_id is not None
        if len(calls) == 1:
            old_entered.set()
            assert old_release.wait(10)
            if old_outcome == "succeeded":
                return jobs.TaskExecutionResult(result={"owner": "old"}, metadata={"old": True})
            if old_outcome == "waiting_for_approval":
                return AgentPaused(state={"obsolete": True}, metadata={"obsolete": True})
            return outcome(old_outcome)
        new_entered.set()
        assert new_release.wait(10)
        return outcome(new_state)
    monkeypatch.setattr(jobs, "_perform", perform)

    with ThreadPoolExecutor(max_workers=2) as pool:
        old = pool.submit(jobs.execute_task, str(task_id))
        try:
            assert old_entered.wait(10)
            # Duplicate RQ deliveries cannot enter the handler while claimed.
            assert jobs.execute_task(str(task_id)) == {}
            assert len(calls) == 1
            with SessionLocal() as db, db.begin():
                db.get(Task, task_id).started_at = datetime.now(UTC) - timedelta(days=2)
            assert scheduler()._recover_stale_tasks(datetime.now(UTC)) == 1
            with SessionLocal() as db:
                assert db.get(Task, task_id).execution_id is None
            newer = None
            if new_state != "queued":
                newer = pool.submit(jobs.execute_task, str(task_id))
                assert new_entered.wait(10)
                assert owners[0] != owners[1]
                if new_state != "running":
                    new_release.set()
                    if new_state == "failed":
                        with pytest.raises(RuntimeError):
                            newer.result(timeout=10)
                    else:
                        newer.result(timeout=10)
            with SessionLocal() as db:
                task = db.get(Task, task_id)
                before = {column.name: getattr(task, column.name) for column in Task.__table__.columns}
            notifications_before = list(notified)
            old_release.set()
            old.result(timeout=10)  # Even obsolete failures are discarded.
            with SessionLocal() as db:
                task = db.get(Task, task_id)
                after = {column.name: getattr(task, column.name) for column in Task.__table__.columns}
            assert after == before
            assert notified == notifications_before
            if new_state == "running":
                new_release.set()
                newer.result(timeout=10)
            if new_state == "succeeded":
                assert jobs.execute_task(str(task_id)) == {"owner": "new"}
                assert len(calls) == 2
        finally:
            old_release.set()
            new_release.set()
