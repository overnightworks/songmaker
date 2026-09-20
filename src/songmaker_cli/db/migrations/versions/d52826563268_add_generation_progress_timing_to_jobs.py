"""Add generation progress timing to jobs.

Revision ID: d52826563268
Revises: f41ebd8f5103
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d52826563268"
down_revision: str | Sequence[str] | None = "f41ebd8f5103"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("running_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("take_index", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("take_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("take_count")
        batch_op.drop_column("take_index")
        batch_op.drop_column("running_since")
