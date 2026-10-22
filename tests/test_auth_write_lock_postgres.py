"""The user-management write lock on PostgreSQL: one lock per transaction."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import pytest
from conftest import seed_user
from fake_oidc_issuer import a_fake_issuer
from psycopg2.errors import LockNotAvailable
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from songmaker_cli.api_helpers import _USER_MANAGEMENT_LOCK_ID, _begin_exclusive
from songmaker_cli.auth_api import _end_subject_sessions
from songmaker_cli.auth_stores import DatabaseWriteLock
from songmaker_cli.db.models import UserSession


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


def _wait_until_an_advisory_lock_is_awaited(pg_factory) -> None:
    deadline = time.monotonic() + 10
    with pg_factory() as observer:
        while time.monotonic() < deadline:
            awaited = observer.execute(
                text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"),
            ).scalar_one()
            observer.rollback()
            if awaited:
                return
            time.sleep(0.02)
    pytest.fail("The back-channel logout never waited on the write lock")


def test_a_back_channel_logout_waits_for_the_write_lock_and_ends_the_session_it_guarded(
    pg_factory,
) -> None:
    subject = "6f1d2c3b-aaaa-4bbb-8ccc-0123456789ab"
    issuer = a_fake_issuer()
    form_body = urlencode({"logout_token": issuer.logout_token(subject)}).encode()
    with pg_factory() as seeding:
        seed_user(seeding, "felix", user_id=subject)
        seeding.commit()
    answers: list[bool] = []
    logout = threading.Thread(
        target=lambda: answers.append(
            _end_subject_sessions(
                issuer.relying_party_for_app(), pg_factory, form_body,
                "application/x-www-form-urlencoded",
            ),
        ),
    )

    with pg_factory() as callback_transaction:
        with DatabaseWriteLock(callback_transaction).hold():
            callback_transaction.add(UserSession(
                id="new-session", user_id=subject,
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            ))
            callback_transaction.flush()
            logout.start()
            _wait_until_an_advisory_lock_is_awaited(pg_factory)
            callback_transaction.commit()
        logout.join(timeout=10)

    assert answers == [True]
    with pg_factory() as session:
        assert session.query(UserSession).filter_by(user_id=subject).count() == 0
