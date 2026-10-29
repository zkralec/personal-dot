"""Fence task state writes by execution ownership.

Revision ID: 0009
Revises: 0008
"""

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical/idle tasks have no owner; each new claim assigns a UUID.
    op.add_column("tasks", sa.Column("execution_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "execution_id")
