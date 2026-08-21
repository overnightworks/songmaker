"""Durable, user-scoped resource event ledger queries."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from songmaker_cli.constants import ResourceEventKind, ResourceType
from songmaker_cli.db.models import ResourceEvent, ResourceEventCursor


def ensure_resource_event_cursor(session: Session, user_id: str) -> None:
    """Create a missing cursor without racing another first event."""
    session.execute(
        text(
            "INSERT INTO resource_event_cursors (user_id, high_water_mark) "
            "VALUES (:user_id, 0) ON CONFLICT (user_id) DO NOTHING",
        ),
        {"user_id": user_id},
    )


def create_generation_created_event(
    session: Session,
    *,
    user_id: str,
    song_id: str,
    generation_id: str,
) -> ResourceEvent:
    """Allocate and persist one ``generation.created`` event transactionally."""
    ensure_resource_event_cursor(session, user_id)
    sequence = session.execute(
        update(ResourceEventCursor)
        .where(ResourceEventCursor.user_id == user_id)
        .values(high_water_mark=ResourceEventCursor.high_water_mark + 1)
        .returning(ResourceEventCursor.high_water_mark),
    ).scalar_one()
    event = ResourceEvent(
        user_id=user_id,
        sequence=sequence,
        kind=ResourceEventKind.GENERATION_CREATED,
        resource_type=ResourceType.SONG,
        resource_id=song_id,
        generation_id=generation_id,
    )
    session.add(event)
    session.flush()
    return event


def get_resource_event_high_water_mark(session: Session, user_id: str) -> int:
    value = session.scalar(
        select(ResourceEventCursor.high_water_mark).where(
            ResourceEventCursor.user_id == user_id,
        ),
    )
    return value or 0


def get_oldest_resource_event_sequence(session: Session, user_id: str) -> int | None:
    return session.scalar(
        select(func.min(ResourceEvent.sequence)).where(ResourceEvent.user_id == user_id),
    )


def list_resource_events_after(
    session: Session,
    user_id: str,
    sequence: int,
    *,
    through: int | None = None,
) -> list[ResourceEvent]:
    statement = select(ResourceEvent).where(
        ResourceEvent.user_id == user_id,
        ResourceEvent.sequence > sequence,
    )
    if through is not None:
        statement = statement.where(ResourceEvent.sequence <= through)
    return list(session.scalars(statement.order_by(ResourceEvent.sequence)))


def delete_resource_events_before(session: Session, cutoff: datetime) -> int:
    result = session.execute(
        delete(ResourceEvent).where(ResourceEvent.created_at < cutoff),
    )
    session.flush()
    return result.rowcount or 0
