import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from personal_dot.db import Base


class TaskType(str, enum.Enum):
    ECHO = "echo"
    FAIL = "fail"
    AGENT = "agent"
    PROJECT_CHECK_IN = "project_check_in"


class TaskStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class NotificationPolicy(str, enum.Enum):
    NONE = "none"
    ON_COMPLETION = "on_completion"
    ON_FAILURE = "on_failure"
    ALWAYS = "always"


class ScheduleType(str, enum.Enum):
    ONCE = "once"
    INTERVAL = "interval"
    CRON = "cron"


class ToolRisk(str, enum.Enum):
    UNCLASSIFIED = "unclassified"
    READ_ONLY = "read_only"
    LOCAL_WRITE = "local_write"
    EXTERNAL_COMMUNICATION = "external_communication"
    DESTRUCTIVE = "destructive"
    FINANCIAL = "financial"


class ToolCallStatus(str, enum.Enum):
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"


class ApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class MemoryType(str, enum.Enum):
    USER_PREFERENCE = "user_preference"
    DURABLE_FACT = "durable_fact"
    PROJECT_NOTE = "project_note"
    AGENT_TASK_SUMMARY = "agent_task_summary"


task_type_column = SQLAlchemyEnum(
    TaskType,
    name="task_type",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda enum_class: [member.value for member in enum_class],
    length=32,
)
task_status_column = SQLAlchemyEnum(
    TaskStatus,
    name="task_status",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda enum_class: [member.value for member in enum_class],
    length=32,
)
notification_policy_column = SQLAlchemyEnum(
    NotificationPolicy,
    name="notification_policy",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda enum_class: [member.value for member in enum_class],
    length=32,
)
schedule_type_column = SQLAlchemyEnum(
    ScheduleType,
    name="schedule_type",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda enum_class: [member.value for member in enum_class],
    length=32,
)
tool_risk_column = SQLAlchemyEnum(
    ToolRisk,
    name="tool_risk",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda enum_class: [member.value for member in enum_class],
    length=32,
)
tool_call_status_column = SQLAlchemyEnum(
    ToolCallStatus,
    name="tool_call_status",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda enum_class: [member.value for member in enum_class],
    length=32,
)
approval_status_column = SQLAlchemyEnum(
    ApprovalStatus,
    name="approval_status",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda enum_class: [member.value for member in enum_class],
    length=32,
)
memory_type_column = SQLAlchemyEnum(
    MemoryType,
    name="memory_type",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda enum_class: [member.value for member in enum_class],
    length=32,
)


class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = (
        CheckConstraint("task_type IN ('echo', 'fail', 'agent')", name="ck_schedules_task_type"),
        CheckConstraint(
            "schedule_type IN ('once', 'interval', 'cron')",
            name="ck_schedules_type",
        ),
        CheckConstraint(
            "notification_policy IN "
            "('none', 'on_completion', 'on_failure', 'always')",
            name="ck_schedules_notification_policy",
        ),
        CheckConstraint(
            "(schedule_type = 'once' AND one_time_at IS NOT NULL "
            "AND interval_seconds IS NULL AND cron_expression IS NULL) OR "
            "(schedule_type = 'interval' AND one_time_at IS NULL "
            "AND interval_seconds IS NOT NULL AND interval_seconds >= 60 "
            "AND cron_expression IS NULL) OR "
            "(schedule_type = 'cron' AND one_time_at IS NULL "
            "AND interval_seconds IS NULL AND cron_expression IS NOT NULL)",
            name="ck_schedules_configuration",
        ),
        Index("ix_schedules_due", "enabled", "next_run_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    schedule_type: Mapped[ScheduleType] = mapped_column(schedule_type_column)
    task_type: Mapped[TaskType] = mapped_column(task_type_column)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    notification_policy: Mapped[NotificationPolicy] = mapped_column(
        notification_policy_column,
        default=NotificationPolicy.NONE,
        server_default=text("'none'"),
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    one_time_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cron_expression: Mapped[str | None] = mapped_column(String(200), nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(100), default="UTC", server_default=text("'UTC'")
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("type IN ('echo', 'fail', 'agent', 'project_check_in')", name="ck_tasks_type"),
        CheckConstraint(
            "status IN "
            "('queued', 'running', 'waiting_for_approval', 'succeeded', 'failed')",
            name="ck_tasks_status",
        ),
        CheckConstraint(
            "notification_policy IN "
            "('none', 'on_completion', 'on_failure', 'always')",
            name="ck_tasks_notification_policy",
        ),
        Index("ix_tasks_created_at", "created_at"),
        Index("ix_tasks_status", "status"),
        Index("ix_tasks_schedule_id", "schedule_id"),
        UniqueConstraint(
            "schedule_id", "scheduled_for", name="uq_tasks_schedule_occurrence"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    type: Mapped[TaskType] = mapped_column(task_type_column)
    status: Mapped[TaskStatus] = mapped_column(task_status_column)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    notification_policy: Mapped[NotificationPolicy] = mapped_column(
        notification_policy_column,
        default=NotificationPolicy.NONE,
        server_default=text("'none'"),
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    agent_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schedules.id", ondelete="RESTRICT"), nullable=True
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    enqueue_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    enqueue_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (Index("ix_notes_task_id", "task_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="RESTRICT")
    )
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ToolCall(Base):
    __tablename__ = "tool_calls"
    __table_args__ = (
        CheckConstraint(
            "risk IN ('unclassified', 'read_only', 'local_write', "
            "'external_communication', 'destructive', 'financial')",
            name="ck_tool_calls_risk",
        ),
        CheckConstraint(
            "status IN "
            "('awaiting_approval', 'running', 'succeeded', 'failed', 'denied')",
            name="ck_tool_calls_status",
        ),
        CheckConstraint(
            "approval_status IN "
            "('not_required', 'pending', 'approved', 'denied')",
            name="ck_tool_calls_approval_status",
        ),
        UniqueConstraint(
            "task_id", "provider_call_id", name="uq_tool_calls_task_provider_call"
        ),
        Index("ix_tool_calls_task_id", "task_id"),
        Index("ix_tool_calls_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="RESTRICT")
    )
    provider_call_id: Mapped[str] = mapped_column(String(200))
    tool_name: Mapped[str] = mapped_column(String(100))
    risk: Mapped[ToolRisk] = mapped_column(tool_risk_column)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB)
    automatic_execution_allowed: Mapped[bool] = mapped_column(Boolean)
    requires_approval: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[ToolCallStatus] = mapped_column(tool_call_status_column)
    approval_status: Mapped[ApprovalStatus] = mapped_column(approval_status_column)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    execution_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'denied')",
            name="ck_approval_requests_status",
        ),
        UniqueConstraint("tool_call_id", name="uq_approval_requests_tool_call_id"),
        Index("ix_approval_requests_task_status", "task_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="RESTRICT")
    )
    tool_call_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tool_calls.id", ondelete="RESTRICT")
    )
    status: Mapped[ApprovalStatus] = mapped_column(approval_status_column)
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = (
        CheckConstraint(
            "type IN ('user_preference', 'durable_fact', 'project_note', "
            "'agent_task_summary')",
            name="ck_memories_type",
        ),
        Index("ix_memories_enabled_type", "enabled", "type"),
        Index("ix_memories_updated_at", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    type: Mapped[MemoryType] = mapped_column(memory_type_column)
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    tags: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
