"""Waits on Redis TIME, the clock the crons' due times are stamped on: bounded polls."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from redis import Redis as SyncRedis
from redis.asyncio import Redis

from songmaker_cli.cron_schedule import Cron, datetime_from_redis_time, next_tick, redis_now

POLL_SECONDS = 0.01
WITHIN_SECONDS = 15
EPOCH = datetime.fromtimestamp(0, UTC)


async def redis_ms(client: Redis) -> int:
    return (await redis_now(client) - EPOCH) // timedelta(milliseconds=1)


async def until(condition: Callable[[], bool]) -> None:
    """Wait until ``condition`` holds; a case it never holds for fails after ``WITHIN_SECONDS``."""
    async with asyncio.timeout(WITHIN_SECONDS):
        while not condition():
            await asyncio.sleep(POLL_SECONDS)


async def until_redis_ms(client: Redis, target_ms: int) -> None:
    """Wait until Redis's own clock has reached ``target_ms``."""
    async with asyncio.timeout(WITHIN_SECONDS):
        while await redis_ms(client) < target_ms:
            await asyncio.sleep(POLL_SECONDS)


async def until_redis_has_passed(client: Redis, span: timedelta) -> None:
    """Wait for ``span`` of Redis's clock, from now."""
    await until_redis_ms(client, await redis_ms(client) + int(span.total_seconds() * 1000))


def redis_datetime(client: SyncRedis) -> datetime:
    return datetime_from_redis_time(*client.time())


def ticks_between(cron: Cron, start: datetime, end: datetime) -> int:
    """How many ticks of ``cron`` fall after ``start`` up to ``end``."""
    ticks = 0
    tick = next_tick(cron, start)
    while tick <= end:
        ticks += 1
        tick = next_tick(cron, tick)
    return ticks


def most_runs_between(cron: Cron, start: datetime, end: datetime) -> int:
    """How often ``cron`` may have run from ``start`` to ``end``: once, then once per tick."""
    return 1 + ticks_between(cron, start, end)


@dataclass
class Window:
    """The span of Redis time a scenario observes: a tick inside it explains a run beyond the
    expected ones, because a recurred cron runs again at its next tick."""

    start: datetime | None = None
    end: datetime | None = None

    @asynccontextmanager
    async def observing(self, client: Redis) -> AsyncIterator[None]:
        self.start = await redis_now(client)
        yield
        self.end = await redis_now(client)

    def without_the_runs_its_ticks_explain(
        self, counts: Mapping[Cron, int], expected: Mapping[Cron, int],
    ) -> dict[Cron, int]:
        """``counts`` less, per cron, the extra runs that ticks in the window explain."""
        assert self.start is not None
        assert self.end is not None
        extra = {cron: max(0, counts.get(cron, 0) - expected.get(cron, 0)) for cron in Cron}
        return {
            cron: counts.get(cron, 0)
            - min(extra[cron], ticks_between(cron, self.start, self.end))
            for cron in Cron
        }
