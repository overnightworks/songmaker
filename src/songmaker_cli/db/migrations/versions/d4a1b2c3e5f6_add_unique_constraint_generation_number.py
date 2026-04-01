"""add unique constraint on generation song_id + generation_number

Revision ID: d4a1b2c3e5f6
Revises: 2c0ce79a63eb
Create Date: 2026-04-01 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "d4a1b2c3e5f6"
down_revision: Union[str, None] = "2c0ce79a63eb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("generations") as batch_op:
        batch_op.create_unique_constraint(
            "uq_generation_song_number", ["song_id", "generation_number"],
        )


def downgrade() -> None:
    with op.batch_alter_table("generations") as batch_op:
        batch_op.drop_constraint("uq_generation_song_number", type_="unique")
