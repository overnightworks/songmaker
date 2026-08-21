"""Per-user durable resource-event outbox."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from songmaker_cli.constants import (
    RESOURCE_CURSOR_LOCK_FAILED,
    RESOURCE_EVENT_CURSOR_LOCK_ATTEMPTS,
    RESOURCE_EVENT_GENERATION_ID_REQUIRED,
    RESOURCE_EVENT_KIND_GENERATION_CREATED,
    RESOURCE_EVENT_RETENTION_DAYS,
    RESOURCE_EVENT_SONG_ID_REQUIRED,
    RESOURCE_EVENT_USER_ID_REQUIRED,
)
from songmaker_cli.db.models import UserResourceCursor, UserResourceEvent


def lock_user_resource_cursor(session: Session, user_id: str) -> UserResourceCursor:
    for _ in range(RESOURCE_EVENT_CURSOR_LOCK_ATTEMPTS):
        cursor = (
            session.query(UserResourceCursor)
            .filter_by(user_id=user_id)
            .with_for_update()
            .first()
        )
        if cursor is not None:
            return cursor
        try:
            with session.begin_nested():
                session.add(UserResourceCursor(user_id=user_id, high_water_mark=0))
                session.flush()
        except IntegrityError:
            continue
        locked = (
            session.query(UserResourceCursor)
            .filter_by(user_id=user_id)
            .with_for_update()
            .first()
        )
        if locked is not None:
            return locked
    raise RuntimeError(RESOURCE_CURSOR_LOCK_FAILED)


def record_generation_created(
    session: Session,
    *,
    user_id: str,
    song_id: str,
    generation_id: str,
) -> UserResourceEvent:
    if not user_id:
        raise ValueError(RESOURCE_EVENT_USER_ID_REQUIRED)
    if not song_id:
        raise ValueError(RESOURCE_EVENT_SONG_ID_REQUIRED)
    if not generation_id:
        raise ValueError(RESOURCE_EVENT_GENERATION_ID_REQUIRED)

    lock_user_resource_cursor(session, user_id)
    for _ in range(RESOURCE_EVENT_CURSOR_LOCK_ATTEMPTS):
        try:
            with session.begin_nested():
                cursor = (
                    session.query(UserResourceCursor)
                    .filter_by(user_id=user_id)
                    .with_for_update()
                    .one()
                )
                sequence = cursor.high_water_mark + 1
                cursor.high_water_mark = sequence
                event = UserResourceEvent(
                    user_id=user_id,
                    sequence=sequence,
                    kind=RESOURCE_EVENT_KIND_GENERATION_CREATED,
                    song_id=song_id,
                    generation_id=generation_id,
                )
                session.add(event)
                session.flush()
                return event
        except IntegrityError:
            continue
    raise RuntimeError(RESOURCE_CURSOR_LOCK_FAILED)


def get_user_high_water_mark(session: Session, user_id: str) -> int:
    cursor = session.query(UserResourceCursor).filter_by(user_id=user_id).first()
    if cursor is None:
        return 0
    return cursor.high_water_mark


def get_oldest_retained_sequence(session: Session, user_id: str) -> int | None:
    oldest = (
        session.query(UserResourceEvent.sequence)
        .filter_by(user_id=user_id)
        .order_by(UserResourceEvent.sequence.asc())
        .first()
    )
    if oldest is None:
        return None
    return oldest[0]


def list_user_events_after(
    session: Session, user_id: str, after_sequence: int,
) -> list[UserResourceEvent]:
    return (
        session.query(UserResourceEvent)
        .filter(
            UserResourceEvent.user_id == user_id,
            UserResourceEvent.sequence > after_sequence,
        )
        .order_by(UserResourceEvent.sequence.asc())
        .all()
    )


def has_retention_gap(
    last_event_id: int, oldest: int | None, high_water_mark: int,
) -> bool:
    if last_event_id >= high_water_mark:
        return False
    if oldest is None:
        return True
    return last_event_id + 1 < oldest


def purge_expired_resource_events(
    session: Session, *, now: datetime | None = None,
) -> int:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(
        days=RESOURCE_EVENT_RETENTION_DAYS,
    )
    deleted = (
        session.query(UserResourceEvent)
        .filter(UserResourceEvent.created_at < cutoff)
        .delete(synchronize_session=False)
    )
    return deleted
