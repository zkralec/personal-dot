import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from personal_dot.agent_runtime import AgentRuntime
from personal_dot.agent_service import AgentService, AgentTurn, AgentToolCall
from personal_dot.db import SessionLocal
from personal_dot.models import Note, ToolCall
from personal_dot.tool_registry import ToolRegistry, build_tool_registry
from tests.test_tasks import run_queued_jobs


def turn(
    *,
    response_id: str,
    output_text: str = "",
    tool_call: AgentToolCall | None = None,
) -> AgentTurn:
    output_items = []
    tool_calls = []
    if tool_call is not None:
        output_items.append(
            {
                "type": "function_call",
                "call_id": tool_call.call_id,
                "name": tool_call.name,
                "arguments": tool_call.arguments,
            }
        )
        tool_calls.append(tool_call)
    return AgentTurn(
        output_text=output_text,
        output_items=output_items,
        tool_calls=tool_calls,
        metadata={
            "provider": "openai",
            "model": "mock-model",
            "success": True,
            "response_id": response_id,
            "request_id": f"req_{response_id}",
            "response_status": "completed",
            "model_started_at": "2026-10-01T00:00:00+00:00",
            "model_completed_at": "2026-10-01T00:00:01+00:00",
            "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
        },
    )


class FakeTurnService:
    def __init__(self, turns: list[AgentTurn]) -> None:
        self.turns = list(turns)
        self.requests: list[dict] = []

    def build_input(self, instruction, context=None, memory_context=None):
        return AgentService.build_input(instruction, context, memory_context)

    def create_turn(self, input_items, tools):
        self.requests.append({"input": list(input_items), "tools": tools})
        return self.turns.pop(0)


def runtime_for(service: FakeTurnService) -> AgentRuntime:
    return AgentRuntime(
        service=service,
        registry=build_tool_registry(),
        max_tool_rounds=8,
    )


def test_registry_rejects_automatic_non_read_only_tool() -> None:
    save_note = build_tool_registry().get("save_note")
    assert save_note is not None
    unsafe = replace(
        save_note,
        automatic_execution_allowed=True,
        requires_approval=False,
    )

    with pytest.raises(
        ValueError, match="only read-only tools may execute automatically"
    ):
        ToolRegistry().register(unsafe)


@pytest.mark.anyio
async def test_registry_metadata_is_exposed_without_handlers(client) -> None:
    response = await client.get("/tools")

    assert response.status_code == 200
    tools = {item["name"]: item for item in response.json()}
    assert set(tools) == {"get_current_time", "save_note"}
    assert tools["get_current_time"]["risk"] == "read_only"
    assert tools["get_current_time"]["automatic_execution_allowed"] is True
    assert tools["get_current_time"]["requires_approval"] is False
    assert tools["save_note"]["risk"] == "local_write"
    assert tools["save_note"]["automatic_execution_allowed"] is False
    assert tools["save_note"]["requires_approval"] is True
    assert tools["save_note"]["input_schema"]["additionalProperties"] is False


@pytest.mark.anyio
async def test_read_only_tool_executes_and_returns_output_to_model(
    client, monkeypatch
) -> None:
    from personal_dot import jobs

    service = FakeTurnService(
        [
            turn(
                response_id="resp_tool",
                tool_call=AgentToolCall(
                    call_id="call_time",
                    name="get_current_time",
                    arguments='{"timezone":"UTC"}',
                ),
            ),
            turn(response_id="resp_final", output_text="The current time was read."),
        ]
    )
    runtime = runtime_for(service)
    monkeypatch.setattr(jobs, "get_agent_runtime", lambda: runtime)

    created = await client.post(
        "/tasks",
        json={"type": "agent", "payload": {"instruction": "What time is it?"}},
    )
    task_id = created.json()["id"]
    run_queued_jobs()

    task = (await client.get(f"/tasks/{task_id}")).json()
    assert task["status"] == "succeeded"
    assert task["result"] == {"output": "The current time was read."}
    assert task["execution_metadata"]["tool_rounds"] == 2
    assert task["execution_metadata"]["usage"]["total_tokens"] == 6
    calls = (await client.get(f"/tasks/{task_id}/tool-calls")).json()
    assert len(calls) == 1
    assert calls[0]["tool_name"] == "get_current_time"
    assert calls[0]["status"] == "succeeded"
    assert calls[0]["approval_status"] == "not_required"
    tool_output = service.requests[1]["input"][-1]
    assert tool_output["type"] == "function_call_output"
    assert json.loads(tool_output["output"])["ok"] is True


@pytest.mark.anyio
async def test_local_write_waits_for_approval_then_resumes(
    client, monkeypatch
) -> None:
    from personal_dot import jobs

    service = FakeTurnService(
        [
            turn(
                response_id="resp_note",
                tool_call=AgentToolCall(
                    call_id="call_note",
                    name="save_note",
                    arguments='{"content":"Remember the safe thing."}',
                ),
            ),
            turn(response_id="resp_saved", output_text="The note was saved."),
        ]
    )
    runtime = runtime_for(service)
    monkeypatch.setattr(jobs, "get_agent_runtime", lambda: runtime)

    created = await client.post(
        "/tasks",
        json={"type": "agent", "payload": {"instruction": "Save my note."}},
    )
    task_id = created.json()["id"]
    run_queued_jobs()

    waiting = (await client.get(f"/tasks/{task_id}")).json()
    assert waiting["status"] == "waiting_for_approval"
    assert waiting["completed_at"] is None
    approvals = (await client.get("/approvals?status=pending")).json()
    assert len(approvals) == 1
    assert approvals[0]["task_id"] == task_id
    assert approvals[0]["summary"] == "Save a local note containing 24 characters."
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Note)) == 0

    approved = await client.post(
        f"/approvals/{approvals[0]['id']}/approve",
        json={"reason": "I requested this local note."},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    run_queued_jobs()

    completed = (await client.get(f"/tasks/{task_id}")).json()
    assert completed["status"] == "succeeded"
    assert completed["result"] == {"output": "The note was saved."}
    calls = (await client.get(f"/tasks/{task_id}/tool-calls")).json()
    assert calls[0]["status"] == "succeeded"
    assert calls[0]["approval_status"] == "approved"
    with SessionLocal() as db:
        note = db.scalar(select(Note))
        assert note is not None
        assert note.content == "Remember the safe thing."
        assert str(note.task_id) == task_id
    resumed_output = service.requests[1]["input"][-1]
    assert json.loads(resumed_output["output"])["result"]["saved"] is True


@pytest.mark.anyio
async def test_approval_enqueue_failure_is_reconciled_without_reapproval(
    client, monkeypatch
) -> None:
    from datetime import datetime, timedelta

    from personal_dot import jobs, tool_routes
    from personal_dot.config import Settings
    from personal_dot.scheduler import SchedulerService

    service = FakeTurnService(
        [
            turn(
                response_id="resp_note_retry",
                tool_call=AgentToolCall(
                    call_id="call_note_retry",
                    name="save_note",
                    arguments='{"content":"Persist this approval."}',
                ),
            ),
            turn(response_id="resp_retry_done", output_text="The note was saved."),
        ]
    )
    monkeypatch.setattr(jobs, "get_agent_runtime", lambda: runtime_for(service))
    created = await client.post(
        "/tasks",
        json={"type": "agent", "payload": {"instruction": "Save a note."}},
    )
    task_id = created.json()["id"]
    run_queued_jobs()
    approval = (await client.get("/approvals?status=pending")).json()[0]

    def fail_enqueue(task_id) -> None:
        raise ConnectionError("simulated Redis outage")

    monkeypatch.setattr(tool_routes, "enqueue_task", fail_enqueue)
    approved = await client.post(
        f"/approvals/{approval['id']}/approve", json={"reason": "Approved once."}
    )

    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    task = (await client.get(f"/tasks/{task_id}")).json()
    assert task["status"] == "queued"
    assert task["enqueue_error"] == "Queue delivery failed (queue_unavailable); durable reconciliation will retry"

    enqueued: list[str] = []
    scheduler = SchedulerService(
        settings=Settings(
            scheduler_requeue_after_seconds=60,
            scheduler_stale_task_seconds=900,
            rq_job_timeout_seconds=600,
        ),
        enqueue_func=lambda pending_id: enqueued.append(str(pending_id)),
    )
    attempted_at = datetime.fromisoformat(task["enqueue_attempted_at"])
    stats = scheduler.run_once(attempted_at + timedelta(seconds=61))

    assert stats.tasks_enqueued == 1
    assert enqueued == [task_id]
    assert (await client.get(f"/approvals/{approval['id']}")).json()["status"] == (
        "approved"
    )


@pytest.mark.anyio
async def test_denied_write_is_not_executed_and_model_can_continue(
    client, monkeypatch
) -> None:
    from personal_dot import jobs

    service = FakeTurnService(
        [
            turn(
                response_id="resp_note",
                tool_call=AgentToolCall(
                    call_id="call_note_denied",
                    name="save_note",
                    arguments='{"content":"Do not save me."}',
                ),
            ),
            turn(response_id="resp_denied", output_text="The note was not saved."),
        ]
    )
    runtime = runtime_for(service)
    monkeypatch.setattr(jobs, "get_agent_runtime", lambda: runtime)

    created = await client.post(
        "/tasks",
        json={"type": "agent", "payload": {"instruction": "Save a note."}},
    )
    task_id = created.json()["id"]
    run_queued_jobs()
    approval = (await client.get("/approvals?status=pending")).json()[0]

    denied = await client.post(
        f"/approvals/{approval['id']}/deny", json={"reason": "No longer needed."}
    )
    assert denied.status_code == 200
    run_queued_jobs()

    task = (await client.get(f"/tasks/{task_id}")).json()
    assert task["status"] == "succeeded"
    calls = (await client.get(f"/tasks/{task_id}/tool-calls")).json()
    assert calls[0]["status"] == "denied"
    assert calls[0]["approval_status"] == "denied"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Note)) == 0
    denied_output = json.loads(service.requests[1]["input"][-1]["output"])
    assert denied_output == {"error": "user denied this tool call", "ok": False}


@pytest.mark.anyio
async def test_invalid_model_arguments_are_audited_and_never_executed(
    client, monkeypatch
) -> None:
    from personal_dot import jobs

    service = FakeTurnService(
        [
            turn(
                response_id="resp_invalid",
                tool_call=AgentToolCall(
                    call_id="call_invalid",
                    name="get_current_time",
                    arguments='{"timezone":"not/a/timezone","extra":true}',
                ),
            ),
            turn(response_id="resp_recovered", output_text="I could not read it."),
        ]
    )
    runtime = runtime_for(service)
    monkeypatch.setattr(jobs, "get_agent_runtime", lambda: runtime)

    created = await client.post(
        "/tasks",
        json={"type": "agent", "payload": {"instruction": "Read the time."}},
    )
    task_id = created.json()["id"]
    run_queued_jobs()

    calls = (await client.get(f"/tasks/{task_id}/tool-calls")).json()
    assert calls[0]["status"] == "failed"
    assert calls[0]["arguments"] == {}
    assert "invalid tool arguments" in calls[0]["error"]
    assert (await client.get(f"/tasks/{task_id}")).json()["status"] == "succeeded"
