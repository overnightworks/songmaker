"""Tests for the durable per-user resource event ledger."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from songmaker_cli.app_context import AppContext
from songmaker_cli.constants import ResourceEventKind, ResourceType
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import (
    Album,
    Generation,
    ResourceEvent,
    ResourceEventCursor,
    Song,
    User,
)
from songmaker_cli.db.queries import (
    create_generation_created_event,
    create_user,
    delete_resource_events_before,
    get_oldest_resource_event_sequence,
    get_resource_event_high_water_mark,
    list_resource_events_after,
)
from songmaker_cli.lifecycle import (
    BackgroundLoopRegistry,
    cleanup_expired_resource_events,
    resource_event_cleanup_loop,
)


@pytest.fixture()
def db_factory(tmp_path: Path):
    return init_test_db(tmp_path / "resource-events.db")


def _add_user(session: Session, user_id: str, username: str) -> None:
    session.add(User(id=user_id, username=username, password_hash="hash", role="user"))
    session.flush()


def _add_generation(session: Session, generation_id: str, user_id: str) -> None:
    album_id = f"album-{generation_id}"
    song_id = f"song-{generation_id}"
    session.add(Album(
        id=album_id, title="Album", artist="Artist", created_by=user_id,
    ))
    session.flush()
    session.add(Song(id=song_id, title="Song", album_id=album_id))
    session.flush()
    session.add(Generation(
        id=generation_id,
        song_id=song_id,
        generation_number=1,
        mp3_path=f"{user_id}/{generation_id}.mp3",
    ))
    session.flush()


def test_create_user_creates_cursor_in_same_transaction(db_factory) -> None:
    with db_factory() as session:
        user = create_user(session, "alice", "hash")
        cursor = session.get(ResourceEventCursor, user.id)
        assert cursor is not None
        assert cursor.high_water_mark == 0
        session.rollback()

    with db_factory() as session:
        assert session.query(User).count() == 0
        assert session.query(ResourceEventCursor).count() == 0


def test_event_sequences_are_ordered_and_user_scoped(db_factory) -> None:
    with db_factory() as session:
        _add_user(session, "u1", "alice")
        _add_user(session, "u2", "bob")
        first = create_generation_created_event(
            session, user_id="u1", song_id="song-1", generation_id="gen-1",
        )
        second = create_generation_created_event(
            session, user_id="u1", song_id="song-2", generation_id="gen-2",
        )
        other = create_generation_created_event(
            session, user_id="u2", song_id="song-3", generation_id="gen-3",
        )
        session.commit()
        assert (first.sequence, second.sequence, other.sequence) == (1, 2, 1)
        assert first.kind == ResourceEventKind.GENERATION_CREATED
        assert first.resource_type == ResourceType.SONG
    with db_factory() as session:
        assert [event.sequence for event in list_resource_events_after(session, "u1", 0)] == [1, 2]
        assert [event.generation_id for event in list_resource_events_after(
            session, "u1", 1, through=2,
        )] == ["gen-2"]
        assert [event.sequence for event in list_resource_events_after(session, "u2", 0)] == [1]


def test_event_failure_rolls_back_generation_and_sequence(db_factory) -> None:
    with db_factory() as session:
        _add_user(session, "u1", "alice")
        create_generation_created_event(
            session, user_id="u1", song_id="existing-song", generation_id="duplicate",
        )
        session.commit()

    with db_factory() as session:
        _add_generation(session, "new-generation", "u1")
        with pytest.raises(IntegrityError):
            create_generation_created_event(
                session,
                user_id="u1",
                song_id="song-new-generation",
                generation_id="duplicate",
            )
        session.rollback()

    with db_factory() as session:
        assert session.get(Generation, "new-generation") is None
        assert get_resource_event_high_water_mark(session, "u1") == 1
        assert [event.sequence for event in list_resource_events_after(session, "u1", 0)] == [1]


def test_retention_preserves_cursor_and_exposes_oldest_sequence(db_factory) -> None:
    now = datetime.now(timezone.utc)
    with db_factory() as session:
        _add_user(session, "u1", "alice")
        events = [
            create_generation_created_event(
                session,
                user_id="u1",
                song_id=f"song-{number}",
                generation_id=f"gen-{number}",
            )
            for number in range(1, 4)
        ]
        events[0].created_at = now - timedelta(days=31)
        events[1].created_at = now - timedelta(days=30, seconds=1)
        session.commit()

    with db_factory() as session:
        assert delete_resource_events_before(session, now - timedelta(days=30)) == 2
        session.commit()
        assert get_resource_event_high_water_mark(session, "u1") == 3
        assert get_oldest_resource_event_sequence(session, "u1") == 3


def test_deleting_user_cascades_cursor_and_events(db_factory) -> None:
    with db_factory() as session:
        _add_user(session, "u1", "alice")
        create_generation_created_event(
            session, user_id="u1", song_id="song-1", generation_id="gen-1",
        )
        session.commit()

    with db_factory() as session:
        session.delete(session.get(User, "u1"))
        session.commit()
        assert session.query(ResourceEventCursor).count() == 0
        assert session.query(ResourceEvent).count() == 0


def test_lifecycle_cleanup_enforces_retention(db_factory, tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    with db_factory() as session:
        _add_user(session, "u1", "alice")
        event = create_generation_created_event(
            session, user_id="u1", song_id="song-1", generation_id="gen-1",
        )
        event.created_at = now - timedelta(days=31)
        session.commit()

    ctx = AppContext(
        db=db_factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=b"a" * 64,
        redis=MagicMock(),
    )
    assert cleanup_expired_resource_events(ctx) == 1
    with db_factory() as session:
        assert session.query(ResourceEvent).count() == 0
        assert get_resource_event_high_water_mark(session, "u1") == 1


def test_resource_event_cleanup_loop_runs_named_cleanup() -> None:
    app = SimpleNamespace(
        state=SimpleNamespace(
            ctx=MagicMock(),
            background_loop_registry=BackgroundLoopRegistry(),
        ),
    )

    async def _run() -> None:
        with (
            patch(
                "songmaker_cli.lifecycle.asyncio.sleep",
                new=AsyncMock(side_effect=[None, asyncio.CancelledError]),
            ),
            patch("songmaker_cli.lifecycle.cleanup_expired_resource_events") as cleanup,
        ):
            with pytest.raises(asyncio.CancelledError):
                await resource_event_cleanup_loop(app)
            cleanup.assert_called_once_with(app.state.ctx)

    asyncio.run(_run())
