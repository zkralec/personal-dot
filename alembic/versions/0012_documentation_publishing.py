"""Durable bounded documentation publication jobs.

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('ck_tasks_type', 'tasks', type_='check')
    op.create_check_constraint('ck_tasks_type', 'tasks',
        "type IN ('echo', 'fail', 'agent', 'project_check_in', 'github_discover', 'github_inspect', 'documentation_preview', 'documentation_publish')")
    op.create_table('documentation_publications',
        sa.Column('preview_task_id', sa.Uuid(), sa.ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('repository_id', sa.BigInteger(), nullable=False),
        sa.Column('completed', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('state', postgresql.JSONB(), nullable=False))
    op.create_index('uq_documentation_active_repository', 'documentation_publications', ['repository_id'],
                    unique=True, postgresql_where=sa.text('completed = false'))


def downgrade() -> None:
    op.drop_table('documentation_publications')
    op.drop_constraint('ck_tasks_type', 'tasks', type_='check')
    op.create_check_constraint('ck_tasks_type', 'tasks',
        "type IN ('echo', 'fail', 'agent', 'project_check_in', 'github_discover', 'github_inspect', 'documentation_preview')")
