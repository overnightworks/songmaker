"""The queue-stream build lock keeps a build exclusive for longer than the lock lasts."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import timedelta
from threading import Semaphore
from types import SimpleNamespace

import anyio
import pytest
from anyio import from_thread
from anyio.from_thread import start_blocking_portal
from fakeredis.commands_mixins import server_mixin
from redis import exceptions as redis_errors
from support.web_app import SettledFakeAsyncRedis
from tandem import Locks

from songmaker_cli import queue_stream_build_lock as build_lock_module
from songmaker_cli.constants import REDIS_KEY_PREFIX
from songmaker_cli.queue_stream_build_lock import (
    FAILED_RENEWAL_WARNING,
    LOST_LOCK_WARNING,
    QUEUE_STREAM_BUILD_LOCK_FAMILY,
    RENEWALS_PER_LOCK_SPAN,
    build_lock,
)

SHORT_LOCK_LASTS = timedelta(seconds=0.4)
STEP_SECONDS = SHORT_LOCK_LASTS.total_seconds() / RENEWALS_PER_LOCK_SPAN
BUILD_STEPS = 3 * RENEWALS_PER_LOCK_SPAN
KEY = "content-hash"


class _VirtualClock:
    """The server's TIME and the renewal's sleep, advanced only by the build.

    A sleep is armed once the renewal waits on it, so the build advances time only while the
    renewal is ready to answer, whatever the load of the machine.
    """

    ARMED_WITHIN_SECONDS = 10

    def __init__(self) -> None:
        self.start = time.time()
        self.elapsed = 0.0
        self._armed = Semaphore(0)

    def read(self) -> float:
        return self.start + self.elapsed

    async def sleep(self, seconds: float) -> None:
        wake = self.elapsed + seconds
        self._armed.release()
        while self.elapsed < wake:
            await asyncio.sleep(0)

    def advance_when_armed(self, seconds: float) -> None:
        assert self._armed.acquire(timeout=self.ARMED_WITHIN_SECONDS), "the renewal never ran"
        self.elapsed += seconds


def test_a_build_longer_than_the_lock_lasts_stays_exclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _VirtualClock()
    monkeypatch.setattr(server_mixin, "time", SimpleNamespace(time=clock.read))
    monkeypatch.setattr(
        build_lock_module,
        "asyncio",
        SimpleNamespace(
            create_task=asyncio.create_task,
            gather=asyncio.gather,
            sleep=clock.sleep,
        ),
    )
    ctx = SimpleNamespace(async_redis=SettledFakeAsyncRedis())
    other_process = Locks(
        ctx.async_redis.another_process(),
        key_prefix=REDIS_KEY_PREFIX,
        family=QUEUE_STREAM_BUILD_LOCK_FAMILY,
        lasts=SHORT_LOCK_LASTS,
    )
    other_process_took_it: list[bool] = []

    def build() -> None:
        with build_lock(ctx, KEY, lasts=SHORT_LOCK_LASTS):
            for _ in range(BUILD_STEPS):
                clock.advance_when_armed(STEP_SECONDS)
                taken = from_thread.run(other_process.acquire, KEY)
                other_process_took_it.append(taken is not None)

    with start_blocking_portal() as portal:
        portal.call(anyio.to_thread.run_sync, build)
        free_after_the_build = portal.call(other_process.acquire, KEY) is not None

    assert other_process_took_it == [False] * BUILD_STEPS
    assert free_after_the_build


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
