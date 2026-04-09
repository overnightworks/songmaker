"""add index on generations.version_id

Revision ID: a1b2c3d4e5f6
Revises: d7e8f9a0b1c2
Create Date: 2026-04-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'd7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.create_index(
        "ix_generations_version_id",
        "generations",
        ["version_id"],
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.drop_index("ix_generations_version_id", table_name="generations")
