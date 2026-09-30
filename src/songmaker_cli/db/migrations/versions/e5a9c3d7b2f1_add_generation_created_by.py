"""add generation created_by

Existing takes keep ``created_by = NULL``: their maker cannot be recovered
honestly from job time windows, so no backfill is attempted.

Revision ID: e5a9c3d7b2f1
Revises: d4f8b2c6a1e7
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5a9c3d7b2f1"
down_revision: str | Sequence[str] | None = "d4f8b2c6a1e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CREATED_BY_FOREIGN_KEY = "fk_generations_created_by_users"
CREATED_BY_INDEX = "ix_generations_created_by"


def upgrade() -> None:
    with op.batch_alter_table("generations") as batch_op:
        batch_op.add_column(sa.Column("created_by", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            CREATED_BY_FOREIGN_KEY, "users", ["created_by"], ["id"], ondelete="SET NULL",
        )
        batch_op.create_index(CREATED_BY_INDEX, ["created_by"])


def downgrade() -> None:
    with op.batch_alter_table("generations") as batch_op:
        batch_op.drop_index(CREATED_BY_INDEX)
        batch_op.drop_constraint(CREATED_BY_FOREIGN_KEY, type_="foreignkey")
        batch_op.drop_column("created_by")
