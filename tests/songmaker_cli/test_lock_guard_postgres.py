"""The lock guard on PostgreSQL asks the database whether the transaction wrote."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_lock_guard import (
    EARLY_WRITES,
    LOCK_OWNERS,
    OWNER_ID,
    refused_and_left_nothing,
    seed_committed_owner,
)


@pytest.fixture
def session(pg_factory):
    with pg_factory() as db:
        seed_committed_owner(db)
        yield db


def _lock_a_row_for_update(session: Session) -> None:
    session.execute(text("SELECT id FROM users WHERE id = :id FOR UPDATE"), {"id": OWNER_ID})


POSTGRES_WRITES = {**EARLY_WRITES, "a row lock": _lock_a_row_for_update}


@pytest.mark.parametrize("write", POSTGRES_WRITES.values(), ids=POSTGRES_WRITES.keys())
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
