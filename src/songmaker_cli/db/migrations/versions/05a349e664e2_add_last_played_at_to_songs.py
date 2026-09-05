"""add last played at to songs

Revision ID: 05a349e664e2
Revises: a8c4d1e9f275
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "05a349e664e2"
down_revision: str | Sequence[str] | None = "a8c4d1e9f275"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "songs",
        sa.Column("last_played_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("songs", "last_played_at")
