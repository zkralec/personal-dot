"""Allow manual bounded documentation-preview tasks.

Revision ID: 0011
Revises: 0010
"""
from alembic import op

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('ck_tasks_type', 'tasks', type_='check')
    op.create_check_constraint('ck_tasks_type', 'tasks',
        "type IN ('echo', 'fail', 'agent', 'project_check_in', 'github_discover', 'github_inspect', 'documentation_preview')")


def downgrade() -> None:
    op.drop_constraint('ck_tasks_type', 'tasks', type_='check')
    op.create_check_constraint('ck_tasks_type', 'tasks',
        "type IN ('echo', 'fail', 'agent', 'project_check_in', 'github_discover', 'github_inspect')")
