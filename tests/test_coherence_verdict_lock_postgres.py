"""Competing first coherence verdicts on one take leave one row (PostgreSQL)."""

from __future__ import annotations

from postgres_lock_harness import CommitPause, race, wrote_to_tables
from test_coherence_verdict_tool import _save, _seed, _stored, _take


def test_competing_first_verdicts_leave_one_row_holding_the_later_pair(pg_factory):
    _seed(pg_factory)
    _take(pg_factory, "g1")
    pause = CommitPause(lambda session: wrote_to_tables(session, "scores"))

    race(
        pg_factory,
        lambda: _save(pg_factory, "g1", 8, "earlier"),
        lambda: _save(pg_factory, "g1", 6, "later"),
        pause,
    )

    assert _stored(pg_factory, "g1") == [
        ("batch", {"lyrical_coherence": 6, "lyrical_summary": "later"}),
    ]
