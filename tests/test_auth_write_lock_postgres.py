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
from songmaker_cli.auth_api import backchannel_logout_host
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
    """Holds the sign-in callback at its pending commit once its new session is flushed,
    and names the backend that asks for the write lock while the callback waits there."""

    def __init__(self) -> None:
        self.reached = threading.Event()
        self.release = threading.Event()
        self.backend_pid: int | None = None
        self.logout_pid: int | None = None

    def note_lock_request(self, connection, _cursor, statement: str, *_execution) -> None:
        asks_for_the_lock = "pg_advisory_xact_lock" in statement
        if self.reached.is_set() and self.logout_pid is None and asks_for_the_lock:
            self.logout_pid = connection.connection.dbapi_connection.info.backend_pid

    def __call__(self, session: Session) -> None:
        rows = session.identity_map.values()
        if self.reached.is_set() or not any(isinstance(row, UserSession) for row in rows):
            return
        self.backend_pid = session.execute(text("SELECT pg_backend_pid()")).scalar_one()
        self.reached.set()
        if not self.release.wait(WAIT_SECONDS):
            raise RuntimeError("The paused sign-in callback was never released")


def _wait_until_the_logout_waits_behind(pg_factory, pause: _CallbackPause) -> None:
    """The logout's own backend awaits the write lock the paused callback's backend holds."""
    lock_state = text("""
        SELECT coalesce(bool_or(granted AND pid = :holder), false),
               coalesce(bool_or(NOT granted AND pid = :waiter), false)
        FROM pg_locks
        WHERE locktype = 'advisory' AND classid = 0 AND objid = :key AND objsubid = 1
          AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
    """)
    deadline = time.monotonic() + WAIT_SECONDS
    with pg_factory() as observer:
        while time.monotonic() < deadline:
            if pause.logout_pid is not None and pause.logout_pid != pause.backend_pid:
                held, awaited = observer.execute(lock_state.bindparams(
                    holder=pause.backend_pid, waiter=pause.logout_pid,
                    key=_USER_MANAGEMENT_LOCK_ID,
                )).one()
                observer.rollback()
                if held and awaited:
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


def _stop_workers(pg_factory, threads: tuple[threading.Thread, ...],
                  backend_pids: tuple[int | None, ...]) -> list[str]:
    """Joins the route threads, ends the database work of any that stay, names those still alive."""
    for thread in threads:
        if thread.ident is not None:
            thread.join(WAIT_SECONDS)
    if any(thread.is_alive() for thread in threads):
        with pg_factory() as observer:
            for pid in filter(None, backend_pids):
                observer.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
            observer.commit()
        for thread in threads:
            thread.join(WAIT_SECONDS)
    return [thread.name for thread in threads if thread.is_alive()]


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
        headers={"host": backchannel_logout_host()},
    ))
    pause = _CallbackPause()
    engine = pg_factory.kw["bind"]
    event.listen(pg_factory, "before_commit", pause)
    event.listen(engine, "before_cursor_execute", pause.note_lock_request)
    try:
        callback.start()
        assert pause.reached.wait(WAIT_SECONDS), "The sign-in callback never reached its commit"
        logout.start()
        _wait_until_the_logout_waits_behind(pg_factory, pause)
        assert "logout" not in answers
    finally:
        pause.release.set()
        stuck = _stop_workers(pg_factory, (callback, logout), (pause.backend_pid, pause.logout_pid))
        event.remove(pg_factory, "before_commit", pause)
        event.remove(engine, "before_cursor_execute", pause.note_lock_request)
        if stuck:
            pytest.fail(f"Route threads never stopped: {', '.join(stuck)}")

    assert answers["callback"].status_code == 303
    assert answers["logout"].status_code == 200
    with pg_factory() as session:
        assert session.get(User, subject) is not None
        assert session.query(UserSession).filter_by(user_id=subject).count() == 0
