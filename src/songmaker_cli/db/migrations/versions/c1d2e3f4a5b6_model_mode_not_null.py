"""model_mode NOT NULL on generations

Backfill any NULL ``generations.model_mode`` to ``'sft'`` (the historic
default) and add a NOT NULL constraint. The corrupted-vs-correct distinction
for the post-recovery rows can't be perfectly recovered (the original
requested model is gone), so we accept the data loss in favour of a clean
schema. The constraint stops the next round of silent fallbacks at the
database boundary.

Revision ID: c1d2e3f4a5b6
Revises: b8c9d1e2f3a4
Create Date: 2026-04-08 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "b8c9d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE generations SET model_mode = 'sft' WHERE model_mode IS NULL")
    with op.batch_alter_table("generations") as batch_op:
        batch_op.alter_column(
            "model_mode", existing_type=sa.String(10), nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("generations") as batch_op:
        batch_op.alter_column(
            "model_mode", existing_type=sa.String(10), nullable=True,
        )
