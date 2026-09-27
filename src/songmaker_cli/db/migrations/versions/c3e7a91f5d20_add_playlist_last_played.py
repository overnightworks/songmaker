"""add playlist last played

Revision ID: c3e7a91f5d20
Revises: 98acbb42010e
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3e7a91f5d20"
down_revision: str | Sequence[str] | None = "98acbb42010e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LAST_PLAYED_SONG_FOREIGN_KEY = "fk_playlists_last_played_song_id_songs"
LAST_PLAYED_SONG_INDEX = "ix_playlists_last_played_song_id"


def upgrade() -> None:
    with op.batch_alter_table("playlists") as batch_op:
        batch_op.add_column(
            sa.Column("last_played_at", sa.DateTime(timezone=True), nullable=True),
        )
        batch_op.add_column(
            sa.Column("last_played_song_id", sa.String(length=36), nullable=True),
        )
        batch_op.create_foreign_key(
            LAST_PLAYED_SONG_FOREIGN_KEY,
            "songs",
            ["last_played_song_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(LAST_PLAYED_SONG_INDEX, ["last_played_song_id"])


def downgrade() -> None:
    with op.batch_alter_table("playlists") as batch_op:
        batch_op.drop_index(LAST_PLAYED_SONG_INDEX)
        batch_op.drop_constraint(LAST_PLAYED_SONG_FOREIGN_KEY, type_="foreignkey")
        batch_op.drop_column("last_played_song_id")
        batch_op.drop_column("last_played_at")
