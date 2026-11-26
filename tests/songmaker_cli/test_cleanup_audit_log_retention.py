"""The audit-log retention run deletes entries older than the period and nothing else."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from songmaker_cli.cleanup import run_audit_log_retention
from songmaker_cli.db.models import AuditLog, User

NOW = datetime(2026, 11, 26, 3, 0, tzinfo=UTC)


def _write_entry(factory, entry_id: str, created_at: datetime, *, person: str | None) -> None:
    with factory() as session:
        session.add(AuditLog(
            id=entry_id, user_id=person, action="login", resource_type="session",
            created_at=created_at,
        ))
        session.commit()


def _remaining_ids(factory) -> set[str]:
    with factory() as session:
        return {entry.id for entry in session.query(AuditLog)}


@pytest.fixture
def audit_log_factory(pg_factory):
    with pg_factory() as session:
        session.add(User(id="person", username="person"))
        session.commit()
    return pg_factory


@pytest.mark.parametrize("days", [1, 90])
def test_the_run_deletes_the_entries_older_than_the_period_and_keeps_the_rest(
    audit_log_factory, days: int,
) -> None:
    day = timedelta(days=1)
    _write_entry(audit_log_factory, "old-person", NOW - (days + 1) * day, person="person")
    _write_entry(audit_log_factory, "old-nobody", NOW - (days + 1) * day, person=None)
    _write_entry(audit_log_factory, "at-the-cutoff", NOW - days * day, person="person")
    if days > 1:
        _write_entry(audit_log_factory, "younger", NOW - (days - 1) * day, person="person")
    _write_entry(audit_log_factory, "written-now", NOW, person=None)

    deleted = run_audit_log_retention(audit_log_factory, days=days, now=NOW)

    assert deleted == 2
    assert _remaining_ids(audit_log_factory) == (
        {"at-the-cutoff", "written-now"} | ({"younger"} if days > 1 else set())
    )


def test_a_second_run_at_the_same_instant_deletes_nothing(audit_log_factory) -> None:
    _write_entry(audit_log_factory, "old", NOW - timedelta(days=100), person=None)
    run_audit_log_retention(audit_log_factory, days=90, now=NOW)

    assert run_audit_log_retention(audit_log_factory, days=90, now=NOW) == 0
