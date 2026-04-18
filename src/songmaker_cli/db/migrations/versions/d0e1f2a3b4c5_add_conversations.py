"""Add conversations + conversation_summaries tables; link chat_messages

Introduces the user-scoped conversation model. Existing chat messages
are grouped per album into archived conversations so no history is
lost. ``chat_messages.song_id`` becomes nullable so future messages
that have no "current song" context can still be stored.

Revision ID: d0e1f2a3b4c5
Revises: c5d6e7f8a9b0
Create Date: 2026-04-18 12:00:00.000000
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_conversations_user_id"), "conversations", ["user_id"],
        unique=False,
    )

    op.create_table(
        "conversation_summaries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column(
            "last_summarized_message_id", sa.String(length=36), nullable=True,
        ),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["last_summarized_message_id"], ["chat_messages.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id"),
    )
    op.create_index(
        op.f("ix_conversation_summaries_conversation_id"),
        "conversation_summaries", ["conversation_id"], unique=False,
    )

    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.add_column(
            sa.Column("conversation_id", sa.String(length=36), nullable=True),
        )
        batch_op.create_index(
            batch_op.f("ix_chat_messages_conversation_id"),
            ["conversation_id"], unique=False,
        )
        batch_op.create_foreign_key(
            "fk_chat_messages_conversation_id", "conversations",
            ["conversation_id"], ["id"], ondelete="CASCADE",
        )
        batch_op.alter_column(
            "song_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )

    backfill_conversations(op.get_bind())


def backfill_conversations(bind) -> None:
    """Group existing chat_messages into per-album archived conversations.

    Exposed at module scope so it can be exercised by tests against a
    SQLite connection without a live Alembic context.
    """
    rows = bind.execute(sa.text(
        "SELECT albums.id AS album_id, albums.title AS album_title, "
        "albums.created_by AS user_id, "
        "MIN(chat_messages.created_at) AS first_at, "
        "MAX(chat_messages.created_at) AS last_at "
        "FROM albums "
        "JOIN songs ON songs.album_id = albums.id "
        "JOIN chat_messages ON chat_messages.song_id = songs.id "
        "WHERE albums.created_by IS NOT NULL "
        "AND chat_messages.conversation_id IS NULL "
        "GROUP BY albums.id, albums.title, albums.created_by"
    )).fetchall()

    now = datetime.now(timezone.utc)
    for row in rows:
        conv_id = str(uuid.uuid4())
        bind.execute(sa.text(
            "INSERT INTO conversations "
            "(id, user_id, title, created_at, updated_at, archived_at) "
            "VALUES (:id, :user_id, :title, :created_at, :updated_at, :archived_at)"
        ), {
            "id": conv_id,
            "user_id": row.user_id,
            "title": f"Legacy: {row.album_title}",
            "created_at": row.first_at,
            "updated_at": row.last_at,
            "archived_at": now,
        })
        bind.execute(sa.text(
            "UPDATE chat_messages SET conversation_id = :conv_id "
            "WHERE conversation_id IS NULL "
            "AND song_id IN (SELECT id FROM songs WHERE album_id = :album_id)"
        ), {"conv_id": conv_id, "album_id": row.album_id})


def downgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.alter_column(
            "song_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
        batch_op.drop_constraint(
            "fk_chat_messages_conversation_id", type_="foreignkey",
        )
        batch_op.drop_index(batch_op.f("ix_chat_messages_conversation_id"))
        batch_op.drop_column("conversation_id")
    op.drop_index(
        op.f("ix_conversation_summaries_conversation_id"),
        table_name="conversation_summaries",
    )
    op.drop_table("conversation_summaries")
    op.drop_index(op.f("ix_conversations_user_id"), table_name="conversations")
    op.drop_table("conversations")
