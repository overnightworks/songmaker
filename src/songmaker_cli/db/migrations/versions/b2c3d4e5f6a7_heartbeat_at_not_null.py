"""heartbeat_at NOT NULL + backfill

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-09 12:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.execute(
        "UPDATE jobs SET heartbeat_at = started_at WHERE heartbeat_at IS NULL"
    )
    op.alter_column(
        "jobs",
        "heartbeat_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.alter_column(
        "jobs",
        "heartbeat_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
