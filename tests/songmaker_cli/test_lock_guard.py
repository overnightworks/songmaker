"""A lock is refused while its transaction holds a write the lock's commit would persist."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from support.web_app import make_authenticated_user, make_fake_redis, seed_user

from songmaker_cli.api_helpers import (
    create_job_with_rate_limit,
    lock_lora_capacity,
    unique_album_id,
    unique_playlist_slug,
    unique_song_slug,
)
from songmaker_cli.auth_stores import DatabaseWriteLock
from songmaker_cli.constants import JobType
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, User

OWNER_ID = "owner"


def _hold_the_write_lock(session: Session) -> None:
    with DatabaseWriteLock(session).hold():
        pass


LOCK_OWNERS: dict[str, Callable[[Session], object]] = {
    "create_job_with_rate_limit": lambda session: create_job_with_rate_limit(
        session, make_authenticated_user(OWNER_ID), JobType.SCORE, redis=make_fake_redis(),
    ),
    "lock_lora_capacity": lock_lora_capacity,
    "unique_album_id": lambda session: unique_album_id(session, "Title"),
    "unique_song_slug": lambda session: unique_song_slug(session, "album", "Title"),
    "unique_playlist_slug": lambda session: unique_playlist_slug(session, "Title"),
    "DatabaseWriteLock": _hold_the_write_lock,
}


def _flush_a_business_row(session: Session) -> None:
    session.add(Album(id="flushed", title="Flushed", artist="X", created_by=OWNER_ID))
    session.flush()


def _run_a_raw_update(session: Session) -> None:
    session.execute(text("UPDATE users SET username = 'renamed'"))


EARLY_WRITES: dict[str, Callable[[Session], None]] = {
    "a flushed row": _flush_a_business_row,
    "a raw update": _run_a_raw_update,
}


def seed_committed_owner(session: Session) -> None:
    seed_user(session, "nina", user_id=OWNER_ID)
    session.commit()


def refused_and_left_nothing(session: Session) -> None:
    """The refusal committed nothing: after a rollback the seeded state is all that remains."""
    session.rollback()
    assert session.query(Album).count() == 0
    assert session.query(User).one().username == "nina"


@pytest.fixture
def session(tmp_path: Path):
    factory = init_test_db(tmp_path / "songmaker.db")
    with factory() as db:
        seed_committed_owner(db)
        yield db


@pytest.mark.parametrize("write", EARLY_WRITES.values(), ids=EARLY_WRITES.keys())
@pytest.mark.parametrize("take_lock", LOCK_OWNERS.values(), ids=LOCK_OWNERS.keys())
def test_a_lock_is_refused_after_a_write_in_the_open_transaction(
    session, take_lock, write,
) -> None:
    write(session)

    with pytest.raises(RuntimeError, match="uncommitted mutations"):
        take_lock(session)

    refused_and_left_nothing(session)


@pytest.mark.parametrize("take_lock", LOCK_OWNERS.values(), ids=LOCK_OWNERS.keys())
def test_a_clean_session_takes_the_lock(session, take_lock) -> None:
    take_lock(session)
