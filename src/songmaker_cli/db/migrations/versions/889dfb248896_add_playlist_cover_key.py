"""add playlist cover_key

Revision ID: 889dfb248896
Revises: 05a349e664e2
Create Date: 2026-09-05

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "889dfb248896"
down_revision: str | Sequence[str] | None = "05a349e664e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("playlists", sa.Column("cover_key", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("playlists", "cover_key")
