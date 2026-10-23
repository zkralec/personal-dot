"""Add per-task and per-schedule notification policy.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "schedules",
        sa.Column(
            "notification_policy",
            sa.String(length=32),
            server_default=sa.text("'none'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_schedules_notification_policy",
        "schedules",
        "notification_policy IN "
        "('none', 'on_completion', 'on_failure', 'always')",
    )
    op.add_column(
        "tasks",
        sa.Column(
            "notification_policy",
            sa.String(length=32),
            server_default=sa.text("'none'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_tasks_notification_policy",
        "tasks",
        "notification_policy IN "
        "('none', 'on_completion', 'on_failure', 'always')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_tasks_notification_policy", "tasks", type_="check"
    )
    op.drop_column("tasks", "notification_policy")
    op.drop_constraint(
        "ck_schedules_notification_policy", "schedules", type_="check"
    )
    op.drop_column("schedules", "notification_policy")
