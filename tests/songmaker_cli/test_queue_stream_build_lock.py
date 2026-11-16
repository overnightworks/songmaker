"""The queue-stream build lock keeps a build exclusive for longer than the lock lasts."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Lock
from types import SimpleNamespace

import anyio
import pytest
from anyio import from_thread
from anyio.from_thread import start_blocking_portal
from redis import exceptions as redis_errors
from support.web_app import SettledFakeAsyncRedis

from songmaker_cli.queue_stream_build_lock import (
    FAILED_RENEWAL_WARNING,
    LOST_LOCK_WARNING,
    build_lock,
)

SHORT_LOCK_LASTS = timedelta(seconds=0.4)
BUILD_SECONDS = 3 * SHORT_LOCK_LASTS.total_seconds()
KEY = "content-hash"


def test_a_build_longer_than_the_lock_lasts_stays_exclusive() -> None:
    ctx = SimpleNamespace(async_redis=SettledFakeAsyncRedis())
    builders_inside: list[int] = []
    inside = 0
    guard = Lock()

    def build() -> None:
        nonlocal inside
        with build_lock(ctx, KEY, lasts=SHORT_LOCK_LASTS):
            with guard:
                inside += 1
                builders_inside.append(inside)
            time.sleep(BUILD_SECONDS)
            with guard:
                inside -= 1

    def build_in_a_request_thread(portal) -> None:
        portal.call(anyio.to_thread.run_sync, build)

    with start_blocking_portal() as portal, ThreadPoolExecutor(max_workers=2) as pool:
        for future in [pool.submit(build_in_a_request_thread, portal) for _ in range(2)]:
            future.result()

    assert builders_inside == [1, 1]


class _UnreachableWhenArmedRedis(SettledFakeAsyncRedis):
    """A client whose server stops answering while ``unreachable`` is set."""

    unreachable = False

    async def execute_command(self, *args, **options):
        if self.unreachable:
            raise redis_errors.ConnectionError
        return await super().execute_command(*args, **options)


def _build_while(ctx, during_build: Callable[[], None]) -> None:
    def build() -> None:
        with build_lock(ctx, KEY, lasts=SHORT_LOCK_LASTS):
            during_build()
            time.sleep(SHORT_LOCK_LASTS.total_seconds())

    with start_blocking_portal() as portal:
        portal.call(anyio.to_thread.run_sync, build)


def test_a_lock_another_process_took_away_is_logged_and_the_build_finishes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ctx = SimpleNamespace(async_redis=SettledFakeAsyncRedis())
    other_process = ctx.async_redis.another_process()

    async def delete_the_generations() -> None:
        await other_process.delete(*await other_process.keys("*:generation"))

    with caplog.at_level(logging.WARNING):
        _build_while(ctx, lambda: from_thread.run(delete_the_generations))

    assert LOST_LOCK_WARNING in caplog.text


def test_a_lock_whose_renewal_fails_is_logged_and_the_build_finishes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ctx = SimpleNamespace(async_redis=_UnreachableWhenArmedRedis())

    def lose_the_server_for_the_renewal() -> None:
        ctx.async_redis.unreachable = True
        time.sleep(SHORT_LOCK_LASTS.total_seconds())
        ctx.async_redis.unreachable = False

    with caplog.at_level(logging.WARNING):
        _build_while(ctx, lose_the_server_for_the_renewal)

    assert FAILED_RENEWAL_WARNING in caplog.text
