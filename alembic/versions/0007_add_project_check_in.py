"""Add manual project check-in tasks; prohibit scheduled check-ins.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_tasks_type", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_type", "tasks", "type IN ('echo', 'fail', 'agent', 'project_check_in')"
    )
    op.create_check_constraint(
        "ck_schedules_task_type", "schedules", "task_type IN ('echo', 'fail', 'agent')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_schedules_task_type", "schedules", type_="check")
    op.drop_constraint("ck_tasks_type", "tasks", type_="check")
    op.create_check_constraint("ck_tasks_type", "tasks", "type IN ('echo', 'fail', 'agent')")
