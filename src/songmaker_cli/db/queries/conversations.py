"""Query functions for conversations and their summaries."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from songmaker_cli.db.models import (
    ChatMessage,
    Conversation,
    ConversationSummary,
)


def get_conversation(
    session: Session, conversation_id: str,
) -> Conversation | None:
    return (
        session.query(Conversation)
        .options(joinedload(Conversation.summary))
        .filter_by(id=conversation_id)
        .first()
    )


def get_active_conversation(
    session: Session, user_id: str,
) -> Conversation | None:
    return (
        session.query(Conversation)
        .filter(
            Conversation.user_id == user_id,
            Conversation.archived_at.is_(None),
        )
        .order_by(Conversation.created_at.desc())
        .first()
    )


def list_conversations(
    session: Session, user_id: str, include_archived: bool = True,
) -> list[Conversation]:
    query = session.query(Conversation).filter(Conversation.user_id == user_id)
    if not include_archived:
        query = query.filter(Conversation.archived_at.is_(None))
    return query.order_by(Conversation.updated_at.desc()).all()


def create_conversation(
    session: Session, user_id: str, title: str | None = None,
) -> Conversation:
    conversation = Conversation(user_id=user_id, title=title)
    session.add(conversation)
    session.flush()
    return conversation


def get_or_create_active_conversation(
    session: Session, user_id: str,
) -> Conversation:
    """Return the user's active conversation, creating one if none exists."""
    active = get_active_conversation(session, user_id)
    if active is not None:
        return active
    return create_conversation(session, user_id)


def archive_conversation(
    session: Session, conversation_id: str,
) -> Conversation:
    conversation = (
        session.query(Conversation).filter_by(id=conversation_id).first()
    )
    if conversation is None:
        raise ValueError(f"Conversation not found: {conversation_id}")
    if conversation.archived_at is None:
        conversation.archived_at = datetime.now(timezone.utc)
        session.flush()
    return conversation


def delete_conversation(session: Session, conversation_id: str) -> None:
    deleted = (
        session.query(Conversation)
        .filter_by(id=conversation_id)
        .delete()
    )
    if not deleted:
        raise ValueError(f"Conversation not found: {conversation_id}")
    session.flush()


def count_messages(session: Session, conversation_id: str) -> int:
    return (
        session.query(ChatMessage)
        .filter(ChatMessage.conversation_id == conversation_id)
        .count()
    )


def list_messages(
    session: Session, conversation_id: str,
) -> list[ChatMessage]:
    return (
        session.query(ChatMessage)
        .filter(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at)
        .all()
    )


def append_message(
    session: Session,
    conversation_id: str,
    role: str,
    content: str,
    song_id: str | None = None,
) -> ChatMessage:
    msg = ChatMessage(
        conversation_id=conversation_id,
        song_id=song_id,
        role=role,
        content=content,
    )
    session.add(msg)
    # Touch the conversation so list ordering reflects the new activity.
    session.query(Conversation).filter_by(id=conversation_id).update(
        {"updated_at": datetime.now(timezone.utc)},
    )
    session.flush()
    return msg


def upsert_summary(
    session: Session,
    conversation_id: str,
    summary_text: str,
    last_summarized_message_id: str | None,
    message_count: int,
    token_count: int,
) -> ConversationSummary:
    existing = (
        session.query(ConversationSummary)
        .filter_by(conversation_id=conversation_id)
        .first()
    )
    if existing is None:
        existing = ConversationSummary(
            conversation_id=conversation_id,
            summary_text=summary_text,
            last_summarized_message_id=last_summarized_message_id,
            message_count=message_count,
            token_count=token_count,
        )
        session.add(existing)
    else:
        existing.summary_text = summary_text
        existing.last_summarized_message_id = last_summarized_message_id
        existing.message_count = message_count
        existing.token_count = token_count
    session.flush()
    return existing


def messages_since(
    session: Session,
    conversation_id: str,
    since_message_id: str | None,
) -> list[ChatMessage]:
    """Return messages created strictly after the given boundary message.

    ``since_message_id`` is an exclusive lower bound — useful for fetching
    everything that came after the last summarized message. If it is None
    or points to a deleted row, the full conversation is returned.
    """
    query = (
        session.query(ChatMessage)
        .filter(ChatMessage.conversation_id == conversation_id)
    )
    if since_message_id is not None:
        boundary = (
            session.query(ChatMessage.created_at)
            .filter_by(id=since_message_id)
            .scalar()
        )
        if boundary is not None:
            query = query.filter(ChatMessage.created_at > boundary)
    return query.order_by(ChatMessage.created_at).all()


def recent_conversations(
    session: Session, user_id: str, limit: int = 20,
) -> list[dict]:
    rows = (
        session.query(
            Conversation.id,
            Conversation.title,
            Conversation.created_at,
            Conversation.updated_at,
            Conversation.archived_at,
            func.count(ChatMessage.id).label("message_count"),
            func.max(ChatMessage.created_at).label("last_message_at"),
        )
        .outerjoin(ChatMessage, ChatMessage.conversation_id == Conversation.id)
        .filter(Conversation.user_id == user_id)
        .group_by(
            Conversation.id, Conversation.title,
            Conversation.created_at, Conversation.updated_at,
            Conversation.archived_at,
        )
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "title": r.title,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
            "archived_at": r.archived_at,
            "message_count": r.message_count,
            "last_message_at": r.last_message_at,
        }
        for r in rows
    ]
