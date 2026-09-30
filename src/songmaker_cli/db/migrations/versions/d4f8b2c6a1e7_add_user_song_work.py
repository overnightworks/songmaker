"""add user song work

Revision ID: d4f8b2c6a1e7
Revises: c3e7a91f5d20
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4f8b2c6a1e7"
down_revision: str | Sequence[str] | None = "c3e7a91f5d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SONG_ID_INDEX = "ix_user_song_work_song_id"


def upgrade() -> None:
    op.create_table(
        "user_song_work",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("song_id", sa.String(length=36), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("played_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["song_id"], ["songs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "song_id"),
    )
    op.create_index(SONG_ID_INDEX, "user_song_work", ["song_id"])


def downgrade() -> None:
    op.drop_index(SONG_ID_INDEX, table_name="user_song_work")
    op.drop_table("user_song_work")
