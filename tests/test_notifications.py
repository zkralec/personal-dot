from dataclasses import dataclass
import uuid

import httpx
import pytest

from personal_dot.config import Settings
from personal_dot.models import NotificationPolicy, TaskStatus, TaskType
from personal_dot.notification_service import (
    NotificationConfigurationError,
    NotificationDeliveryError,
    NotificationMessage,
    NotificationResult,
    NotificationService,
    PushoverProvider,
    TaskNotification,
    should_notify,
)


@dataclass
class FakeHttpClient:
    response: httpx.Response
    request: dict | None = None

    def post(self, url, *, data, timeout=None):
        self.request = {"url": url, "data": data, "timeout": timeout}
        return self.response


def test_pushover_provider_sends_expected_form_without_network() -> None:
    client = FakeHttpClient(
        httpx.Response(200, json={"status": 1, "request": "push-request-1"})
    )
    provider = PushoverProvider(
        settings=Settings(
            pushover_api_token="test-app-token",
            pushover_user_key="test-user-key",
            notification_timeout_seconds=7,
        ),
        client=client,
    )

    result = provider.send(
        NotificationMessage(title="Personal Dot test", body="It works.")
    )

    assert result == NotificationResult(
        provider="pushover", provider_request_id="push-request-1"
    )
    assert client.request == {
        "url": "https://api.pushover.net/1/messages.json",
        "data": {
            "token": "test-app-token",
            "user": "test-user-key",
            "title": "Personal Dot test",
            "message": "It works.",
        },
        "timeout": 7.0,
    }


def test_pushover_provider_fails_clearly_without_credentials() -> None:
    provider = PushoverProvider(
        settings=Settings(pushover_api_token=None, pushover_user_key=None)
    )

    with pytest.raises(
        NotificationConfigurationError,
        match="PUSHOVER_API_TOKEN is not configured",
    ):
        provider.send(NotificationMessage(title="Test", body="Test"))


def test_pushover_provider_returns_safe_http_error() -> None:
    client = FakeHttpClient(
        httpx.Response(
            400,
            json={"status": 0, "errors": ["test-app-token must not leak"]},
        )
    )
    provider = PushoverProvider(
        settings=Settings(
            pushover_api_token="test-app-token",
            pushover_user_key="test-user-key",
        ),
        client=client,
    )

    with pytest.raises(
        NotificationDeliveryError,
        match="Pushover request failed with HTTP 400",
    ) as raised:
        provider.send(NotificationMessage(title="Test", body="Test"))

    assert "test-app-token" not in str(raised.value)


@pytest.mark.parametrize(
    ("policy", "status", "expected"),
    [
        (NotificationPolicy.NONE, TaskStatus.SUCCEEDED, False),
        (NotificationPolicy.NONE, TaskStatus.FAILED, False),
        (NotificationPolicy.ON_COMPLETION, TaskStatus.SUCCEEDED, True),
        (NotificationPolicy.ON_COMPLETION, TaskStatus.FAILED, False),
        (NotificationPolicy.ON_FAILURE, TaskStatus.SUCCEEDED, False),
        (NotificationPolicy.ON_FAILURE, TaskStatus.FAILED, True),
        (NotificationPolicy.ALWAYS, TaskStatus.SUCCEEDED, True),
        (NotificationPolicy.ALWAYS, TaskStatus.FAILED, True),
    ],
)
def test_notification_policy_decision(policy, status, expected) -> None:
    assert should_notify(policy, status) is expected


@pytest.mark.parametrize('outcome', [None, 'blocked', 'budget exhausted', 'uncertain', 'failed',
    'merged; deployment unverified', 'published; merge pending', 'preview'])
def test_notification_title_matches_publication_outcome(outcome):
    client = FakeHttpClient(httpx.Response(200, json={'status': 1, 'request': 'synthetic'}))
    service = NotificationService(PushoverProvider(settings=Settings(
        pushover_api_token='synthetic', pushover_user_key='synthetic'), client=client))
    task_id = uuid.uuid4()
    service.send_task_notification(TaskNotification(task_id=task_id,
        task_type=TaskType.DOCUMENTATION_MAINTENANCE, status=TaskStatus.SUCCEEDED,
        publication_status=outcome))
    assert client.request['data']['title'] == 'Personal Dot task ' + (outcome or 'succeeded')
    assert f'task {outcome or "completed successfully"}.' in client.request['data']['message']
    assert str(task_id) in client.request['data']['message']


@pytest.mark.parametrize('status,state,label', [
    (TaskStatus.SUCCEEDED, {'outcome': 'invalid_candidate'}, 'blocked'),
    (TaskStatus.SUCCEEDED, {'outcome': 'changes_requested'}, 'blocked'),
    (TaskStatus.SUCCEEDED, {'outcome': 'blocked'}, 'blocked'),
    (TaskStatus.SUCCEEDED, {'outcome': 'budget_exhausted'}, 'budget exhausted'),
    (TaskStatus.SUCCEEDED, {'outcome': 'uncertain'}, 'uncertain'),
    (TaskStatus.SUCCEEDED, {'outcome': 'merged', 'pool_blockers': ['transport']}, 'merged; deployment unverified'),
    (TaskStatus.FAILED, {}, 'failed'),
    (TaskStatus.UNCERTAIN, {}, 'uncertain'),
])
def test_maintenance_outbox_sends_result_status_without_source(status, state, label):
    from datetime import UTC, datetime
    from personal_dot.db import SessionLocal
    from personal_dot.models import Task, NotificationDelivery
    from personal_dot.notification_delivery import ensure_notification, deliver_notification

    client = FakeHttpClient(httpx.Response(200, json={'status': 1, 'request': 'synthetic'}))
    service = NotificationService(PushoverProvider(settings=Settings(
        pushover_api_token='synthetic', pushover_user_key='synthetic'), client=client))
    now = datetime.now(UTC)
    with SessionLocal() as db, db.begin():
        task = Task(type=TaskType.DOCUMENTATION_MAINTENANCE, status=status, payload={},
            notification_policy=NotificationPolicy.ALWAYS,
            result={**state, 'notify': True, 'source': 'SENSITIVE_SOURCE_MARKER'})
        db.add(task); db.flush()
        task_id = task.id
        ensure_notification(db, task, now)
    assert deliver_notification(task_id, now=now, service_factory=lambda: service)
    assert client.request['data']['title'] == 'Personal Dot task ' + label
    assert client.request['data']['message'] == f'Documentation_maintenance task {label}. ID: {task_id}'
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        assert task.status == status and task.result == {**state, 'notify': True, 'source': 'SENSITIVE_SOURCE_MARKER'}
        assert db.get(NotificationDelivery, task_id).status == 'sent'


@pytest.mark.anyio
async def test_notification_test_endpoint_uses_service(client, monkeypatch) -> None:
    from personal_dot import notification_routes

    class FakeNotificationService:
        def send_test_notification(self) -> NotificationResult:
            return NotificationResult(
                provider="pushover", provider_request_id="test-request"
            )

    monkeypatch.setattr(
        notification_routes,
        "get_notification_service",
        lambda: FakeNotificationService(),
    )

    response = await client.post("/notifications/test")

    assert response.status_code == 200
    assert response.json() == {
        "status": "sent",
        "provider": "pushover",
        "provider_request_id": "test-request",
    }


@pytest.mark.anyio
async def test_notification_test_endpoint_reports_missing_configuration(
    client, monkeypatch
) -> None:
    from personal_dot import notification_routes

    class MissingConfigurationService:
        def send_test_notification(self) -> NotificationResult:
            raise NotificationConfigurationError(
                "PUSHOVER_API_TOKEN is not configured"
            )

    monkeypatch.setattr(
        notification_routes,
        "get_notification_service",
        lambda: MissingConfigurationService(),
    )

    response = await client.post("/notifications/test")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "notification provider is not configured"
    }
