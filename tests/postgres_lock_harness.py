"""Helpers for PostgreSQL tests in which one writer is held mid-transaction while another waits."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

WAIT_SECONDS = 10

_BACKENDS_BLOCKED_BEHIND = text("""
    SELECT pid FROM pg_stat_activity
    WHERE datname = current_database() AND :holder = ANY(pg_blocking_pids(pid))
""")
_ADVISORY_WAITERS = text("""
    SELECT pid FROM pg_locks
    WHERE locktype = 'advisory' AND classid = 0 AND objid = :key AND objsubid = 1
      AND NOT granted AND pid = ANY(:waiters)
      AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
""")


class CommitPause:
    """Holds a writer at its pending commit and names the backend that holds its locks.

    Install it as a ``before_commit`` listener: the first commit whose session satisfies
    ``at_commit`` is held until ``release`` is set. A writer that drives its own commit
    calls ``hold`` instead.
    """

    def __init__(self, at_commit: Callable[[Session], bool] = lambda _session: True) -> None:
        self.at_commit = at_commit
        self.reached = threading.Event()
        self.release = threading.Event()
        self.backend_pid: int | None = None

    def hold(self, session: Session) -> None:
        self.backend_pid = session.execute(text("SELECT pg_backend_pid()")).scalar_one()
        self.reached.set()
        if not self.release.wait(WAIT_SECONDS):
            raise RuntimeError("The paused writer was never released")

    def __call__(self, session: Session) -> None:
        if not self.reached.is_set() and self.at_commit(session):
            self.hold(session)


def wait_until_blocked_behind(
    pg_factory: sessionmaker[Session], holder_pid: int | None, *, advisory_key: int | None = None,
) -> int:
    """Returns the backend that waits on a lock the holder's backend owns.

    ``advisory_key`` also requires that wait to be for that advisory lock.
    """
    deadline = time.monotonic() + WAIT_SECONDS
    with pg_factory() as observer:
        while time.monotonic() < deadline:
            waiters = [
                pid for pid in observer.execute(
                    _BACKENDS_BLOCKED_BEHIND, {"holder": holder_pid},
                ).scalars()
            ]
            if advisory_key is not None and waiters:
                waiters = list(observer.execute(
                    _ADVISORY_WAITERS, {"key": advisory_key, "waiters": waiters},
                ).scalars())
            observer.rollback()
            if waiters:
                return waiters[0]
            time.sleep(0.02)
    pytest.fail("No writer ever waited behind the paused one")


def in_thread(
    answers: dict[str, Any], name: str, call: Callable[[], Any],
) -> threading.Thread:
    """A daemon thread that stores what ``call`` returns, or raises, under ``name``."""
    def run() -> None:
        try:
            answers[name] = call()
        except BaseException as failure:  # noqa: BLE001 - reported by the asserting thread
            answers[name] = failure

    return threading.Thread(target=run, name=name, daemon=True)


def stop_workers(
    pg_factory: sessionmaker[Session],
    threads: tuple[threading.Thread, ...],
    backend_pids: tuple[int | None, ...],
) -> list[str]:
    """Joins the threads, ends the database work of any that stay, names those still alive."""
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
