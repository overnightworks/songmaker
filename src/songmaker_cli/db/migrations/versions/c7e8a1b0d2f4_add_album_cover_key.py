"""add album cover_key

Revision ID: c7e8a1b0d2f4
Revises: f4a5b6c7d8e9
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e8a1b0d2f4"
down_revision: str | Sequence[str] | None = "f4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("albums", sa.Column("cover_key", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("albums", "cover_key")
