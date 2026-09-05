"""add resource event ledger

Revision ID: f4a5b6c7d8e9
Revises: 40a1c2d3e4f5
Create Date: 2026-08-21
"""

from collections.abc import Sequence
from typing import Final

import sqlalchemy as sa
from alembic import op

revision: str = "f4a5b6c7d8e9"
down_revision: str | Sequence[str] | None = "40a1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USERS_ID: Final = "users.id"


def upgrade() -> None:
    op.create_table(
        "resource_event_cursors",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "high_water_mark",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.ForeignKeyConstraint(["user_id"], [USERS_ID], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.execute(
        "INSERT INTO resource_event_cursors (user_id, high_water_mark) "
        "SELECT users.id, COALESCE(user_resource_cursors.high_water_mark, 0) "
        "FROM users LEFT JOIN user_resource_cursors "
        "ON user_resource_cursors.user_id = users.id",
    )
    op.create_table(
        "resource_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("resource_type", sa.String(length=30), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("generation_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], [USERS_ID], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "kind",
            "generation_id",
            name="uq_resource_event_kind_generation",
        ),
        sa.UniqueConstraint(
            "user_id",
            "sequence",
            name="uq_resource_event_user_sequence",
        ),
    )
    op.create_index(
        "ix_resource_events_created_at",
        "resource_events",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_resource_events_resource_id",
        "resource_events",
        ["resource_id"],
        unique=False,
    )
    op.execute(
        "INSERT INTO resource_events "
        "(id, user_id, sequence, kind, resource_type, resource_id, "
        "generation_id, created_at) "
        "SELECT id, user_id, sequence, kind, 'song', song_id, "
        "generation_id, created_at FROM user_resource_events",
    )
    op.drop_index(
        "ix_user_resource_events_created_at",
        table_name="user_resource_events",
    )
    op.drop_index("ix_user_resource_events_user_id", table_name="user_resource_events")
    op.drop_table("user_resource_events")
    op.drop_table("user_resource_cursors")


def downgrade() -> None:
    op.create_table(
        "user_resource_cursors",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("high_water_mark", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], [USERS_ID], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "user_resource_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("song_id", sa.String(length=36), nullable=False),
        sa.Column("generation_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], [USERS_ID], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "sequence", name="uq_user_resource_event_seq"),
        sa.UniqueConstraint("generation_id", name="uq_user_resource_event_generation"),
    )
    op.create_index(
        "ix_user_resource_events_user_id",
        "user_resource_events",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_resource_events_created_at",
        "user_resource_events",
        ["created_at"],
        unique=False,
    )
    op.execute(
        "INSERT INTO user_resource_cursors (user_id, high_water_mark) "
        "SELECT user_id, high_water_mark FROM resource_event_cursors",
    )
    op.execute(
        "INSERT INTO user_resource_events "
        "(id, user_id, sequence, kind, song_id, generation_id, created_at) "
        "SELECT id, user_id, sequence, kind, resource_id, generation_id, created_at "
        "FROM resource_events",
    )
    op.drop_index("ix_resource_events_resource_id", table_name="resource_events")
    op.drop_index("ix_resource_events_created_at", table_name="resource_events")
    op.drop_table("resource_events")
    op.drop_table("resource_event_cursors")
