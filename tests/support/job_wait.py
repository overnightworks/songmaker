"""The wait a deferred job's row names beside the delay its queue message carries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from songmaker_cli.db.models import Job


def now() -> datetime:
    return datetime.now(timezone.utc)


def run_after_follows_defer(
    job: Job, defer_seconds: float, before_deferral: datetime, after_deferral: datetime,
) -> bool:
    """Whether the row's ``run_after`` lies the queue message's delay after the deferral."""
    delay = timedelta(seconds=defer_seconds)
    return job.run_after is not None and (
        before_deferral + delay <= job.run_after <= after_deferral + delay
    )
