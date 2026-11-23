"""Waits on Redis TIME, the clock the crons' due times are stamped on: bounded polls."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from redis import Redis as SyncRedis
from redis.asyncio import Redis

from songmaker_cli.cron_schedule import Cron, next_tick, redis_now

POLL_SECONDS = 0.01
WITHIN_SECONDS = 15


async def redis_ms(client: Redis) -> int:
    seconds, microseconds = await client.time()
    return int(seconds) * 1000 + int(microseconds) // 1000


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


async def until_no_file_cleanup_tick_within(client: Redis, span: timedelta) -> None:
    """Wait until Redis's clock is more than ``span`` before the next file-cleanup tick.

    A recurred cleanup runs again at that tick: a test that counts runs must end before it.
    """
    async with asyncio.timeout(WITHIN_SECONDS):
        while True:
            now = await redis_now(client)
            if next_tick(Cron.CLEANUP_FILES, now) - now > span:
                return
            await asyncio.sleep(POLL_SECONDS)


def redis_datetime(client: SyncRedis) -> datetime:
    seconds, microseconds = client.time()
    return datetime.fromtimestamp(int(seconds), UTC).replace(microsecond=int(microseconds))


def most_runs_between(cron: Cron, start: datetime, end: datetime) -> int:
    """How often ``cron`` may have run from ``start`` to ``end``: once, then once per tick."""
    runs = 1
    tick = next_tick(cron, start)
    while tick <= end:
        runs += 1
        tick = next_tick(cron, tick)
    return runs
