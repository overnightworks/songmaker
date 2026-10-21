"""The user-management write lock on PostgreSQL: one lock per transaction."""

from __future__ import annotations

import pytest
from psycopg2.errors import LockNotAvailable
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from songmaker_cli.api_helpers import _USER_MANAGEMENT_LOCK_ID, _begin_exclusive
from songmaker_cli.auth_stores import DatabaseWriteLock


def _second_session_times_out_on_the_lock(pg_factory) -> None:
    with pg_factory() as other:
        other.execute(text("SET LOCAL lock_timeout = '200ms'"))
        with pytest.raises(OperationalError) as refused:
            _begin_exclusive(other, _USER_MANAGEMENT_LOCK_ID)
    assert isinstance(refused.value.orig, LockNotAvailable)


def _second_session_gets_the_lock(pg_factory) -> None:
    with pg_factory() as other:
        other.execute(text("SET LOCAL lock_timeout = '2s'"))
        _begin_exclusive(other, _USER_MANAGEMENT_LOCK_ID)
        other.rollback()


def _transaction_id(session) -> int:
    return session.execute(text("SELECT pg_current_xact_id()")).scalar_one()


def test_a_nested_hold_keeps_the_lock_until_the_outer_commit(pg_factory) -> None:
    with pg_factory() as session:
        lock = DatabaseWriteLock(session)
        with lock.hold():
            outer_transaction = _transaction_id(session)
            with lock.hold():
                assert _transaction_id(session) == outer_transaction
                _second_session_times_out_on_the_lock(pg_factory)
            _second_session_times_out_on_the_lock(pg_factory)
            session.commit()
    _second_session_gets_the_lock(pg_factory)


def test_a_sequential_hold_keeps_the_lock_until_the_outer_commit(pg_factory) -> None:
    with pg_factory() as session:
        lock = DatabaseWriteLock(session)
        with lock.hold():
            first_transaction = _transaction_id(session)
            _second_session_times_out_on_the_lock(pg_factory)
        with lock.hold():
            assert _transaction_id(session) == first_transaction
            _second_session_times_out_on_the_lock(pg_factory)
        session.commit()
    _second_session_gets_the_lock(pg_factory)
