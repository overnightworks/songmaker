"""The user-management write lock on PostgreSQL: one lock per transaction."""

from __future__ import annotations

import threading
from contextlib import contextmanager

import pytest

from songmaker_cli.api_helpers import _USER_MANAGEMENT_LOCK_ID, _begin_exclusive
from songmaker_cli.auth_stores import DatabaseWriteLock

_WRITER_WAIT_SECONDS = 1.0
_WRITER_JOIN_SECONDS = 10.0


@contextmanager
def _concurrent_writer(pg_factory):
    """A second connection that asks for the lock; `acquired` is set once it has it."""
    acquired = threading.Event()

    def _write() -> None:
        with pg_factory() as session:
            _begin_exclusive(session, _USER_MANAGEMENT_LOCK_ID)
            acquired.set()
            session.rollback()

    writer = threading.Thread(target=_write)
    writer.start()
    try:
        yield acquired
    finally:
        writer.join(timeout=_WRITER_JOIN_SECONDS)
    assert not writer.is_alive()


@pytest.mark.parametrize("nesting", ["nested", "sequential"])
def test_a_concurrent_writer_blocks_until_the_outer_commit(pg_factory, nesting: str) -> None:
    with pg_factory() as session:
        lock = DatabaseWriteLock(session)
        with lock.hold():
            if nesting == "nested":
                with _concurrent_writer(pg_factory) as acquired, lock.hold():
                    assert not acquired.wait(_WRITER_WAIT_SECONDS)
                    session.commit()
                return
        with _concurrent_writer(pg_factory) as acquired:
            with lock.hold():
                assert not acquired.wait(_WRITER_WAIT_SECONDS)
            session.commit()
