"""The countdown row on PostgreSQL: the migrated schema has it; a late acknowledgement is moot."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from sqlalchemy import text

from songmaker_cli.constants import SETTING_REFERENCE_COUNTDOWN_VISIBLE_SINCE
from songmaker_cli.db.queries.reference_recordings import (
    acknowledge_countdown_shown,
    get_countdown_publication,
)

FIRST_SHOWN = datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)
LATER_SHOWN = datetime(2026, 11, 7, 10, 5, tzinfo=timezone.utc)
WAIT_BOUND_SECONDS = 30


def _count_countdown_rows(session) -> int:
    return session.execute(
        text("SELECT count(*) FROM rate_limit_settings WHERE setting_key = :key"),
        {"key": SETTING_REFERENCE_COUNTDOWN_VISIBLE_SINCE},
    ).scalar_one()


def _a_session_waits_on_a_lock(session) -> bool:
    return session.execute(
        text(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname = current_database() AND wait_event_type = 'Lock'",
        ),
    ).scalar_one() > 0


def test_the_migrated_test_database_has_exactly_one_countdown_row(pg_factory) -> None:
    with pg_factory() as session:
        assert _count_countdown_rows(session) == 1


def test_two_concurrent_acknowledgements_write_once_and_both_succeed(pg_factory) -> None:
    with pg_factory() as first, pg_factory() as observer:
        epoch = get_countdown_publication(first).epoch
        results: list[bool] = []

        def second_acknowledgement() -> None:
            with pg_factory() as second:
                results.append(acknowledge_countdown_shown(second, epoch, LATER_SHOWN))
                second.commit()

        assert acknowledge_countdown_shown(first, epoch, FIRST_SHOWN)
        waiting = threading.Thread(target=second_acknowledgement, daemon=True)
        waiting.start()
        try:
            deadline = time.monotonic() + WAIT_BOUND_SECONDS
            poll = threading.Event()
            while waiting.is_alive() and not _a_session_waits_on_a_lock(observer):
                assert time.monotonic() < deadline, "the second acknowledgement never waited"
                observer.rollback()  # a fresh snapshot of the activity view
                poll.wait(0.01)
        finally:
            first.commit()
            waiting.join(WAIT_BOUND_SECONDS)
        assert not waiting.is_alive(), "the second acknowledgement did not finish"
        observer.rollback()

        assert results == [True]
        assert get_countdown_publication(first).published == FIRST_SHOWN
        first.rollback()
