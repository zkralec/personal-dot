import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import httpx

from personal_dot.config import Settings, get_settings
from personal_dot.models import NotificationPolicy, TaskStatus, TaskType

PUSHOVER_MESSAGES_URL = "https://api.pushover.net/1/messages.json"


class NotificationError(RuntimeError):
    """Base class for safe notification failures."""


class NotificationConfigurationError(NotificationError):
    """Raised when the configured provider cannot be initialized or used."""


class NotificationDeliveryError(NotificationError):
    """Raised when a provider rejects or cannot deliver a notification."""


@dataclass(frozen=True)
class NotificationMessage:
    title: str
    body: str


@dataclass(frozen=True)
class NotificationResult:
    provider: str
    provider_request_id: str | None = None


@dataclass(frozen=True)
class TaskNotification:
    task_id: uuid.UUID
    task_type: TaskType
    status: TaskStatus


class NotificationProvider(Protocol):
    name: str

    def send(self, message: NotificationMessage) -> NotificationResult: ...


class HttpClient(Protocol):
    def post(
        self,
        url: str,
        *,
        data: dict[str, str],
        timeout: float | None = None,
    ) -> httpx.Response: ...


class PushoverProvider:
    name = "pushover"

    def __init__(
        self,
        settings: Settings | None = None,
        client: HttpClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client

    def send(self, message: NotificationMessage) -> NotificationResult:
        token = self._required_secret(
            self.settings.pushover_api_token, "PUSHOVER_API_TOKEN"
        )
        user = self._required_secret(
            self.settings.pushover_user_key, "PUSHOVER_USER_KEY"
        )
        payload = {
            "token": token,
            "user": user,
            "title": message.title[:250],
            "message": message.body[:1024],
        }

        try:
            if self.client is not None:
                response = self.client.post(
                    PUSHOVER_MESSAGES_URL,
                    data=payload,
                    timeout=self.settings.notification_timeout_seconds,
                )
            else:
                with httpx.Client(
                    timeout=self.settings.notification_timeout_seconds
                ) as client:
                    response = client.post(PUSHOVER_MESSAGES_URL, data=payload)
        except httpx.HTTPError as exc:
            raise NotificationDeliveryError(
                f"Pushover request failed: {type(exc).__name__}"
            ) from exc

        if not response.is_success:
            raise NotificationDeliveryError(
                f"Pushover request failed with HTTP {response.status_code}"
            )
        try:
            response_data: Any = response.json()
        except ValueError as exc:
            raise NotificationDeliveryError(
                "Pushover returned an invalid response"
            ) from exc
        if not isinstance(response_data, dict) or response_data.get("status") != 1:
            raise NotificationDeliveryError("Pushover rejected the notification")

        request_id = response_data.get("request")
        return NotificationResult(
            provider=self.name,
            provider_request_id=request_id if isinstance(request_id, str) else None,
        )

    @staticmethod
    def _required_secret(secret: Any, variable_name: str) -> str:
        if secret is None:
            raise NotificationConfigurationError(
                f"{variable_name} is not configured"
            )
        value = secret.get_secret_value().strip()
        if not value:
            raise NotificationConfigurationError(
                f"{variable_name} is not configured"
            )
        return value


class NotificationService:
    def __init__(self, provider: NotificationProvider) -> None:
        self.provider = provider

    def send_task_notification(
        self, notification: TaskNotification
    ) -> NotificationResult:
        status_label = (
            "completed successfully"
            if notification.status == TaskStatus.SUCCEEDED
            else "failed"
        )
        message = NotificationMessage(
            title=f"Personal Dot task {notification.status.value}",
            body=(
                f"{notification.task_type.value.capitalize()} task {status_label}. "
                f"ID: {notification.task_id}"
            ),
        )
        return self.provider.send(message)

    def send_test_notification(self) -> NotificationResult:
        return self.provider.send(
            NotificationMessage(
                title="Personal Dot test",
                body="Pushover notifications are configured correctly.",
            )
        )


def should_notify(policy: NotificationPolicy, status: TaskStatus) -> bool:
    if policy == NotificationPolicy.ALWAYS:
        return status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED}
    if policy == NotificationPolicy.ON_COMPLETION:
        return status == TaskStatus.SUCCEEDED
    if policy == NotificationPolicy.ON_FAILURE:
        return status == TaskStatus.FAILED
    return False


@lru_cache
def get_notification_service() -> NotificationService:
    settings = get_settings()
    if settings.notification_provider == "pushover":
        return NotificationService(PushoverProvider(settings=settings))
    raise NotificationConfigurationError(
        f"unsupported notification provider: {settings.notification_provider}"
    )
