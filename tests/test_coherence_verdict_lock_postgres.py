"""Competing first coherence verdicts on one take leave one row (PostgreSQL)."""

from __future__ import annotations

from postgres_lock_harness import CommitPause, race, wrote_to_tables
from support.coherence_verdicts import add_take, save_verdict, seed_verdict_world, stored_scores


def test_competing_first_verdicts_leave_one_row_holding_the_later_pair(pg_factory):
    seed_verdict_world(pg_factory)
    add_take(pg_factory, "g1")
    pause = CommitPause(lambda session: wrote_to_tables(session, "scores"))

    race(
        pg_factory,
        lambda: save_verdict(pg_factory, "g1", 8, "earlier"),
        lambda: save_verdict(pg_factory, "g1", 6, "later"),
        pause,
    )

    assert stored_scores(pg_factory, "g1") == [
        ("batch", {"lyrical_coherence": 6, "lyrical_summary": "later"}),
    ]
