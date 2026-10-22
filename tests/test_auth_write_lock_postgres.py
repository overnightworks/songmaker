"""The user-management write lock on PostgreSQL: one lock per transaction."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import pytest
from conftest import make_test_app, web_client
from fake_oidc_issuer import Person, a_fake_issuer
from httpx import Response
from oidc_world import World
from psycopg2.errors import LockNotAvailable
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from songmaker_cli.api_helpers import _USER_MANAGEMENT_LOCK_ID, _begin_exclusive
from songmaker_cli.auth_api import _backchannel_logout_host
from songmaker_cli.auth_stores import DatabaseWriteLock
from songmaker_cli.db.models import User, UserSession
from songmaker_cli.request_policies import BACKCHANNEL_LOGOUT_PATH

WAIT_SECONDS = 10


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


class _CallbackPause:
    """Holds the sign-in callback at its pending commit once its new session is flushed."""

    def __init__(self) -> None:
        self.reached = threading.Event()
        self.release = threading.Event()
        self.backend_pid: int | None = None

    def __call__(self, session: Session) -> None:
        rows = session.identity_map.values()
        if self.reached.is_set() or not any(isinstance(row, UserSession) for row in rows):
            return
        self.backend_pid = session.execute(text("SELECT pg_backend_pid()")).scalar_one()
        self.reached.set()
        if not self.release.wait(WAIT_SECONDS):
            raise RuntimeError("The paused sign-in callback was never released")


def _wait_until_the_logout_waits_behind(pg_factory, holder_pid: int) -> None:
    """Exactly one other backend awaits the write lock the paused callback holds."""
    lock_state = text("""
        SELECT coalesce(bool_or(granted AND pid = :holder), false),
               count(*) FILTER (WHERE NOT granted AND pid <> :holder)
        FROM pg_locks
        WHERE locktype = 'advisory' AND classid = 0 AND objid = :key AND objsubid = 1
          AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
    """).bindparams(holder=holder_pid, key=_USER_MANAGEMENT_LOCK_ID)
    deadline = time.monotonic() + WAIT_SECONDS
    with pg_factory() as observer:
        while time.monotonic() < deadline:
            held, waiting = observer.execute(lock_state).one()
            observer.rollback()
            if held and waiting == 1:
                return
            time.sleep(0.02)
    pytest.fail("The back-channel logout never waited on the lock the sign-in callback holds")


def _in_thread(answers: dict[str, Response | BaseException], name: str,
               call: Callable[[], Response]) -> threading.Thread:
    def run() -> None:
        try:
            answers[name] = call()
        except BaseException as failure:  # noqa: BLE001 - reported by the asserting thread
            answers[name] = failure

    return threading.Thread(target=run, name=name, daemon=True)


def test_a_back_channel_logout_waits_for_a_pending_sign_in_and_ends_its_new_session(
    pg_factory, tmp_path,
) -> None:
    """Cell 7: both real routes on PostgreSQL; the callback holds the lock through its commit."""
    subject = "6f1d2c3b-aaaa-4bbb-8ccc-0123456789ab"
    client, _ = make_test_app(tmp_path, factory=pg_factory)
    world = World(client, pg_factory, a_fake_issuer())
    client.app.state.oidc_sign_in = world.issuer.relying_party_for_app()
    started = world.start()
    realm = web_client(client.app, cookies={})
    answers: dict[str, Response | BaseException] = {}
    person = Person(subject, "felix")
    callback = _in_thread(answers, "callback", lambda: world.callback(person, started))
    logout = _in_thread(answers, "logout", lambda: realm.post(
        BACKCHANNEL_LOGOUT_PATH, data={"logout_token": world.issuer.logout_token(subject)},
        headers={"host": _backchannel_logout_host()},
    ))
    pause = _CallbackPause()
    event.listen(pg_factory, "before_commit", pause)
    try:
        callback.start()
        assert pause.reached.wait(WAIT_SECONDS), "The sign-in callback never reached its commit"
        logout.start()
        _wait_until_the_logout_waits_behind(pg_factory, pause.backend_pid)
        assert "logout" not in answers
    finally:
        pause.release.set()
        for thread in (callback, logout):
            if thread.ident is not None:
                thread.join(WAIT_SECONDS)
        event.remove(pg_factory, "before_commit", pause)
    assert not callback.is_alive() and not logout.is_alive(), "A route never answered"

    assert answers["callback"].status_code == 303
    assert answers["logout"].status_code == 200
    with pg_factory() as session:
        assert session.get(User, subject) is not None
        assert session.query(UserSession).filter_by(user_id=subject).count() == 0
