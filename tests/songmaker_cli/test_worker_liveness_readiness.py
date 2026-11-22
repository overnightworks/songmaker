"""The music worker's readiness file and lease family, and the readers of its roster."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from logline.testing import configured
from tandem import StoreError

import songmaker_cli.arq_pool as arq_pool
from songmaker_cli.music_worker import MusicWorker
from songmaker_cli.redis_client import create_async_redis
from songmaker_cli.settings import Settings
from songmaker_cli.worker_liveness import (
    MUSIC_WORKER_KIND,
    owner_leases,
    pid_one_start_ticks,
    read_music_roster,
    worker_is_ready,
    worker_kind_leases,
    write_readiness_file,
)

OWNER_ID = "owner-of-this-start"
THIS_START_TICKS = "4242"
EARLIER_START_TICKS = "4141"
ARQ_CONTEXT = {"redis": MagicMock()}
Observation = tuple[bool, set[str]]
"""Whether the worker reads ready, and who holds a music-worker lease."""


@pytest.fixture
def restored_logging() -> Iterator[None]:
    with configured("restored-after-the-test"):
        yield


@pytest.fixture
def readiness_file(tmp_path: Path) -> Path:
    return tmp_path / "readiness"


def _stat_line(command_name: str, start_ticks: str) -> str:
    fields_between_state_and_start_ticks = ["0"] * 18
    return " ".join(["1", f"({command_name})", "S", *fields_between_state_and_start_ticks,
                     start_ticks, "0"])


def test_pid_one_start_ticks_read_field_22_whatever_the_command_name_holds(
    tmp_path: Path,
) -> None:
    stat_file = tmp_path / "stat"
    stat_file.write_text(_stat_line("arq (worker) 1", "987654"))

    assert pid_one_start_ticks(stat_file) == "987654"


def test_pid_one_has_start_ticks_on_this_machine() -> None:
    assert pid_one_start_ticks().isdigit()


def test_the_readiness_file_names_the_owner_and_the_start_ticks(readiness_file: Path) -> None:
    write_readiness_file(readiness_file, OWNER_ID, THIS_START_TICKS)

    assert readiness_file.read_text().split() == [OWNER_ID, THIS_START_TICKS]


def test_a_second_write_replaces_the_first_and_leaves_nothing_beside_it(
    readiness_file: Path,
) -> None:
    write_readiness_file(readiness_file, "earlier-owner", EARLIER_START_TICKS)
    write_readiness_file(readiness_file, OWNER_ID, THIS_START_TICKS)

    assert readiness_file.read_text().split() == [OWNER_ID, THIS_START_TICKS]
    assert list(readiness_file.parent.iterdir()) == [readiness_file]


@pytest.mark.parametrize(
    ("ticks_in_file", "lease_is_live", "ready"),
    [
        (EARLIER_START_TICKS, True, False),
        (THIS_START_TICKS, True, True),
        (THIS_START_TICKS, False, False),
    ],
    ids=["other ticks, live lease", "equal ticks, live lease", "equal ticks, no lease"],
)
def test_a_worker_is_ready_only_with_this_starts_ticks_and_a_live_owner_lease(
    redis_url: str, readiness_file: Path, ticks_in_file: str, lease_is_live: bool, ready: bool,
) -> None:
    write_readiness_file(readiness_file, OWNER_ID, ticks_in_file)

    async def read_readiness() -> bool:
        redis = create_async_redis(redis_url)
        try:
            leases = owner_leases(redis)
            if lease_is_live:
                await leases.renew(OWNER_ID)
            return await worker_is_ready(leases, readiness_file, THIS_START_TICKS)
        finally:
            await redis.aclose()

    assert asyncio.run(read_readiness()) is ready


def test_a_worker_without_a_readiness_file_is_not_ready(
    redis_url: str, readiness_file: Path,
) -> None:
    async def read_readiness() -> bool:
        redis = create_async_redis(redis_url)
        try:
            return await worker_is_ready(owner_leases(redis), readiness_file, THIS_START_TICKS)
        finally:
            await redis.aclose()

    assert asyncio.run(read_readiness()) is False


def test_a_running_music_worker_is_ready_and_listed_and_is_neither_after_its_shutdown(
    restored_logging: None, redis_url: str, readiness_file: Path, monkeypatch,
) -> None:
    monkeypatch.setattr("songmaker_cli.music_worker.MUSIC_WORKER_READINESS_FILE", readiness_file)
    worker = MusicWorker(Settings(
        database_url="postgresql://example", redis_url=redis_url,
        session_secret="session-secret", songmaker_internal_token="internal-token",
    ))
    worker.get_db_factory = MagicMock()
    worker.start_serving = MagicMock()
    worker.serve_queued_jobs = MagicMock()

    async def observe_the_start_and_the_end() -> tuple[Observation, Observation]:
        reader = create_async_redis(redis_url)

        async def observation() -> Observation:
            ready = await worker_is_ready(
                owner_leases(reader), readiness_file, pid_one_start_ticks(),
            )
            roster = await worker_kind_leases(reader, MUSIC_WORKER_KIND).live()
            return ready, set(roster.holders)

        try:
            await worker.on_startup(ARQ_CONTEXT)
            running = await observation()
            await worker.on_shutdown({})
            return running, await observation()
        finally:
            await reader.aclose()

    running, ended = asyncio.run(observe_the_start_and_the_end())

    assert running == (True, {worker.owner_id})
    assert ended == (False, set())


def _arq_pool_on(redis_url: str) -> None:
    arq_pool._pool = create_async_redis(redis_url)


@pytest.fixture
def restored_arq_pool() -> Iterator[None]:
    saved = arq_pool._pool
    yield
    arq_pool._pool = saved


def test_a_live_music_holder_makes_the_worker_healthy_and_none_does_not(
    redis_url: str, restored_arq_pool: None,
) -> None:
    async def healthy_without_and_with_a_holder() -> tuple[bool, bool]:
        _arq_pool_on(redis_url)
        try:
            without = await arq_pool.is_music_worker_healthy()
            await worker_kind_leases(arq_pool.get_arq_pool(), MUSIC_WORKER_KIND).renew(OWNER_ID)
            return without, await arq_pool.is_music_worker_healthy()
        finally:
            await arq_pool.close_arq_pool()

    assert asyncio.run(healthy_without_and_with_a_holder()) == (False, True)


def test_a_holder_of_the_owner_family_alone_does_not_make_the_worker_healthy(
    redis_url: str, restored_arq_pool: None,
) -> None:
    async def healthy_with_an_owner() -> bool:
        _arq_pool_on(redis_url)
        try:
            await owner_leases(arq_pool.get_arq_pool()).renew(OWNER_ID)
            return await arq_pool.is_music_worker_healthy()
        finally:
            await arq_pool.close_arq_pool()

    assert asyncio.run(healthy_with_an_owner()) is False


def test_a_worker_whose_roster_cannot_be_read_is_not_healthy(restored_arq_pool: None) -> None:
    arq_pool._pool = MagicMock(evalsha=AsyncMock(side_effect=StoreError("down")))

    assert asyncio.run(arq_pool.is_music_worker_healthy()) is False


def test_a_roster_that_cannot_be_read_reads_as_none() -> None:
    leases = MagicMock(live=AsyncMock(side_effect=StoreError("down")))

    assert asyncio.run(read_music_roster(leases)) is None
