"""The music worker's recurring jobs: when each is due and how the workers share the due times.

Each cron is one key of a tandem ``Deadlines`` of kind ``worker-crons``. Redis TIME is the only
clock: a due time is stamped on it by tandem and the next tick is computed from it, so no pod's
own clock decides when a cron runs. A key absent from Redis (a first start, a Redis that lost
its data) is armed due now, so it costs one run of an idempotent body and never a skipped day.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import NoReturn

from redis.asyncio import Redis
from tandem import Deadlines, Due

from songmaker_cli.cleanup import DAILY_CLEANUP_HOUR_UTC
from songmaker_cli.constants import (
    CRON_CLAIM_FOR_SECONDS,
    CRON_EVERY_SECONDS,
    CRON_STOP_WAIT_SECONDS,
    REDIS_KEY_PREFIX,
)
from songmaker_cli.worker_base import logged_cron

log = logging.getLogger(__name__)

CRON_DEADLINES_KIND = "worker-crons"
UNKNOWN_CRON_EVENT = "cron_job.unknown"
RECUR_FAILED_AT_STOP_EVENT = "cron_job.recur_failed_at_stop"
FILE_CLEANUP_MINUTES = 2
CLAIM_FOR = timedelta(seconds=CRON_CLAIM_FOR_SECONDS)
EVERY = timedelta(seconds=CRON_EVERY_SECONDS)
STOP_WAIT = timedelta(seconds=CRON_STOP_WAIT_SECONDS)

type CronBody = Callable[[], Awaitable[object]]


class Cron(StrEnum):
    """The recurring jobs; each value is the deadline's key and names the job on its line."""

    CLEANUP_FILES = "cleanup_files_cron"
    GENERATION_RETENTION = "generation_retention_cron"
    REFERENCE_REMNANT = "reference_remnant_cron"
    REFERENCE_UNUSED = "reference_unused_cron"


def next_tick(cron: Cron, now: datetime) -> datetime:
    """The first tick of ``cron`` strictly after ``now``: the file cleanup runs at second 0 of
    every even minute, the daily jobs at the daily cleanup hour."""
    if cron is Cron.CLEANUP_FILES:
        minute = now.replace(second=0, microsecond=0)
        wait_minutes = FILE_CLEANUP_MINUTES - minute.minute % FILE_CLEANUP_MINUTES
        return minute + timedelta(minutes=wait_minutes)
    today = now.replace(hour=DAILY_CLEANUP_HOUR_UTC, minute=0, second=0, microsecond=0)
    return today if today > now else today + timedelta(days=1)


def cron_deadlines(redis: Redis, *, claim_for: timedelta = CLAIM_FOR) -> Deadlines:
    return Deadlines(
        redis, key_prefix=REDIS_KEY_PREFIX, kind=CRON_DEADLINES_KIND, claim_for=claim_for,
    )


async def redis_now(redis: Redis) -> datetime:
    seconds, microseconds = await redis.time()
    return datetime.fromtimestamp(int(seconds), UTC).replace(microsecond=int(microseconds))


async def serve_due_crons(
    redis: Redis,
    bodies: Mapping[Cron, CronBody],
    *,
    claim_for: timedelta = CLAIM_FOR,
    every: timedelta = EVERY,
    stop_wait: timedelta = STOP_WAIT,
) -> NoReturn:
    """Run the body of every cron that comes due, on one worker of any number, until cancelled.

    ``stop_wait`` is how long a stop waits for a running body: a stop cancels the claim's
    extensions with the body, so the claim lives on for at least two thirds of ``claim_for``, and
    a wait beyond that would let another worker start the body that still runs here.
    """
    deadlines = cron_deadlines(redis, claim_for=claim_for)
    crons = _DueCrons(deadlines, redis, bodies, stop_wait)
    await deadlines.serve_due(crons.handle, every=every, reconcile=crons.arm_all)


class _DueCrons:
    def __init__(
        self, deadlines: Deadlines, redis: Redis, bodies: Mapping[Cron, CronBody],
        stop_wait: timedelta,
    ) -> None:
        self._deadlines = deadlines
        self._redis = redis
        self._bodies = bodies
        self._stop_wait = stop_wait

    async def arm_all(self) -> None:
        """Arm every cron due now unless it waits or is claimed."""
        for cron in Cron:
            await self._deadlines.arm(cron, timedelta(0))

    async def handle(self, due: Due) -> None:
        try:
            cron = Cron(due.key)
        except ValueError:
            log.warning(UNKNOWN_CRON_EVENT, extra={"cron_key": due.key})
            await self._deadlines.cancel(due.key)
            return
        running = asyncio.ensure_future(logged_cron(cron.value, self._bodies[cron])())
        try:
            await asyncio.shield(running)
        except asyncio.CancelledError:
            if await self._ended_within_the_stop_wait(running):
                await self._recur_without_replacing_the_stop(cron, due)
            raise
        except Exception:
            await self._recur(cron, due)
            raise
        await self._recur(cron, due)

    async def _ended_within_the_stop_wait(self, running: asyncio.Future[object]) -> bool:
        """Wait for the body up to the stop wait, then cut it; whether it ended by itself."""
        _, unfinished = await asyncio.wait({running}, timeout=self._stop_wait.total_seconds())
        if unfinished:
            running.cancel()
            await asyncio.wait({running})
        if not running.cancelled():
            running.exception()  # the body's own line names it; no unretrieved error is left
        return not unfinished

    async def _recur_without_replacing_the_stop(self, cron: Cron, due: Due) -> None:
        """Recur, and log a failure instead of raising it: a raised error would replace the stop's
        cancellation, and tandem would hand this worker the next key of its batch."""
        try:
            await self._recur(cron, due)
        except Exception:
            log.exception(RECUR_FAILED_AT_STOP_EVENT, extra={"cron_key": cron.value})

    async def _recur(self, cron: Cron, due: Due) -> None:
        now = await redis_now(self._redis)
        await self._deadlines.recur(due, next_tick(cron, now) - now)
