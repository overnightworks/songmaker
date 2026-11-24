"""The workers' readiness file and lease families, and the readers of their rosters."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from logline.testing import configured
from tandem import StoreError

import songmaker_cli.arq_pool as arq_pool
from songmaker_cli.constants import WORKER_READINESS_FILE
from songmaker_cli.job_types import WorkerLivenessSignal
from songmaker_cli.music_worker import MusicWorker
from songmaker_cli.redis_client import create_async_redis
from songmaker_cli.scoring import subprocess_runner
from songmaker_cli.scoring_worker import ScoringWorker
from songmaker_cli.settings import Settings
from songmaker_cli.worker_liveness import (
    WORKER_KINDS,
    owner_leases,
    pid_one_start_ticks,
    read_kind_roster,
    worker_is_ready,
    worker_kind_leases,
    write_readiness_file,
)

OWNER_ID = "owner-of-this-start"
THIS_START_TICKS = "4242"
EARLIER_START_TICKS = "4141"
Observation = tuple[bool, set[str]]
"""Whether the worker reads ready, and who holds a lease of its kind."""


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


@pytest.mark.parametrize(
    ("worker_class", "kind"),
    [
        (MusicWorker, WorkerLivenessSignal.MUSIC),
        (ScoringWorker, WorkerLivenessSignal.SCORING),
    ],
    ids=["music", "scoring"],
)
def test_a_running_worker_is_ready_and_listed_and_is_neither_after_its_shutdown(
    restored_logging: None, redis_url: str, readiness_file: Path,
    monkeypatch: pytest.MonkeyPatch, worker_class, kind: WorkerLivenessSignal,
) -> None:
    monkeypatch.setattr(subprocess_runner, "_scorer_process", None)
    worker = worker_class(
        Settings(
            database_url="postgresql://example", redis_url=redis_url,
            session_secret="session-secret", songmaker_internal_token="internal-token",
        ),
        readiness_file=readiness_file,
    )
    worker.get_db_factory = MagicMock()

    async def observe_the_start_and_the_end() -> tuple[Observation, Observation]:
        reader = create_async_redis(redis_url)

        async def observation() -> Observation:
            ready = await worker_is_ready(
                owner_leases(reader), readiness_file, pid_one_start_ticks(),
            )
            roster = await worker_kind_leases(reader, kind).live()
            return ready, set(roster.holders)

        try:
            await worker.start()
            running = await observation()
            await worker.stop()
            return running, await observation()
        finally:
            await reader.aclose()

    running, ended = asyncio.run(observe_the_start_and_the_end())

    assert running == (True, {worker.owner_id})
    assert ended == (False, set())


def test_a_worker_writes_the_readiness_file_its_constructor_names_and_not_the_shared_one(
    restored_logging: None, redis_url: str, readiness_file: Path,
) -> None:
    worker = MusicWorker(
        Settings(
            database_url="postgresql://example", redis_url=redis_url,
            session_secret="session-secret", songmaker_internal_token="internal-token",
        ),
        readiness_file=readiness_file,
    )
    worker.get_db_factory = MagicMock()
    shared_file_before = WORKER_READINESS_FILE.stat() if WORKER_READINESS_FILE.exists() else None

    async def start_and_stop() -> None:
        await worker.start()
        await worker.stop()

    asyncio.run(start_and_stop())

    assert readiness_file.read_text().split()[0] == worker.owner_id
    assert (WORKER_READINESS_FILE.stat() if WORKER_READINESS_FILE.exists() else None) == (
        shared_file_before
    )


@pytest.fixture
def web_redis(redis_url: str, monkeypatch, fresh_settings: None) -> str:
    """The URL the web process's arq pool connects to."""
    monkeypatch.setenv("REDIS_URL", redis_url)
    return redis_url


@pytest.fixture(params=WORKER_KINDS, ids=lambda kind: kind.value)
def kind_and_health(request) -> tuple[WorkerLivenessSignal, Callable[[], Awaitable[bool]]]:
    """A worker kind and the question whether a worker of that kind is healthy."""
    health = {
        WorkerLivenessSignal.MUSIC: arq_pool.is_music_worker_healthy,
        WorkerLivenessSignal.SCORING: arq_pool.is_scoring_worker_healthy,
    }
    return request.param, health[request.param]


def test_a_live_holder_makes_the_worker_healthy_and_none_does_not(
    web_redis: str, kind_and_health,
) -> None:
    kind, is_healthy = kind_and_health

    async def healthy_without_and_with_a_holder() -> tuple[bool, bool]:
        pool = await arq_pool.init_arq_pool()
        try:
            without = await is_healthy()
            await worker_kind_leases(pool, kind).renew(OWNER_ID)
            return without, await is_healthy()
        finally:
            await arq_pool.close_arq_pool()

    assert asyncio.run(healthy_without_and_with_a_holder()) == (False, True)


def test_a_holder_of_the_owner_family_alone_does_not_make_the_worker_healthy(
    web_redis: str, kind_and_health,
) -> None:
    _, is_healthy = kind_and_health

    async def healthy_with_an_owner() -> bool:
        pool = await arq_pool.init_arq_pool()
        try:
            await owner_leases(pool).renew(OWNER_ID)
            return await is_healthy()
        finally:
            await arq_pool.close_arq_pool()

    assert asyncio.run(healthy_with_an_owner()) is False


def test_a_worker_whose_roster_cannot_be_read_is_not_healthy(
    web_redis: str, kind_and_health,
) -> None:
    kind, is_healthy = kind_and_health

    async def healthy_once_the_pool_is_closed() -> bool:
        await arq_pool.init_arq_pool()
        await worker_kind_leases(arq_pool.get_arq_pool(), kind).renew(OWNER_ID)
        await arq_pool.close_arq_pool()
        return await is_healthy()

    assert asyncio.run(healthy_once_the_pool_is_closed()) is False


def test_a_roster_that_cannot_be_read_reads_as_none() -> None:
    leases = MagicMock(live=AsyncMock(side_effect=StoreError("down")))

    assert asyncio.run(read_kind_roster(WorkerLivenessSignal.MUSIC, leases)) is None
