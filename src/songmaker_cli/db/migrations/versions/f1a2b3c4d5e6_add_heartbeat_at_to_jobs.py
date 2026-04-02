"""add heartbeat_at to jobs

Revision ID: f1a2b3c4d5e6
Revises: af88e1bd4d6d
Create Date: 2026-04-02 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'af88e1bd4d6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.add_column("jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.drop_column("jobs", "heartbeat_at")
