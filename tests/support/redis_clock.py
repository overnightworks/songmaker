"""Waits on Redis TIME, the clock the crons' due times are stamped on: bounded polls."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta

from redis.asyncio import Redis

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
