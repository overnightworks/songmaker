"""add user song work kind and album listen

``edit_kind`` names what kind of edit the person's latest one was;
``album_played_at`` is their latest listen outside a playlist. Existing rows
keep both NULL: what an earlier edit was, and whether an earlier listen was
inside a playlist, cannot be recovered honestly, so no backfill is attempted.

Revision ID: 5f4912bc4a31
Revises: e5a9c3d7b2f1
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5f4912bc4a31"
down_revision: str | Sequence[str] | None = "e5a9c3d7b2f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_song_work") as batch_op:
        batch_op.add_column(sa.Column("edit_kind", sa.String(length=16), nullable=True))
        batch_op.add_column(
            sa.Column("album_played_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("user_song_work") as batch_op:
        batch_op.drop_column("album_played_at")
        batch_op.drop_column("edit_kind")
