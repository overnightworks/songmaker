"""The lock that serialises one queue-stream build across every web process."""

from __future__ import annotations

import sys
import time
from collections.abc import Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from datetime import timedelta
from typing import Final

from anyio import from_thread
from tandem import LockLost, Locks

import songmaker_cli.constants as _consts
from songmaker_cli.app_context import AppContext

QUEUE_STREAM_BUILD_POLL_SECONDS: Final = 0.25
# A dead builder frees the lock after one span, and a Redis restart holds builds only that long.
QUEUE_STREAM_BUILD_LOCK_LASTS: Final = timedelta(seconds=15)
QUEUE_STREAM_BUILD_LOCK_EXTEND_EVERY: Final = timedelta(seconds=5)
QUEUE_STREAM_BUILD_LOCK_FAMILY: Final = "queue-stream-build"


@contextmanager
def build_lock(ctx: AppContext, key: str) -> Iterator[None]:
    """Serialize builds of one content hash or snapshot id across every web process.

    Runs in a request's worker thread; tandem's ``held`` extends the lock on the app's event loop
    while the build runs. A build whose lock was lost finishes anyway: a thread cannot be
    cancelled, and the cost of a second build of the same stream is one extra snapshot.
    """
    locks = Locks(
        ctx.async_redis, key_prefix=_consts.REDIS_KEY_PREFIX, family=QUEUE_STREAM_BUILD_LOCK_FAMILY,
        lasts=QUEUE_STREAM_BUILD_LOCK_LASTS,
    )
    while (keeping := _acquire_and_keep(locks, key)) is None:
        time.sleep(QUEUE_STREAM_BUILD_POLL_SECONDS)
    try:
        yield
    finally:
        from_thread.run(keeping.__aexit__, *sys.exc_info())


def _acquire_and_keep(locks: Locks, key: str) -> AbstractAsyncContextManager[None] | None:
    """The entered keeper of the lock, or None while another process holds it.

    The thread enters and leaves ``held`` in two tasks of the loop, which only
    ``cancel_on_loss=False`` allows.
    """
    generation = from_thread.run(locks.acquire, key)
    if generation is None:
        return None
    keeping = locks.held(
        key, generation, every=QUEUE_STREAM_BUILD_LOCK_EXTEND_EVERY, cancel_on_loss=False,
    )
    try:
        from_thread.run(keeping.__aenter__)
    except LockLost:
        return None
    return keeping
