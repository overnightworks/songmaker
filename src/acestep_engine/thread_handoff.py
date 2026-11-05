"""A blocking acquisition handed to a thread without losing what it acquires.

Music and the worker both install this package and neither may import the other.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial


def _release_acquired[ResourceT](
    acquisition: asyncio.Future[ResourceT], release: Callable[[ResourceT], None],
) -> None:
    if acquisition.exception() is None:
        release(acquisition.result())


async def acquire_in_thread[ResourceT](
    acquire: Callable[[], ResourceT], release: Callable[[ResourceT], None],
) -> ResourceT:
    """Run ``acquire`` in a thread; a cancelled caller still releases what it yields.

    Cancelling the await cannot stop the thread, so the acquisition is shielded, and after a
    cancel its result is released instead of being dropped with the future.
    """
    acquisition = asyncio.get_running_loop().run_in_executor(None, acquire)
    try:
        return await asyncio.shield(acquisition)
    except asyncio.CancelledError:
        acquisition.add_done_callback(partial(_release_acquired, release=release))
        await asyncio.wait([acquisition])
        raise
