"""Allow manual read-only GitHub discovery and inspection tasks.

Revision ID: 0010
Revises: 0009
"""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_tasks_type", "tasks", type_="check")
    op.create_check_constraint("ck_tasks_type", "tasks",
        "type IN ('echo', 'fail', 'agent', 'project_check_in', 'github_discover', 'github_inspect')")


def downgrade() -> None:
    # Will fail safely if read-task records still exist; never discard history.
    op.drop_constraint("ck_tasks_type", "tasks", type_="check")
    op.create_check_constraint("ck_tasks_type", "tasks",
        "type IN ('echo', 'fail', 'agent', 'project_check_in')")
