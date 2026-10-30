import uuid
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from personal_dot.check_in_schemas import CheckInRequest
from personal_dot.github import repository_name
from personal_dot.documentation_schemas import DocumentationRequest, PublicationRequest

from personal_dot.models import (
    ApprovalStatus,
    MemoryType,
    NotificationPolicy,
    ScheduleType,
    TaskStatus,
    TaskType,
    ToolCallStatus,
    ToolRisk,
)


def _normalize_tags(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        tag = value.strip().lower()
        if not tag:
            raise ValueError("tags must not be blank")
        if len(tag) > 50:
            raise ValueError("tags must be at most 50 characters")
        allowed = "abcdefghijklmnopqrstuvwxyz0123456789:_-"
        if any(character not in allowed for character in tag):
            raise ValueError(
                "tags may contain only lowercase letters, numbers, colon, underscore, and hyphen"
            )
        if tag not in normalized:
            normalized.append(tag)
    return normalized


class MemorySelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    types: list[MemoryType] = Field(default_factory=list, max_length=4)
    tags: list[str] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=10, ge=1, le=10)

    @field_validator("ids", "types")
    @classmethod
    def values_must_be_unique(cls, values: list[Any]) -> list[Any]:
        if len(values) != len(set(values)):
            raise ValueError("selection values must be unique")
        return values

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        return _normalize_tags(values)


class AgentTaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=1, max_length=50_000)
    context: str | None = Field(default=None, max_length=200_000)
    memory: MemorySelection | None = None

    @field_validator("instruction")
    @classmethod
    def instruction_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("instruction must not be blank")
        return value


class GitHubDiscoveryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(default=1, ge=1, le=1_000_000)


class GitHubInspectionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str = Field(min_length=1, max_length=100)

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        return repository_name(value)


class TaskCreate(BaseModel):
    type: TaskType = TaskType.ECHO
    payload: dict[str, Any] = Field(default_factory=dict)
    notification_policy: NotificationPolicy = NotificationPolicy.NONE

    @model_validator(mode="after")
    def validate_payload_for_type(self) -> "TaskCreate":
        if self.type == TaskType.AGENT:
            validated = AgentTaskPayload.model_validate(self.payload)
            self.payload = validated.model_dump(mode="json", exclude_none=True)
        elif self.type == TaskType.PROJECT_CHECK_IN:
            check_in = CheckInRequest.model_validate(self.payload)
            self.payload = check_in.model_dump(mode="json")
        elif self.type == TaskType.DOCUMENTATION_PUBLISH:
            self.payload = PublicationRequest.model_validate(self.payload).model_dump(mode="json")
        elif self.type == TaskType.DOCUMENTATION_PREVIEW:
            self.payload = DocumentationRequest.model_validate(self.payload).model_dump(mode="json")
            if self.notification_policy != NotificationPolicy.NONE:
                raise ValueError("Documentation previews require notification_policy=none")
        elif self.type in {TaskType.GITHUB_DISCOVER, TaskType.GITHUB_INSPECT}:
            model = GitHubDiscoveryPayload if self.type == TaskType.GITHUB_DISCOVER else GitHubInspectionPayload
            self.payload = model.model_validate(self.payload).model_dump(mode="json")
            if self.notification_policy != NotificationPolicy.NONE:
                raise ValueError("GitHub read tasks require notification_policy=none")
        return self


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: TaskType
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    payload: dict[str, Any]
    notification_policy: NotificationPolicy
    result: dict[str, Any] | None
    error: str | None
    execution_metadata: dict[str, Any]
    schedule_id: uuid.UUID | None
    scheduled_for: datetime | None
    enqueue_attempted_at: datetime | None
    enqueue_error: str | None


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    schedule_type: ScheduleType
    task: TaskCreate
    enabled: bool = True
    run_at: datetime | None = None
    start_at: datetime | None = None
    interval_seconds: int | None = Field(default=None, ge=60)
    cron_expression: str | None = Field(default=None, max_length=200)
    timezone: str = Field(default="UTC", min_length=1, max_length=100)

    @field_validator("run_at", "start_at")
    @classmethod
    def datetime_must_be_timezone_aware(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("datetime must include a timezone offset")
        return value

    @field_validator("timezone")
    @classmethod
    def timezone_must_exist(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def validate_schedule_configuration(self) -> "ScheduleCreate":
        if self.task.type in {TaskType.GITHUB_DISCOVER, TaskType.GITHUB_INSPECT, TaskType.DOCUMENTATION_PREVIEW, TaskType.DOCUMENTATION_PUBLISH}:
            raise ValueError("GitHub discovery and inspection are manual tasks only")
        if self.task.type == TaskType.PROJECT_CHECK_IN:
            if "enabled" not in self.model_fields_set:
                self.enabled = False
            if self.enabled:
                raise ValueError("create check-in schedules disabled, then explicitly enable them")
        if self.schedule_type == ScheduleType.ONCE:
            if self.run_at is None:
                raise ValueError("run_at is required for a one-time schedule")
            if any(
                value is not None
                for value in (
                    self.start_at,
                    self.interval_seconds,
                    self.cron_expression,
                )
            ):
                raise ValueError("one-time schedules accept only run_at")
        elif self.schedule_type == ScheduleType.INTERVAL:
            if self.interval_seconds is None:
                raise ValueError("interval_seconds is required for an interval schedule")
            if self.run_at is not None or self.cron_expression is not None:
                raise ValueError(
                    "interval schedules accept interval_seconds and optional start_at"
                )
        else:
            if self.cron_expression is None:
                raise ValueError("cron_expression is required for a cron schedule")
            if len(self.cron_expression.split()) != 5:
                raise ValueError("cron_expression must use exactly five fields")
            if not croniter.is_valid(self.cron_expression, strict=True):
                raise ValueError("cron_expression is invalid")
            if any(
                value is not None
                for value in (self.run_at, self.start_at, self.interval_seconds)
            ):
                raise ValueError("cron schedules accept only cron_expression")
        return self


class ScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class ScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    schedule_type: ScheduleType
    task_type: TaskType
    payload: dict[str, Any]
    notification_policy: NotificationPolicy
    enabled: bool
    one_time_at: datetime | None
    interval_seconds: int | None
    cron_expression: str | None
    timezone: str
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    postgres: Literal["ok", "unavailable"]
    redis: Literal["ok", "unavailable"]


class TestNotificationResponse(BaseModel):
    status: Literal["sent"]
    provider: str
    provider_request_id: str | None = None


class ToolDefinitionRead(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    risk: ToolRisk
    automatic_execution_allowed: bool
    requires_approval: bool


class ToolCallRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    provider_call_id: str
    tool_name: str
    risk: ToolRisk
    arguments: dict[str, Any]
    automatic_execution_allowed: bool
    requires_approval: bool
    status: ToolCallStatus
    approval_status: ApprovalStatus
    result: dict[str, Any] | None
    error: str | None
    requested_at: datetime
    execution_started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    tool_call_id: uuid.UUID
    status: ApprovalStatus
    summary: str
    created_at: datetime
    decided_at: datetime | None
    decision_reason: str | None


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=1000)


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: MemoryType
    content: str = Field(min_length=1, max_length=5000)
    source: str = Field(default="manual", min_length=1, max_length=100)
    enabled: bool = True
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("content", "source")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        return _normalize_tags(values)


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: MemoryType | None = None
    content: str | None = Field(default=None, min_length=1, max_length=5000)
    source: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    tags: list[str] | None = Field(default=None, max_length=20)

    @field_validator("content", "source")
    @classmethod
    def text_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str] | None) -> list[str] | None:
        return _normalize_tags(values) if values is not None else None

    @model_validator(mode="after")
    def require_update_field(self) -> "MemoryUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("memory fields cannot be null")
        return self


class MemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: MemoryType
    content: str
    source: str
    enabled: bool
    tags: list[str]
    created_at: datetime
    updated_at: datetime
