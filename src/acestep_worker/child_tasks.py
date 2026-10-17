from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)


async def settle_child_task(child: asyncio.Task[Any]) -> None:
    """Wait until a child task has ended, however often the waiter is cancelled meanwhile.

    Each cancellation of the waiter reaches a still running child as if the waiter awaited it
    directly. The waiter's cancellation is re-raised only once the child has ended, so the
    waiter's cleanup never starts while the child runs. The child's own cancellation is accepted;
    its failure is raised, or logged when the waiter's cancellation takes precedence.
    """
    waiter_cancellation: asyncio.CancelledError | None = None
    while not child.done():
        try:
            await asyncio.wait({child})
        except asyncio.CancelledError as cancellation:
            waiter_cancellation = cancellation
            if not child.done():
                child.cancel()
    if waiter_cancellation is None:
        if not child.cancelled():
            child.result()
        return
    if not child.cancelled() and (failure := child.exception()) is not None:
        log.error("Child task failed while its waiter was cancelled", exc_info=failure)
    raise waiter_cancellation
