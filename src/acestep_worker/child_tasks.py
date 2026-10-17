from __future__ import annotations

import asyncio
from typing import Any


async def settle_child_task(child: asyncio.Task[Any]) -> None:
    """Wait until a child task has ended; its own cancellation is accepted, its failure raised.

    A cancellation of the waiter reaches the child as if the waiter awaited it directly, and is
    re-raised once the child has ended, so the waiter's cleanup never starts while the child runs.
    """
    try:
        await asyncio.wait({child})
    except asyncio.CancelledError:
        child.cancel()
        await asyncio.wait({child})
        raise
    if not child.cancelled():
        child.result()
