import uuid

import pytest

from personal_dot.agent_runtime import AgentRuntime
from personal_dot.agent_service import AgentService, AgentTurn
from personal_dot.db import engine
from personal_dot.memory_service import MemoryService
from personal_dot.schemas import MemorySelection
from personal_dot.tool_registry import build_tool_registry
from tests.test_tasks import run_queued_jobs


class FinalTurnService:
    def __init__(self) -> None:
        self.requests: list[list[dict]] = []

    def build_input(self, instruction, context=None, memory_context=None):
        return AgentService.build_input(instruction, context, memory_context)

    def create_turn(self, input_items, tools):
        self.requests.append(list(input_items))
        return AgentTurn(
            output_text="Memory-aware answer.",
            output_items=[],
            tool_calls=[],
            metadata={
                "provider": "openai",
                "model": "mock-model",
                "success": True,
                "response_id": "resp_memory",
                "response_status": "completed",
                "model_started_at": "2026-10-01T00:00:00+00:00",
                "model_completed_at": "2026-10-01T00:00:01+00:00",
                "usage": {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10},
            },
        )


def memory_runtime(service: FinalTurnService) -> AgentRuntime:
    return AgentRuntime(
        service=service,
        registry=build_tool_registry(),
        max_tool_rounds=8,
    )


@pytest.mark.anyio
async def test_memory_crud_filter_disable_and_delete(client) -> None:
    created = await client.post(
        "/memories",
        json={
            "type": "user_preference",
            "content": "Prefer concise status reports.",
            "source": "manual",
            "tags": ["Work", "reports", "work"],
        },
    )
    assert created.status_code == 201
    memory = created.json()
    memory_id = memory["id"]
    assert memory["tags"] == ["work", "reports"]
    assert memory["enabled"] is True

    filtered = await client.get(
        "/memories?type=user_preference&tag=work&enabled=true"
    )
    assert [item["id"] for item in filtered.json()] == [memory_id]

    updated = await client.patch(
        f"/memories/{memory_id}",
        json={"content": "Prefer very concise status reports.", "source": "user-edit"},
    )
    assert updated.status_code == 200
    assert updated.json()["content"] == "Prefer very concise status reports."
    assert updated.json()["source"] == "user-edit"

    disabled = await client.post(f"/memories/{memory_id}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert (await client.get("/memories?enabled=true")).json() == []
    assert (await client.get("/memories?enabled=false")).json()[0]["id"] == memory_id

    deleted = await client.delete(f"/memories/{memory_id}")
    assert deleted.status_code == 204
    assert (await client.get(f"/memories/{memory_id}")).status_code == 404


@pytest.mark.anyio
async def test_memory_survives_fresh_database_connections(client) -> None:
    created = await client.post(
        "/memories",
        json={
            "type": "durable_fact",
            "content": "The mini PC uses UTC.",
            "source": "manual",
            "tags": ["host"],
        },
    )
    memory_id = created.json()["id"]

    # Drop every pooled connection and construct a fresh service, matching the
    # persistence boundary used after an API or worker process restart.
    engine.dispose()
    retrieved = MemoryService().retrieve(
        MemorySelection(ids=[uuid.UUID(memory_id)])
    )

    assert retrieved.metadata["selected_ids"] == [memory_id]
    assert "The mini PC uses UTC." in retrieved.text
    fetched = await client.get(f"/memories/{memory_id}")
    assert fetched.status_code == 200


@pytest.mark.anyio
async def test_selected_memories_reach_agent_without_full_database_stuffing(
    client, monkeypatch
) -> None:
    from personal_dot import jobs

    preference = (
        await client.post(
            "/memories",
            json={
                "type": "user_preference",
                "content": "Use metric units.",
                "source": "manual",
                "tags": ["profile"],
            },
        )
    ).json()
    unrelated = (
        await client.post(
            "/memories",
            json={
                "type": "project_note",
                "content": "Unrelated project detail.",
                "source": "manual",
                "tags": ["unrelated"],
            },
        )
    ).json()
    disabled = (
        await client.post(
            "/memories",
            json={
                "type": "durable_fact",
                "content": "Disabled memory must not appear.",
                "source": "manual",
                "enabled": False,
                "tags": ["profile"],
            },
        )
    ).json()

    service = FinalTurnService()
    runtime = memory_runtime(service)
    monkeypatch.setattr(jobs, "get_agent_runtime", lambda: runtime)
    created = await client.post(
        "/tasks",
        json={
            "type": "agent",
            "payload": {
                "instruction": "Give me a measurement.",
                "memory": {
                    "ids": [preference["id"], disabled["id"]],
                    "tags": ["profile"],
                    "limit": 10,
                },
            },
        },
    )
    assert created.status_code == 202
    task_id = created.json()["id"]
    run_queued_jobs()

    content = service.requests[0][0]["content"]
    memory_block = next(
        item["text"] for item in content if item["text"].startswith("Explicit memories")
    )
    assert "Use metric units." in memory_block
    assert unrelated["content"] not in memory_block
    assert disabled["content"] not in memory_block
    task = (await client.get(f"/tasks/{task_id}")).json()
    assert task["status"] == "succeeded"
    assert task["execution_metadata"]["memory"] == {
        "strategy": "explicit_v1",
        "selected_ids": [preference["id"]],
        "selected_types": ["user_preference"],
        "missing_or_disabled_ids": [disabled["id"]],
        "count": 1,
    }


@pytest.mark.anyio
async def test_agent_without_memory_selector_receives_no_memories(
    client, monkeypatch
) -> None:
    from personal_dot import jobs

    await client.post(
        "/memories",
        json={
            "type": "durable_fact",
            "content": "This must not be included implicitly.",
            "source": "manual",
        },
    )
    service = FinalTurnService()
    monkeypatch.setattr(jobs, "get_agent_runtime", lambda: memory_runtime(service))

    created = await client.post(
        "/tasks",
        json={"type": "agent", "payload": {"instruction": "Answer normally."}},
    )
    run_queued_jobs()

    content = service.requests[0][0]["content"]
    assert len(content) == 1
    assert "Explicit memories" not in str(content)
    task = (await client.get(f"/tasks/{created.json()['id']}")).json()
    assert "memory" not in task["execution_metadata"]
