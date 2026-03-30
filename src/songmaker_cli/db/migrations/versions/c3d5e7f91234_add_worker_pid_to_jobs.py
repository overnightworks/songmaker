"""add worker_pid to jobs

Revision ID: c3d5e7f91234
Revises: b1c3f4a90210
Create Date: 2026-03-30 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c3d5e7f91234'
down_revision: Union[str, Sequence[str], None] = 'b1c3f4a90210'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.add_column("jobs", sa.Column("worker_pid", sa.Integer(), nullable=True))


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.drop_column("jobs", "worker_pid")
