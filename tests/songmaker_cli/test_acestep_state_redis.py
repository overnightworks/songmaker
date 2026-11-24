"""Two processes' clients on one real Redis: the locks that single-flight a tick, a download and
the GPU, in the order each race can take and after a Redis restart.

The Lua of the GPU admission runs on Redis itself here; the fakes run it on an emulation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta

import pytest
from support.redis_clock import until_redis_has_passed
from support.redis_server import lose_everything, settle_the_real_servers_epoch
from support.redis_that_loses_its_first_lock import RedisThatLosesItsFirstLock
from support.refused_download import attempt_download_that_must_not_run

from songmaker_acestep_worker.heartbeat import reserve_gpu_hold
from songmaker_cli.acestep_state import (
    DownloadAlreadyRunning,
    DownloadLockLost,
    admit_generation,
    download_key,
    download_locks,
    gpu_hold_is_free,
    read_download_in_progress,
    read_queue_depth,
    single_flight_download,
)
from songmaker_cli.lifecycle import JOB_REAPER_LOCK_NAME, tick_locks
from songmaker_cli.redis_client import create_async_redis

WORKER = "acestep-worker-0"
SHORT_LOCK_LASTS = timedelta(seconds=3)
SHORT_EXTEND_EVERY = timedelta(milliseconds=500)
DOWNLOAD_LOST_WITHIN_SECONDS = 15


@pytest.fixture
def short_download_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("songmaker_cli.acestep_state.DOWNLOAD_LOCK_LASTS", SHORT_LOCK_LASTS)
    monkeypatch.setattr(
        "songmaker_cli.acestep_state.DOWNLOAD_LOCK_EXTEND_EVERY", SHORT_EXTEND_EVERY,
    )


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
    settle_the_real_servers_epoch(redis_url)

    async def scenario(first, second) -> list[bool]:
        return [
            await tick_locks(first).acquire(JOB_REAPER_LOCK_NAME) is not None,
            await tick_locks(second).acquire(JOB_REAPER_LOCK_NAME) is not None,
        ]

    assert _in_two_processes(redis_url, scenario) == [True, False]


def test_a_download_of_a_mode_runs_in_one_of_two_processes(redis_url: str) -> None:
    settle_the_real_servers_epoch(redis_url)

    async def scenario(first, second) -> str | None:
        async with single_flight_download(first, "sft", "job-1"):
            with pytest.raises(DownloadAlreadyRunning) as refused:
                await attempt_download_that_must_not_run(second, "sft", "job-2")
        return refused.value.job_id

    assert _in_two_processes(redis_url, scenario) == "job-1"


def test_the_worker_reserve_and_the_web_admission_cannot_both_win(redis_url: str) -> None:
    settle_the_real_servers_epoch(redis_url)

    async def scenario(worker, web) -> tuple[bool, bool, int]:
        reserved = await reserve_gpu_hold(worker, WORKER) is not None
        admitted = await admit_generation(web, WORKER)
        return reserved, admitted, await read_queue_depth(web, WORKER)

    assert _in_two_processes(redis_url, scenario) == (True, False, 0)


def test_the_web_admission_wins_against_a_later_worker_reserve(redis_url: str) -> None:
    settle_the_real_servers_epoch(redis_url)

    async def scenario(worker, web) -> tuple[bool, bool, int]:
        admitted = await admit_generation(web, WORKER)
        reserved = await reserve_gpu_hold(worker, WORKER) is not None
        return admitted, reserved, await read_queue_depth(web, WORKER)

    assert _in_two_processes(redis_url, scenario) == (True, False, 1)


def test_the_gpu_is_refused_to_both_sides_until_a_restart_is_settled(redis_url: str) -> None:
    settle_the_real_servers_epoch(redis_url)
    lose_everything(redis_url)

    async def scenario(worker, web) -> tuple[bool, bool, bool]:
        return (
            await gpu_hold_is_free(web, WORKER),
            await admit_generation(web, WORKER),
            await reserve_gpu_hold(worker, WORKER) is not None,
        )

    assert _in_two_processes(redis_url, scenario) == (False, False, False)

    settle_the_real_servers_epoch(redis_url)

    async def after_the_span(worker, web) -> tuple[bool, bool]:
        return await gpu_hold_is_free(web, WORKER), await admit_generation(web, WORKER)

    assert _in_two_processes(redis_url, after_the_span) == (True, True)


def test_a_label_whose_lock_is_free_reads_as_no_download_in_progress(redis_url: str) -> None:
    settle_the_real_servers_epoch(redis_url)

    async def scenario(crashed_holder, reader) -> str | None:
        await crashed_holder.set(download_key("sft"), "job-1")
        return await read_download_in_progress(reader, "sft")

    assert _in_two_processes(redis_url, scenario) is None


def test_a_download_longer_than_its_span_keeps_the_lock(
    redis_url: str, short_download_lock: None,
) -> None:
    settle_the_real_servers_epoch(redis_url)

    async def scenario(holder, other_process) -> str | None:
        async with single_flight_download(holder, "sft", "job-1"):
            await until_redis_has_passed(holder, 2 * SHORT_LOCK_LASTS)
            assert await download_locks(other_process).acquire("sft") is None
            return await read_download_in_progress(other_process, "sft")

    assert _in_two_processes(redis_url, scenario) == "job-1"


def test_a_download_whose_lock_ran_out_before_its_entry_leaves_no_label(
    redis_url: str, short_download_lock: None,
) -> None:
    settle_the_real_servers_epoch(redis_url)

    keys_written: list[str] = []

    class WriteRecordingRedis(RedisThatLosesItsFirstLock):
        async def set(self, name, value, *args, **kwargs):
            keys_written.append(name)
            return await super().set(name, value, *args, **kwargs)

    async def scenario() -> list[str]:
        holder = WriteRecordingRedis.from_url(redis_url)
        holder.when_lost = lambda: lose_everything(redis_url)
        try:
            with pytest.raises(DownloadLockLost):
                await attempt_download_that_must_not_run(holder, "sft", "job-1")
            return keys_written
        finally:
            await holder.aclose()

    assert asyncio.run(scenario()) == []


def test_a_download_whose_lock_was_lost_ends_and_leaves_the_new_holders_label(
    redis_url: str, short_download_lock: None,
) -> None:
    settle_the_real_servers_epoch(redis_url)

    async def scenario(first, new_holder) -> str | None:
        async def download_until_the_lock_is_lost() -> None:
            async with single_flight_download(first, "sft", "job-1"):
                lose_everything(redis_url)
                settle_the_real_servers_epoch(redis_url)
                assert await download_locks(new_holder).acquire("sft") is not None
                await new_holder.set(download_key("sft"), "job-2")
                async with asyncio.timeout(DOWNLOAD_LOST_WITHIN_SECONDS):
                    await asyncio.Event().wait()

        with pytest.raises(DownloadLockLost) as lost:
            await download_until_the_lock_is_lost()
        assert lost.value.mode == "sft"
        return await read_download_in_progress(new_holder, "sft")

    assert _in_two_processes(redis_url, scenario) == "job-2"
