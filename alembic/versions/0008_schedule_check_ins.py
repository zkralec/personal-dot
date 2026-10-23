"""Schedule check-ins and persist independent notification delivery intent.

Revision ID: 0008
Revises: 0007
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_schedules_task_type", "schedules", type_="check")
    op.create_check_constraint("ck_schedules_task_type", "schedules", "task_type IN ('echo', 'fail', 'agent', 'project_check_in')")
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")
    op.create_check_constraint("ck_tasks_status", "tasks", "status IN ('queued', 'running', 'waiting_for_approval', 'succeeded', 'failed', 'uncertain')")
    op.create_table(
        "notification_deliveries",
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("attempts", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'sending', 'sent', 'exhausted')", name="ck_notification_deliveries_status"),
        sa.CheckConstraint("attempt_count >= 0 AND attempt_count <= 3", name="ck_notification_deliveries_attempts"),
    )
    op.create_index("ix_notification_deliveries_due", "notification_deliveries", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_table("notification_deliveries")
    op.drop_constraint("ck_tasks_status", "tasks", type_="check")
    op.create_check_constraint("ck_tasks_status", "tasks", "status IN ('queued', 'running', 'waiting_for_approval', 'succeeded', 'failed')")
    op.drop_constraint("ck_schedules_task_type", "schedules", type_="check")
    op.create_check_constraint("ck_schedules_task_type", "schedules", "task_type IN ('echo', 'fail', 'agent')")
