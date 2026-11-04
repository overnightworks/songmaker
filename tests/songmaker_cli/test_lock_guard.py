"""A lock is refused while its transaction holds a write the lock's commit would persist."""

from __future__ import annotations

from pathlib import Path

import pytest
from support.lock_owners import (
    EARLY_WRITES,
    LOCK_OWNERS,
    read_the_seeded_owner,
    refused_and_left_nothing,
    seed_committed_owner,
)

from songmaker_cli.db.engine import init_test_db


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
    read_the_seeded_owner(session)

    take_lock(session)
