"""The queue-stream build lock keeps a build exclusive for longer than the lock lasts.

Two processes' clients on one real Redis; the lock's span and extension step are patched short.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from types import SimpleNamespace

import anyio
import pytest
from anyio import from_thread
from anyio.from_thread import start_blocking_portal
from support.redis_clock import redis_ms, until, until_redis_ms
from support.redis_server import lose_everything, settle_the_real_servers_epoch
from tandem import Locks

from songmaker_cli import queue_stream_build_lock as build_lock_module
from songmaker_cli.constants import REDIS_KEY_PREFIX
from songmaker_cli.queue_stream_build_lock import QUEUE_STREAM_BUILD_LOCK_FAMILY, build_lock
from songmaker_cli.redis_client import create_async_redis

SHORT_LOCK_LASTS = timedelta(seconds=3)
SHORT_EXTEND_EVERY = timedelta(milliseconds=500)
KEY = "content-hash"
LOCK_LOST_LINE = "lock.lost"


@pytest.fixture(autouse=True)
def short_build_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(build_lock_module, "QUEUE_STREAM_BUILD_LOCK_LASTS", SHORT_LOCK_LASTS)
    monkeypatch.setattr(
        build_lock_module, "QUEUE_STREAM_BUILD_LOCK_EXTEND_EVERY", SHORT_EXTEND_EVERY,
    )


def _locks(redis_url: str) -> Locks:
    return Locks(
        create_async_redis(redis_url), key_prefix=REDIS_KEY_PREFIX,
        family=QUEUE_STREAM_BUILD_LOCK_FAMILY, lasts=SHORT_LOCK_LASTS,
    )


def _build(redis_url: str, during_build: Callable[[SimpleNamespace, Locks], None]) -> bool:
    """Run one build in a request's worker thread; whether a third process can take the lock after.

    ``during_build`` gets the build's context and a second process's locks.
    """
    settle_the_real_servers_epoch(redis_url)
    ctx = SimpleNamespace(async_redis=create_async_redis(redis_url))
    second_process, third_process = _locks(redis_url), _locks(redis_url)

    def build() -> None:
        with build_lock(ctx, KEY):
            during_build(ctx, second_process)

    with start_blocking_portal() as portal:
        portal.call(anyio.to_thread.run_sync, build)
        free_after_the_build = portal.call(third_process.acquire, KEY) is not None
    return free_after_the_build


def test_a_build_longer_than_the_lock_lasts_stays_exclusive(redis_url: str) -> None:
    other_process_took_it: list[bool] = []

    def build_for_twice_the_span(ctx: SimpleNamespace, second_process: Locks) -> None:
        end = from_thread.run(redis_ms, ctx.async_redis) + 2 * int(
            SHORT_LOCK_LASTS.total_seconds() * 1000,
        )
        from_thread.run(until_redis_ms, ctx.async_redis, end)
        other_process_took_it.append(from_thread.run(second_process.acquire, KEY) is not None)

    free_after_the_build = _build(redis_url, build_for_twice_the_span)

    assert other_process_took_it == [False]
    assert free_after_the_build


def test_a_lock_redis_lost_is_logged_and_the_build_finishes_beside_the_new_holder(
    redis_url: str, caplog: pytest.LogCaptureFixture,
) -> None:
    new_holder_took_it: list[bool] = []

    def build_after_a_redis_restart(ctx: SimpleNamespace, new_holder: Locks) -> None:
        lose_everything(redis_url)
        settle_the_real_servers_epoch(redis_url)
        new_holder_took_it.append(from_thread.run(new_holder.acquire, KEY) is not None)
        from_thread.run(until, lambda: any(r.message == LOCK_LOST_LINE for r in caplog.records))

    with caplog.at_level(logging.WARNING):
        free_after_the_build = _build(redis_url, build_after_a_redis_restart)

    assert new_holder_took_it == [True]
    assert not free_after_the_build
