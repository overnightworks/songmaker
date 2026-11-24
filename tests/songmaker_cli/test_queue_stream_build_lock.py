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
from redis.asyncio import Redis
from support.redis_clock import until, until_redis_has_passed
from support.redis_server import lose_everything, settle_the_real_servers_epoch
from support.redis_that_loses_its_first_lock import RedisThatLosesItsFirstLock
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


def _locks(client: Redis) -> Locks:
    return Locks(
        client, key_prefix=REDIS_KEY_PREFIX,
        family=QUEUE_STREAM_BUILD_LOCK_FAMILY, lasts=SHORT_LOCK_LASTS,
    )


def _run_one_build(redis_url: str, during_build: Callable[[SimpleNamespace, Locks], None]) -> bool:
    """Run one build in a request's worker thread; whether a third process can take the lock after.

    ``during_build`` gets the build's context and a second process's locks.
    """
    settle_the_real_servers_epoch(redis_url)
    clients = [create_async_redis(redis_url) for _ in range(3)]
    ctx = SimpleNamespace(async_redis=clients[0])
    second_process, third_process = _locks(clients[1]), _locks(clients[2])

    def build() -> None:
        with build_lock(ctx, KEY):
            during_build(ctx, second_process)

    with start_blocking_portal() as portal:
        try:
            portal.call(anyio.to_thread.run_sync, build)
            free_after_the_build = portal.call(third_process.acquire, KEY) is not None
        finally:
            for client in clients:
                portal.call(client.aclose)
    return free_after_the_build


def test_a_build_longer_than_the_lock_lasts_stays_exclusive(redis_url: str) -> None:
    other_process_took_it: list[bool] = []

    def build_for_twice_the_span(ctx: SimpleNamespace, second_process: Locks) -> None:
        from_thread.run(until_redis_has_passed, ctx.async_redis, 2 * SHORT_LOCK_LASTS)
        other_process_took_it.append(from_thread.run(second_process.acquire, KEY) is not None)

    free_after_the_build = _run_one_build(redis_url, build_for_twice_the_span)

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
        free_after_the_build = _run_one_build(redis_url, build_after_a_redis_restart)

    assert new_holder_took_it == [True]
    assert not free_after_the_build


def test_a_build_that_fails_raises_its_own_error_and_frees_the_lock(redis_url: str) -> None:
    def failing_build(_ctx: SimpleNamespace, _second_process: Locks) -> None:
        raise ValueError("the build failed")

    with pytest.raises(ValueError, match="the build failed"):
        _run_one_build(redis_url, failing_build)

    settle_the_real_servers_epoch(redis_url)
    assert _run_one_build(redis_url, lambda _ctx, _second_process: None)


def test_a_build_whose_lock_runs_out_before_its_entry_polls_again(redis_url: str) -> None:
    ran: list[bool] = []

    def server_forgets_the_lock() -> None:
        lose_everything(redis_url)
        settle_the_real_servers_epoch(redis_url)

    settle_the_real_servers_epoch(redis_url)
    forgetful = RedisThatLosesItsFirstLock.from_url(redis_url)
    forgetful.when_lost = server_forgets_the_lock
    third_process = create_async_redis(redis_url)

    def build() -> None:
        with build_lock(SimpleNamespace(async_redis=forgetful), KEY):
            ran.append(True)

    with start_blocking_portal() as portal:
        try:
            portal.call(anyio.to_thread.run_sync, build)
            free_after_the_build = portal.call(_locks(third_process).acquire, KEY) is not None
        finally:
            portal.call(forgetful.aclose)
            portal.call(third_process.aclose)

    assert forgetful.lost
    assert ran == [True]
    assert free_after_the_build
