"""Add agent task type and execution metadata.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-30
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_tasks_type", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_type",
        "tasks",
        "type IN ('echo', 'fail', 'agent')",
    )
    op.add_column(
        "tasks",
        sa.Column(
            "execution_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("tasks", "execution_metadata")
    op.drop_constraint("ck_tasks_type", "tasks", type_="check")
    op.create_check_constraint(
        "ck_tasks_type",
        "tasks",
        "type IN ('echo', 'fail')",
    )
