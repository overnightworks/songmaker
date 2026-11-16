"""The lock that serialises one queue-stream build across every web process."""

from __future__ import annotations

import asyncio
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
QUEUE_STREAM_BUILD_LOCK_RENEW_SECONDS: Final = QUEUE_STREAM_BUILD_LOCK_LASTS.total_seconds() / 3


@contextmanager
def build_lock(ctx: AppContext, key: str) -> Iterator[None]:
    """Serialize builds of one content hash or snapshot id across every web process.

    Runs in a request's worker thread and takes the lock on the app's event loop, which renews it
    while the build runs. The lock lasts a short span, so a dead builder frees it quickly and a
    Redis restart holds builds only that long.
    """
    locks = Locks(
        ctx.async_redis, key_prefix=_consts.REDIS_KEY_PREFIX, family="queue-stream-build",
        lasts=QUEUE_STREAM_BUILD_LOCK_LASTS,
    )
    while (generation := from_thread.run(locks.acquire, key)) is None:
        time.sleep(QUEUE_STREAM_BUILD_POLL_SECONDS)
    renewal = from_thread.run(_start_renewing, locks, key, generation)
    try:
        yield
    finally:
        from_thread.run(_stop_renewing, renewal)
        from_thread.run(locks.release, key, generation)


async def _start_renewing(locks: Locks, key: str, generation: str) -> asyncio.Task[None]:
    async def renew() -> None:
        while True:
            await asyncio.sleep(QUEUE_STREAM_BUILD_LOCK_RENEW_SECONDS)
            await locks.extend(key, generation)

    return asyncio.create_task(renew())


async def _stop_renewing(renewal: asyncio.Task[None]) -> None:
    renewal.cancel()
    await asyncio.gather(renewal, return_exceptions=True)
