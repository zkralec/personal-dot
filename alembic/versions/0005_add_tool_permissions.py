"""Add durable tool calls, approvals, notes, and resumable agent state.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_status",
        "tasks",
        "status IN "
        "('queued', 'running', 'waiting_for_approval', 'succeeded', 'failed')",
    )
    op.add_column(
        "tasks",
        sa.Column(
            "agent_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    op.create_table(
        "notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notes_task_id", "notes", ["task_id"], unique=False)

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("provider_call_id", sa.String(length=200), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("risk", sa.String(length=32), nullable=False),
        sa.Column(
            "arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("automatic_execution_allowed", sa.Boolean(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("approval_status", sa.String(length=32), nullable=False),
        sa.Column(
            "result", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("execution_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "risk IN ('unclassified', 'read_only', 'local_write', "
            "'external_communication', 'destructive', 'financial')",
            name="ck_tool_calls_risk",
        ),
        sa.CheckConstraint(
            "status IN "
            "('awaiting_approval', 'running', 'succeeded', 'failed', 'denied')",
            name="ck_tool_calls_status",
        ),
        sa.CheckConstraint(
            "approval_status IN "
            "('not_required', 'pending', 'approved', 'denied')",
            name="ck_tool_calls_approval_status",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id", "provider_call_id", name="uq_tool_calls_task_provider_call"
        ),
    )
    op.create_index(
        "ix_tool_calls_task_id", "tool_calls", ["task_id"], unique=False
    )
    op.create_index("ix_tool_calls_status", "tool_calls", ["status"], unique=False)

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("tool_call_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'denied')",
            name="ck_approval_requests_status",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tool_call_id"], ["tool_calls.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tool_call_id", name="uq_approval_requests_tool_call_id"
        ),
    )
    op.create_index(
        "ix_approval_requests_task_status",
        "approval_requests",
        ["task_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_approval_requests_task_status", table_name="approval_requests"
    )
    op.drop_table("approval_requests")
    op.drop_index("ix_tool_calls_status", table_name="tool_calls")
    op.drop_index("ix_tool_calls_task_id", table_name="tool_calls")
    op.drop_table("tool_calls")
    op.drop_index("ix_notes_task_id", table_name="notes")
    op.drop_table("notes")
    op.drop_column("tasks", "agent_state")
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_status",
        "tasks",
        "status IN ('queued', 'running', 'succeeded', 'failed')",
    )
