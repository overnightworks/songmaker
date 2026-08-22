"""add song cover_key

Revision ID: d8e9f0a1b2c3
Revises: c7e8a1b0d2f4
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8e9f0a1b2c3"
down_revision: str | Sequence[str] | None = "c7e8a1b0d2f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("songs", sa.Column("cover_key", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("songs", "cover_key")
