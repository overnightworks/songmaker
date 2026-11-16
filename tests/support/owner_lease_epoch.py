"""The epoch of tandem's keys, dated as on a Redis that has run for a lock or lease span."""

from __future__ import annotations

import time

# tandem offers no public helper that settles the epoch yet, so the test names its key itself.
from tandem.keys import lease_keys

from songmaker_cli.constants import REDIS_KEY_PREFIX
from songmaker_cli.job_timing import OWNER_LEASE_TTL_SECONDS
from songmaker_cli.worker_liveness import OWNER_LEASE_FAMILY

MILLISECONDS_PER_SECOND = 1000


def aged_epoch(span_seconds: float) -> tuple[str, int]:
    """The app's epoch key and a value older than ``span_seconds``, for ``SET`` on a Redis the
    test shares.

    An absent lease or lock reads gone, and a lock is acquired, only on a Redis that old; on a
    younger one, unknown, as after a restart. The epoch is one key for every family of the app.
    """
    now_ms = time.time_ns() // 1_000_000
    aged_ms = now_ms - int((span_seconds + 1) * MILLISECONDS_PER_SECOND)
    return lease_keys(REDIS_KEY_PREFIX, OWNER_LEASE_FAMILY).epoch, aged_ms


def aged_owner_lease_epoch() -> tuple[str, int]:
    """The epoch dated one lease span back."""
    return aged_epoch(OWNER_LEASE_TTL_SECONDS)
