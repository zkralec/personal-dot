"""Add persistent schedules and task occurrence linkage.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("schedule_type", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("one_time_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("cron_expression", sa.String(length=200), nullable=True),
        sa.Column(
            "timezone",
            sa.String(length=100),
            server_default=sa.text("'UTC'"),
            nullable=False,
        ),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "schedule_type IN ('once', 'interval', 'cron')",
            name="ck_schedules_type",
        ),
        sa.CheckConstraint(
            "(schedule_type = 'once' AND one_time_at IS NOT NULL "
            "AND interval_seconds IS NULL AND cron_expression IS NULL) OR "
            "(schedule_type = 'interval' AND one_time_at IS NULL "
            "AND interval_seconds IS NOT NULL AND interval_seconds >= 60 "
            "AND cron_expression IS NULL) OR "
            "(schedule_type = 'cron' AND one_time_at IS NULL "
            "AND interval_seconds IS NULL AND cron_expression IS NOT NULL)",
            name="ck_schedules_configuration",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_schedules_due", "schedules", ["enabled", "next_run_at"], unique=False
    )
    op.add_column("tasks", sa.Column("schedule_id", sa.Uuid(), nullable=True))
    op.add_column(
        "tasks", sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "tasks",
        sa.Column("enqueue_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("tasks", sa.Column("enqueue_error", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_tasks_schedule_id_schedules",
        "tasks",
        "schedules",
        ["schedule_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_tasks_schedule_occurrence", "tasks", ["schedule_id", "scheduled_for"]
    )
    op.create_index("ix_tasks_schedule_id", "tasks", ["schedule_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tasks_schedule_id", table_name="tasks")
    op.drop_constraint("uq_tasks_schedule_occurrence", "tasks", type_="unique")
    op.drop_constraint(
        "fk_tasks_schedule_id_schedules", "tasks", type_="foreignkey"
    )
    op.drop_column("tasks", "enqueue_error")
    op.drop_column("tasks", "enqueue_attempted_at")
    op.drop_column("tasks", "scheduled_for")
    op.drop_column("tasks", "schedule_id")
    op.drop_index("ix_schedules_due", table_name="schedules")
    op.drop_table("schedules")
