"""How a queued job row reaches a worker: a wake says look now, a poll says look anyway.

PostgreSQL holds the queue. A wake on the app's channel carries no job, only the address of a
queue; a worker that hears it, or that has gone without one for a poll interval, claims the
rows that are due.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from tandem import StoreError, Wake, WakeChannel

from songmaker_cli.constants import REDIS_KEY_PREFIX
from songmaker_cli.job_payloads import JobPayload

if TYPE_CHECKING:
    from redis.asyncio import Redis

log = logging.getLogger(__name__)

# A wake that Redis dropped, or that no worker was following yet, is never repeated: this
# interval bounds how long such a job waits. It costs one indexed SELECT per worker and interval.
QUEUE_POLL_INTERVAL_SECONDS: Final = 5.0
_WAKE_READY_WITHIN: Final = timedelta(seconds=5)


class JobQueue(StrEnum):
    """A queue's address on the wake channel."""

    SCORE = "queue/score"


@dataclass(frozen=True)
class ClaimedJob:
    """A row this worker moved to running, read before its claim was committed."""

    job_id: str
    payload: JobPayload | None


def app_wake_channel(redis: Redis) -> WakeChannel:
    """The app's one wake channel on ``redis``; its addresses tell what changed."""
    return WakeChannel(redis, key_prefix=REDIS_KEY_PREFIX)


async def publish_queue_wake(wake_channel: WakeChannel, queue: JobQueue) -> None:
    """Tell the workers of ``queue`` that a row is due; call it after the row's commit.

    A wake that cannot be sent leaves the committed row to the next poll.
    """
    try:
        await wake_channel.publish(queue)
    except StoreError:
        log.warning("A wake of queue %s could not be sent; the next poll finds the job", queue)


class _Wakeup:
    """The event a wake, a resync or an ended job sets for the claiming loop."""

    def __init__(self, queue: JobQueue) -> None:
        self._queue = queue
        self.event = asyncio.Event()

    def on_wake(self, wake: Wake) -> None:
        if wake.address == self._queue:
            self.event.set()

    def on_resync(self) -> None:
        # A wake sent while the subscription was down is lost: look again.
        self.event.set()

    def on_failed(self, _error: Exception) -> None:
        log.warning("Wake channel of queue %s lost; claiming by poll only", self._queue)
        self.event.set()


async def serve_queue[Claimed](
    wake_channel: WakeChannel,
    queue: JobQueue,
    *,
    claim: Callable[[], Claimed | None],
    run: Callable[[Claimed], Coroutine[None, None, None]],
    places: asyncio.Semaphore,
    poll_interval: float,
    drain_seconds: float,
) -> None:
    """Claim and run the due jobs of ``queue``, one per free place of ``places``, until cancelled.

    ``places`` is the worker's one capacity: every path that runs a job in the process takes a
    place from it, so the paths never run more jobs together than the worker has places for.
    ``claim`` is a blocking call that returns one claimed job or none; the loop looks again
    when a wake arrives or ``poll_interval`` seconds have passed without one. A cancel stops
    the claiming and waits up to ``drain_seconds`` for the running jobs; one still running then
    keeps its row, which the owner's lease hands to the reaper.
    """
    loop = _ClaimLoop(queue, claim, run, places, poll_interval)
    try:
        async with AsyncExitStack() as following:
            try:
                await following.enter_async_context(wake_channel.following(
                    on_resync=loop.wakeup.on_resync, on_wake=loop.wakeup.on_wake,
                    on_failed=loop.wakeup.on_failed, ready_within=_WAKE_READY_WITHIN,
                ))
            except StoreError:
                log.warning("Wake channel unreachable; queue %s is claimed by poll only", queue)
            await loop.claim_while_due()
    finally:
        await loop.drain(drain_seconds)


class _ClaimLoop[Claimed]:
    def __init__(
        self,
        queue: JobQueue,
        claim: Callable[[], Claimed | None],
        run: Callable[[Claimed], Coroutine[None, None, None]],
        places: asyncio.Semaphore,
        poll_interval: float,
    ) -> None:
        self.wakeup = _Wakeup(queue)
        self._claim = claim
        self._run = run
        self._free_places = places
        self._poll_interval = poll_interval
        self._running: set[asyncio.Task[None]] = set()

    async def claim_while_due(self) -> None:
        while True:
            self.wakeup.event.clear()
            await self._free_places.acquire()
            claimed = await self._claim_without_losing_it()
            if claimed is None:
                self._free_places.release()
                await self._wait_for_wakeup()
            else:
                self._start(claimed)

    async def _claim_without_losing_it(self) -> Claimed | None:
        """Claim once; a cancel that arrives mid-claim still runs the row the claim took."""
        claiming = asyncio.ensure_future(asyncio.to_thread(self._claim))
        try:
            return await asyncio.shield(claiming)
        except asyncio.CancelledError:
            if (claimed := await claiming) is not None:
                self._start(claimed)
            raise
        except Exception:
            log.exception("Claiming a job failed; trying again at the next poll")
            return None

    def _start(self, claimed: Claimed) -> None:
        task = asyncio.create_task(self._run(claimed))
        self._running.add(task)
        task.add_done_callback(self._job_ended)

    def _job_ended(self, task: asyncio.Task[None]) -> None:
        self._running.discard(task)
        self._free_places.release()
        self.wakeup.event.set()
        if not task.cancelled() and (error := task.exception()) is not None:
            log.error("A claimed job ended with an error", exc_info=error)

    async def _wait_for_wakeup(self) -> None:
        with suppress(TimeoutError):
            await asyncio.wait_for(self.wakeup.event.wait(), self._poll_interval)

    async def drain(self, drain_seconds: float) -> None:
        if not self._running:
            return
        _, unfinished = await asyncio.wait(self._running, timeout=drain_seconds)
        for task in unfinished:
            task.cancel()
