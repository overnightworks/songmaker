"""Tests a child pytest runs for tests/test_postgresql_databases.py; never collected on their own.

Each database test prints the name of the database it got, so the parent can check that
the child's teardown dropped it.
"""

from __future__ import annotations

import signal

from sqlalchemy import text

DATABASE_LINE = "probe-database="
_leaked_sessions = []


def _announce(pg_factory) -> None:
    print(f"{DATABASE_LINE}{pg_factory.kw['bind'].url.database}", flush=True)  # noqa: T201 - the parent reads this line


def test_probe_needs_no_database():
    assert True


def test_probe_needs_a_database(pg_factory):
    _announce(pg_factory)


def test_probe_fails_after_using_its_database(pg_factory):
    _announce(pg_factory)
    raise AssertionError("this probe fails on purpose")


def test_probe_leaves_a_session_open(pg_factory):
    _announce(pg_factory)
    session = pg_factory()
    session.execute(text("SELECT count(*) FROM users"))
    _leaked_sessions.append(session)


def test_probe_waits_for_an_interrupt(pg_factory):
    _announce(pg_factory)
    signal.pause()
