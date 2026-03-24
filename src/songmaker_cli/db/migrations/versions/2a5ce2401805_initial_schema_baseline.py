"""initial schema baseline

Revision ID: 2a5ce2401805
Revises:
Create Date: 2026-03-24

Captures the current schema. Only applies the safe additive change
(index on scores.generation_id). Existing DBs may have a leftover
jobs.generation_id column — harmless, ignored by the ORM.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "2a5ce2401805"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_scores_generation_id"), "scores", ["generation_id"], unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_scores_generation_id"), table_name="scores")
