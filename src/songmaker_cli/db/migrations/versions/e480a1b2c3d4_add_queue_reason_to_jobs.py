"""add queue reason to jobs

Revision ID: e480a1b2c3d4
Revises: d5f8a3b21c46
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e480a1b2c3d4"
down_revision: str | Sequence[str] | None = "d5f8a3b21c46"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("queue_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "queue_reason")
