"""Add the legacy per-user resource event outbox.

Revision ID: 40a1c2d3e4f5
Revises: 202b0514cdde
Create Date: 2026-08-21 00:00:00.000000

This revision was briefly deployed before its application code was reverted.
It remains in the chain so databases stamped at this revision can migrate
forward.  The following revision replaces these tables with the reviewed
ledger schema while preserving any rows written during that deployment.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "40a1c2d3e4f5"
down_revision: Union[str, Sequence[str], None] = "202b0514cdde"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_resource_cursors",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("high_water_mark", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
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


def downgrade() -> None:
    op.drop_index("ix_user_resource_events_created_at", table_name="user_resource_events")
    op.drop_index("ix_user_resource_events_user_id", table_name="user_resource_events")
    op.drop_table("user_resource_events")
    op.drop_table("user_resource_cursors")
