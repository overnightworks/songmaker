"""add deleted_at soft-delete columns to albums and songs

Revision ID: d7e8f9a0b1c2
Revises: c1d2e3f4a5b6
Create Date: 2026-04-08 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "albums", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "songs", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    if op.get_bind().dialect.name == "sqlite":
        return
    op.execute(
        "CREATE INDEX ix_albums_deleted_at ON albums (deleted_at) "
        "WHERE deleted_at IS NOT NULL",
    )
    op.execute(
        "CREATE INDEX ix_songs_deleted_at ON songs (deleted_at) "
        "WHERE deleted_at IS NOT NULL",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        op.execute("DROP INDEX IF EXISTS ix_songs_deleted_at")
        op.execute("DROP INDEX IF EXISTS ix_albums_deleted_at")
    op.drop_column("songs", "deleted_at")
    op.drop_column("albums", "deleted_at")
