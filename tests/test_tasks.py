import pytest
from rq import SimpleWorker

from personal_dot.agent_service import AgentExecutionError, AgentResult
from personal_dot.notification_service import (
    NotificationDeliveryError,
    NotificationResult,
)
from personal_dot.queue import get_queue, get_redis


def run_queued_jobs() -> None:
    worker = SimpleWorker([get_queue()], connection=get_redis())
    worker.work(burst=True, logging_level="WARNING")


@pytest.mark.anyio
async def test_task_success_lifecycle(client) -> None:
    created = await client.post(
        "/tasks", json={"type": "echo", "payload": {"message": "hello"}}
    )
    assert created.status_code == 202
    task_id = created.json()["id"]
    assert created.json()["status"] == "queued"

    run_queued_jobs()

    fetched = await client.get(f"/tasks/{task_id}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["status"] == "succeeded"
    assert body["result"] == {"echo": {"message": "hello"}}
    assert body["started_at"] is not None
    assert body["completed_at"] is not None
    assert body["error"] is None

    listed = await client.get("/tasks")
    assert listed.status_code == 200
    assert [task["id"] for task in listed.json()] == [task_id]


@pytest.mark.anyio
async def test_task_failure_is_persisted(client) -> None:
    created = await client.post("/tasks", json={"type": "fail", "payload": {}})
    assert created.status_code == 202
    task_id = created.json()["id"]

    run_queued_jobs()

    fetched = await client.get(f"/tasks/{task_id}")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["status"] == "failed"
    assert body["error"] == "RuntimeError: requested test failure"
    assert body["completed_at"] is not None


@pytest.mark.anyio
async def test_agent_task_persists_normalized_result_and_metadata(
    client, monkeypatch
) -> None:
    from personal_dot import jobs

    class FakeAgentRuntime:
        def execute(
            self,
            task_id,
            payload,
            state,
            memory_context=None,
            memory_metadata=None,
        ) -> AgentResult:
            assert task_id is not None
            assert payload.instruction == "Summarize the note."
            assert payload.context == "The note is short."
            assert state is None
            assert memory_context is None
            assert memory_metadata is None
            return AgentResult(
                output_text="Short summary.",
                metadata={
                    "provider": "openai",
                    "model": "mock-model",
                    "success": True,
                    "response_id": "resp_mock",
                    "request_id": "req_mock",
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 3,
                        "total_tokens": 13,
                    },
                },
            )

    notified = []

    class FakeNotificationService:
        def send_task_notification(self, notification) -> NotificationResult:
            notified.append(notification)
            return NotificationResult(
                provider="pushover", provider_request_id="push_mock"
            )

    monkeypatch.setattr(jobs, "get_agent_runtime", lambda: FakeAgentRuntime())
    monkeypatch.setattr(
        jobs, "get_notification_service", lambda: FakeNotificationService()
    )
    created = await client.post(
        "/tasks",
        json={
            "type": "agent",
            "payload": {
                "instruction": "Summarize the note.",
                "context": "The note is short.",
            },
            "notification_policy": "on_completion",
        },
    )
    assert created.status_code == 202
    task_id = created.json()["id"]

    run_queued_jobs()

    fetched = await client.get(f"/tasks/{task_id}")
    body = fetched.json()
    assert body["status"] == "succeeded"
    assert body["result"] == {"output": "Short summary."}
    assert body["execution_metadata"]["model"] == "mock-model"
    assert body["execution_metadata"]["response_id"] == "resp_mock"
    assert body["execution_metadata"]["usage"]["total_tokens"] == 13
    assert body["notification_policy"] == "on_completion"
    assert body["execution_metadata"]["notification"]["status"] == "sent"
    assert body["execution_metadata"]["notification"]["provider"] == "pushover"
    assert body["execution_metadata"]["notification"]["provider_request_id"] == (
        "push_mock"
    )
    assert len(notified) == 1


@pytest.mark.anyio
async def test_notification_failure_does_not_corrupt_successful_result(
    client, monkeypatch
) -> None:
    from personal_dot import jobs

    class FailingNotificationService:
        def send_task_notification(self, notification) -> NotificationResult:
            raise NotificationDeliveryError("simulated provider outage")

    monkeypatch.setattr(
        jobs,
        "get_notification_service",
        lambda: FailingNotificationService(),
    )
    created = await client.post(
        "/tasks",
        json={
            "type": "echo",
            "payload": {"message": "preserve me"},
            "notification_policy": "on_completion",
        },
    )
    task_id = created.json()["id"]

    run_queued_jobs()

    body = (await client.get(f"/tasks/{task_id}")).json()
    assert body["status"] == "succeeded"
    assert body["result"] == {"echo": {"message": "preserve me"}}
    assert body["error"] is None
    notification = body["execution_metadata"]["notification"]
    assert notification["status"] == "failed"
    assert notification["provider"] == "pushover"
    assert notification["error"] == (
        "NotificationDeliveryError: simulated provider outage"
    )


@pytest.mark.anyio
async def test_on_failure_policy_notifies_without_replacing_task_error(
    client, monkeypatch
) -> None:
    from personal_dot import jobs

    statuses = []

    class FakeNotificationService:
        def send_task_notification(self, notification) -> NotificationResult:
            statuses.append(notification.status.value)
            return NotificationResult(provider="pushover")

    monkeypatch.setattr(
        jobs, "get_notification_service", lambda: FakeNotificationService()
    )
    created = await client.post(
        "/tasks",
        json={
            "type": "fail",
            "payload": {},
            "notification_policy": "on_failure",
        },
    )
    task_id = created.json()["id"]

    run_queued_jobs()

    body = (await client.get(f"/tasks/{task_id}")).json()
    assert body["status"] == "failed"
    assert body["error"] == "RuntimeError: requested test failure"
    assert body["execution_metadata"]["notification"]["status"] == "sent"
    assert statuses == ["failed"]


@pytest.mark.anyio
async def test_agent_failure_is_safely_persisted(client, monkeypatch) -> None:
    from personal_dot import jobs

    class FailingAgentRuntime:
        def execute(
            self,
            task_id,
            payload,
            state,
            memory_context=None,
            memory_metadata=None,
        ) -> AgentResult:
            raise AgentExecutionError(
                "OpenAI API request timed out",
                {
                    "provider": "openai",
                    "model": "mock-model",
                    "success": False,
                    "request_id": "req_failed",
                },
            )

    monkeypatch.setattr(jobs, "get_agent_runtime", lambda: FailingAgentRuntime())
    created = await client.post(
        "/tasks",
        json={"type": "agent", "payload": {"instruction": "Do the task."}},
    )
    task_id = created.json()["id"]

    run_queued_jobs()

    fetched = await client.get(f"/tasks/{task_id}")
    body = fetched.json()
    assert body["status"] == "failed"
    assert body["result"] is None
    assert body["error"] == "AgentExecutionError: OpenAI API request timed out"
    assert body["execution_metadata"] == {
        "provider": "openai",
        "model": "mock-model",
        "success": False,
        "request_id": "req_failed",
    }


@pytest.mark.anyio
async def test_agent_task_requires_instruction(client) -> None:
    response = await client.post(
        "/tasks", json={"type": "agent", "payload": {"context": "No instruction"}}
    )

    assert response.status_code == 422

    blank_response = await client.post(
        "/tasks", json={"type": "agent", "payload": {"instruction": "   "}}
    )
    assert blank_response.status_code == 422


@pytest.mark.anyio
async def test_missing_task_returns_404(client) -> None:
    response = await client.get("/tasks/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_manual_enqueue_failure_remains_durable_and_is_reconciled(
    client, monkeypatch
) -> None:
    from datetime import datetime, timedelta

    from personal_dot import main
    from personal_dot.config import Settings
    from personal_dot.scheduler import SchedulerService

    def fail_enqueue(task_id) -> None:
        raise ConnectionError("simulated Redis outage")

    monkeypatch.setattr(main, "enqueue_task", fail_enqueue)
    created = await client.post(
        "/tasks", json={"type": "echo", "payload": {"durable": True}}
    )

    assert created.status_code == 202
    body = created.json()
    assert body["status"] == "queued"
    assert body["error"] is None
    assert body["enqueue_error"] == "ConnectionError: queue delivery failed"

    enqueued: list[str] = []
    scheduler = SchedulerService(
        settings=Settings(
            scheduler_requeue_after_seconds=60,
            scheduler_stale_task_seconds=900,
            rq_job_timeout_seconds=600,
        ),
        enqueue_func=lambda task_id: enqueued.append(str(task_id)),
    )
    attempted_at = datetime.fromisoformat(body["enqueue_attempted_at"])
    stats = scheduler.run_once(attempted_at + timedelta(seconds=61))

    assert stats.tasks_enqueued == 1
    assert enqueued == [body["id"]]


@pytest.mark.anyio
async def test_rq_job_uses_explicit_runtime_and_retention_limits(client) -> None:
    from personal_dot.config import get_settings

    created = await client.post(
        "/tasks", json={"type": "echo", "payload": {"limits": True}}
    )
    assert created.status_code == 202

    jobs = get_queue().get_jobs()
    assert len(jobs) == 1
    settings = get_settings()
    assert jobs[0].timeout == settings.rq_job_timeout_seconds
    assert jobs[0].result_ttl == settings.rq_result_ttl_seconds
    assert jobs[0].failure_ttl == settings.rq_failure_ttl_seconds
