"""The lock that serialises one queue-stream build across every web process."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Final

from anyio import from_thread
from tandem import Locks

import songmaker_cli.constants as _consts
from songmaker_cli.app_context import AppContext

QUEUE_STREAM_BUILD_POLL_SECONDS: Final = 0.25
QUEUE_STREAM_BUILD_LOCK_LASTS: Final = timedelta(seconds=15)
RENEWALS_PER_LOCK_SPAN: Final = 3
LOST_LOCK_WARNING: Final = (
    "Queue stream build lock lost while building; another process may build the same stream"
)
FAILED_RENEWAL_WARNING: Final = (
    "Queue stream build lock renewal failed; the lock lapses unless a later renewal succeeds"
)

log = logging.getLogger(__name__)


@contextmanager
def build_lock(
    ctx: AppContext, key: str, *, lasts: timedelta = QUEUE_STREAM_BUILD_LOCK_LASTS,
) -> Iterator[None]:
    """Serialize builds of one content hash or snapshot id across every web process.

    Runs in a request's worker thread and takes the lock on the app's event loop, which renews it
    while the build runs. The lock lasts a short span, so a dead builder frees it quickly and a
    Redis restart holds builds only that long.
    """
    locks = Locks(
        ctx.async_redis, key_prefix=_consts.REDIS_KEY_PREFIX, family="queue-stream-build",
        lasts=lasts,
    )
    while (generation := from_thread.run(locks.acquire, key)) is None:
        time.sleep(QUEUE_STREAM_BUILD_POLL_SECONDS)
    renewal = from_thread.run_sync(_start_renewing, locks, key, generation, lasts)
    try:
        yield
    finally:
        from_thread.run(_stop_renewing, renewal)
        from_thread.run(locks.release, key, generation)


def _start_renewing(
    locks: Locks, key: str, generation: str, lasts: timedelta,
) -> asyncio.Task[None]:
    async def renew() -> None:
        while True:
            await asyncio.sleep(lasts.total_seconds() / RENEWALS_PER_LOCK_SPAN)
            try:
                if not await locks.extend(key, generation):
                    log.warning(LOST_LOCK_WARNING)
                    return
            except Exception:
                log.warning(FAILED_RENEWAL_WARNING, exc_info=True)

    return asyncio.create_task(renew())


async def _stop_renewing(renewal: asyncio.Task[None]) -> None:
    renewal.cancel()
    await asyncio.gather(renewal, return_exceptions=True)
