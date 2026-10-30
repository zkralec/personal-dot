"""Budgeted, account-wide daily documentation maintenance.

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('ck_tasks_type', 'tasks', type_='check')
    op.create_check_constraint('ck_tasks_type', 'tasks', "type IN ('echo', 'fail', 'agent', 'project_check_in', 'github_discover', 'github_inspect', 'documentation_preview', 'documentation_publish', 'documentation_maintenance')")
    op.drop_constraint('ck_schedules_task_type', 'schedules', type_='check')
    op.create_check_constraint('ck_schedules_task_type', 'schedules', "task_type IN ('echo', 'fail', 'agent', 'project_check_in', 'documentation_maintenance')")
    op.add_column('tasks', sa.Column('maintenance_parent_id', sa.Uuid(), nullable=True))
    op.create_foreign_key('fk_tasks_maintenance_parent', 'tasks', 'tasks', ['maintenance_parent_id'], ['id'], ondelete='RESTRICT')
    op.create_index('uq_maintenance_schedule', 'schedules', ['task_type'], unique=True, postgresql_where=sa.text("task_type = 'documentation_maintenance'"))
    op.create_table('maintenance_control',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('paused', sa.Boolean(), nullable=False),
        sa.Column('configuration', postgresql.JSONB(), nullable=False), sa.Column('configuration_sha256', sa.String(64), nullable=False),
        sa.Column('schedule_id', sa.Uuid(), sa.ForeignKey('schedules.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('pilot_task_id', sa.Uuid(), sa.ForeignKey('tasks.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('discovered_at', sa.DateTime(timezone=True)), sa.Column('discovery', postgresql.JSONB(), nullable=False))
    op.create_table('maintenance_repositories', sa.Column('repository_id', sa.BigInteger(), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False), sa.Column('identity', postgresql.JSONB(), nullable=False),
        sa.Column('available', sa.Boolean(), nullable=False), sa.Column('last_checked_at', sa.DateTime(timezone=True)),
        sa.Column('state', postgresql.JSONB(), nullable=False))
    op.create_table('maintenance_assessments', sa.Column('repository_id', sa.BigInteger(), primary_key=True),
        sa.Column('fingerprint', sa.String(64), primary_key=True), sa.Column('outcome', sa.String(64), nullable=False),
        sa.Column('assessed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('task_id', sa.Uuid(), sa.ForeignKey('tasks.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('state', postgresql.JSONB(), nullable=False))
    op.create_table('maintenance_days', sa.Column('day', sa.Date(), primary_key=True),
        sa.Column('reserved_microusd', sa.Integer(), nullable=False), sa.Column('model_calls', sa.Integer(), nullable=False),
        sa.Column('assessment_owner', sa.Uuid(), sa.ForeignKey('tasks.id', ondelete='RESTRICT')),
        sa.Column('merge_owner', sa.Uuid(), sa.ForeignKey('tasks.id', ondelete='RESTRICT')),
        sa.CheckConstraint('reserved_microusd >= 0 AND model_calls >= 0 AND model_calls <= 2', name='ck_maintenance_day_limits'))
    op.create_table('maintenance_runs', sa.Column('task_id', sa.Uuid(), sa.ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('configuration_sha256', sa.String(64), nullable=False), sa.Column('budget_day', sa.Date()),
        sa.Column('reserved_microusd', sa.Integer(), nullable=False), sa.Column('state', postgresql.JSONB(), nullable=False))


def downgrade() -> None:
    for table in ('maintenance_runs', 'maintenance_days', 'maintenance_assessments', 'maintenance_repositories', 'maintenance_control'):
        op.drop_table(table)
    op.drop_index('uq_maintenance_schedule', table_name='schedules')
    op.drop_constraint('fk_tasks_maintenance_parent', 'tasks', type_='foreignkey')
    op.drop_column('tasks', 'maintenance_parent_id')
    op.drop_constraint('ck_schedules_task_type', 'schedules', type_='check')
    op.create_check_constraint('ck_schedules_task_type', 'schedules', "task_type IN ('echo', 'fail', 'agent', 'project_check_in')")
    op.drop_constraint('ck_tasks_type', 'tasks', type_='check')
    op.create_check_constraint('ck_tasks_type', 'tasks', "type IN ('echo', 'fail', 'agent', 'project_check_in', 'github_discover', 'github_inspect', 'documentation_preview', 'documentation_publish')")
