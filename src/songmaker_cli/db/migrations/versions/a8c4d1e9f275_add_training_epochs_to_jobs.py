"""add training epochs to jobs

Revision ID: a8c4d1e9f275
Revises: f533c1a00001
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8c4d1e9f275"
down_revision: str | Sequence[str] | None = "f533c1a00001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.add_column(sa.Column("current_epoch", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("train_epochs", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("training_started_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_column("training_started_at")
        batch_op.drop_column("train_epochs")
        batch_op.drop_column("current_epoch")
