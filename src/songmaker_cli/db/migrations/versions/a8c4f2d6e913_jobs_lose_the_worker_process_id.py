"""jobs lose the worker process id

Images that still map the column select it in every jobs query, so the drop runs only
once no running image maps it. The downgrade adds the column back nullable and empty:
the old values are stale process ids nothing reads.

Revision ID: a8c4f2d6e913
Revises: b64e2a7c9d10
Create Date: 2026-11-28 12:00:00.000000

"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a8c4f2d6e913'
down_revision: str | Sequence[str] | None = 'b64e2a7c9d10'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _is_sqlite():
        op.drop_column("jobs", "worker_pid")


def downgrade() -> None:
    if not _is_sqlite():
        op.add_column("jobs", sa.Column("worker_pid", sa.Integer(), nullable=True))


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"
