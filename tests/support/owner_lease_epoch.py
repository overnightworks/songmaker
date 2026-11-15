"""The epoch of the owner leases, dated as on a Redis that has run for the lease span."""

from __future__ import annotations

import time

# tandem offers no public helper that settles the epoch yet, so the test names its key itself.
from tandem.keys import lease_keys

from songmaker_cli.constants import REDIS_KEY_PREFIX
from songmaker_cli.job_timing import OWNER_LEASE_TTL_SECONDS
from songmaker_cli.worker_liveness import OWNER_LEASE_FAMILY

MILLISECONDS_PER_SECOND = 1000


def aged_owner_lease_epoch() -> tuple[str, int]:
    """The epoch key and a value one lease span old, for ``SET`` on a Redis the test shares.

    An absent lease reads gone only on a Redis that old; on a younger one, unknown, as after a
    restart.
    """
    now_ms = time.time_ns() // 1_000_000
    aged_ms = now_ms - (OWNER_LEASE_TTL_SECONDS + 1) * MILLISECONDS_PER_SECOND
    return lease_keys(REDIS_KEY_PREFIX, OWNER_LEASE_FAMILY).epoch, aged_ms
