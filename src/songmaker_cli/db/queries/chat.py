"""Song-scoped chat message query helpers.

New code should prefer the conversation-scoped queries in
``db/queries/conversations.py``. These song-scoped helpers are kept
for the legacy per-song chat UI which will be replaced in the
co-writer redesign.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from songmaker_cli.db.models import ChatMessage, Song


def list_chat_messages(session: Session, song_id: str) -> list[ChatMessage]:
    return (
        session.query(ChatMessage)
        .filter(ChatMessage.song_id == song_id)
        .order_by(ChatMessage.created_at)
        .all()
    )


def create_chat_message(
    session: Session,
    song_id: str,
    role: str,
    content: str,
    conversation_id: str | None = None,
) -> ChatMessage:
    msg = ChatMessage(
        song_id=song_id, role=role, content=content,
        conversation_id=conversation_id,
    )
    session.add(msg)
    session.flush()
    return msg


def delete_chat_messages(session: Session, song_id: str) -> int:
    count = (
        session.query(ChatMessage)
        .filter(ChatMessage.song_id == song_id)
        .delete()
    )
    session.flush()
    return count


def count_chat_messages(session: Session, song_id: str) -> int:
    return (
        session.query(ChatMessage)
        .filter(ChatMessage.song_id == song_id)
        .count()
    )


def songs_with_chat(
    session: Session, user_id: str, limit: int = 20,
) -> list[dict]:
    rows = (
        session.query(
            Song.id,
            Song.title,
            func.count(ChatMessage.id).label("message_count"),
            func.max(ChatMessage.created_at).label("last_message_at"),
        )
        .join(ChatMessage, ChatMessage.song_id == Song.id)
        .join(Song.album)
        .filter(Song.album.has(created_by=user_id))
        .group_by(Song.id, Song.title)
        .order_by(func.max(ChatMessage.created_at).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "song_id": r.id,
            "title": r.title,
            "message_count": r.message_count,
            "last_message_at": r.last_message_at.isoformat() if r.last_message_at else None,
        }
        for r in rows
    ]
