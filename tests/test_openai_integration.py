import os

import pytest

from tests.test_tasks import run_queued_jobs


@pytest.mark.integration
@pytest.mark.anyio
async def test_real_openai_agent_task_is_persisted(client) -> None:
    if os.getenv("RUN_OPENAI_INTEGRATION") != "1":
        pytest.skip("set RUN_OPENAI_INTEGRATION=1 to allow a paid API request")
    if not os.getenv("OPENAI_API_KEY", "").strip():
        pytest.skip("OPENAI_API_KEY is not configured")

    created = await client.post(
        "/tasks",
        json={
            "type": "agent",
            "payload": {
                "instruction": "Reply with exactly: personal dot integration ok"
            },
        },
    )
    assert created.status_code == 202
    task_id = created.json()["id"]

    run_queued_jobs()

    fetched = await client.get(f"/tasks/{task_id}")
    body = fetched.json()
    assert body["status"] == "succeeded", body
    assert "personal dot integration ok" in body["result"]["output"].lower()
    assert body["execution_metadata"]["provider"] == "openai"
    assert body["execution_metadata"]["response_id"]
    assert body["execution_metadata"]["usage"]["total_tokens"] > 0
