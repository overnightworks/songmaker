"""Two processes' clients on one real Redis: the locks that single-flight a tick, a download and
the GPU, in the order each race can take and after a Redis restart.

The Lua of the GPU admission runs on Redis itself here; the fakes run it on an emulation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from redis import Redis
from support.owner_lease_epoch import settled_epoch

from acestep_worker.heartbeat import reserve_gpu_hold
from songmaker_cli.acestep_state import (
    DownloadAlreadyRunning,
    admit_generation,
    gpu_hold_is_free,
    read_queue_depth,
    single_flight_download,
)
from songmaker_cli.lifecycle import JOB_REAPER_LOCK_NAME, tick_locks
from songmaker_cli.redis_client import create_async_redis

WORKER = "acestep-worker-0"


def _settle_the_epoch(redis_url: str) -> None:
    """Date the epoch as on a Redis that has run longer than any lock lasts."""
    with Redis.from_url(redis_url) as server:
        server.set(*settled_epoch())


def _lose_everything(redis_url: str) -> None:
    """What a Redis restart does to the keys."""
    with Redis.from_url(redis_url) as server:
        server.flushall()


def _in_two_processes(
    redis_url: str, scenario: Callable[[object, object], Awaitable[object]],
) -> object:
    async def run() -> object:
        first, second = create_async_redis(redis_url), create_async_redis(redis_url)
        try:
            return await scenario(first, second)
        finally:
            await first.aclose()
            await second.aclose()

    return asyncio.run(run())


def test_one_of_two_processes_takes_a_tick_lock(redis_url: str) -> None:
    _settle_the_epoch(redis_url)

    async def scenario(first, second) -> list[bool]:
        return [
            await tick_locks(first).acquire(JOB_REAPER_LOCK_NAME) is not None,
            await tick_locks(second).acquire(JOB_REAPER_LOCK_NAME) is not None,
        ]

    assert _in_two_processes(redis_url, scenario) == [True, False]


def test_a_download_of_a_mode_runs_in_one_of_two_processes(redis_url: str) -> None:
    _settle_the_epoch(redis_url)

    async def scenario(first, second) -> str | None:
        async with single_flight_download(first, "sft", "job-1"):
            with pytest.raises(DownloadAlreadyRunning) as refused:
                async with single_flight_download(second, "sft", "job-2"):
                    pytest.fail("a second download of the mode must not start")
        return refused.value.job_id

    assert _in_two_processes(redis_url, scenario) == "job-1"


def test_the_worker_reserve_and_the_web_admission_cannot_both_win(redis_url: str) -> None:
    _settle_the_epoch(redis_url)

    async def scenario(worker, web) -> tuple[bool, bool, int]:
        reserved = await reserve_gpu_hold(worker, WORKER) is not None
        admitted = await admit_generation(web, WORKER)
        return reserved, admitted, await read_queue_depth(web, WORKER)

    assert _in_two_processes(redis_url, scenario) == (True, False, 0)


def test_the_web_admission_wins_against_a_later_worker_reserve(redis_url: str) -> None:
    _settle_the_epoch(redis_url)

    async def scenario(worker, web) -> tuple[bool, bool, int]:
        admitted = await admit_generation(web, WORKER)
        reserved = await reserve_gpu_hold(worker, WORKER) is not None
        return admitted, reserved, await read_queue_depth(web, WORKER)

    assert _in_two_processes(redis_url, scenario) == (True, False, 1)


def test_the_gpu_is_refused_to_both_sides_until_a_restart_is_settled(redis_url: str) -> None:
    _settle_the_epoch(redis_url)
    _lose_everything(redis_url)

    async def scenario(worker, web) -> tuple[bool, bool, bool]:
        return (
            await gpu_hold_is_free(web, WORKER),
            await admit_generation(web, WORKER),
            await reserve_gpu_hold(worker, WORKER) is not None,
        )

    assert _in_two_processes(redis_url, scenario) == (False, False, False)

    _settle_the_epoch(redis_url)

    async def after_the_span(worker, web) -> tuple[bool, bool]:
        return await gpu_hold_is_free(web, WORKER), await admit_generation(web, WORKER)

    assert _in_two_processes(redis_url, after_the_span) == (True, True)
