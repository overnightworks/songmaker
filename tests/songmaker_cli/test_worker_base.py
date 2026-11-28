"""Tests for the WorkerBase shared infrastructure class."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Coroutine, Iterator
from pathlib import Path
from typing import NamedTuple
from unittest.mock import MagicMock, patch

import pytest
from logline.testing import configured
from support.redis_proxy import redis_proxy

from songmaker_cli.db.models import Album, Generation, Song, Version
from songmaker_cli.job_timing import OWNER_LEASE_REFRESH_SECONDS, OWNER_LEASE_TTL_SECONDS
from songmaker_cli.job_types import WorkerLivenessSignal
from songmaker_cli.music_worker import MusicWorker
from songmaker_cli.redis_client import create_async_redis
from songmaker_cli.scoring_worker import ScoringWorker
from songmaker_cli.settings import Settings
from songmaker_cli.worker_base import WorkerBase
from songmaker_cli.worker_liveness import owner_leases

WORKER_STOP_BOUND_SECONDS = 10


def _run(coro):
    return asyncio.run(coro)


class _DummyWorker(WorkerBase):
    service_name = "dummy-worker"
    job_types = ("dummy",)


class DatabaseEngine(NamedTuple):
    init_db: MagicMock
    engine: MagicMock


@pytest.fixture
def database_engine() -> Iterator[DatabaseEngine]:
    """The ``init_db`` the worker calls and its engine, to see whether the pool is disposed."""
    engine = MagicMock()
    with patch("songmaker_cli.worker_base.init_db") as init_db:
        init_db.return_value.kw = {"bind": engine}
        yield DatabaseEngine(init_db, engine)


# ── get_db_factory caches per instance ────────────────────────────


def test_get_db_factory_caches(database_engine: DatabaseEngine) -> None:
    worker = _DummyWorker()

    result1 = worker.get_db_factory()
    result2 = worker.get_db_factory()

    assert result1 is result2
    database_engine.init_db.assert_called_once()


def test_get_db_factory_independent_per_instance(database_engine: DatabaseEngine) -> None:
    a = _DummyWorker()
    b = _DummyWorker()

    a.get_db_factory()
    b.get_db_factory()

    assert database_engine.init_db.call_count == 2


def _settings_on(redis_url: str) -> Settings:
    return Settings(
        database_url="postgresql://example", redis_url=redis_url,
        session_secret="session-secret", songmaker_internal_token="internal-token",
    )


# ── logging ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("worker_class", "service"),
    [
        (MusicWorker, "songmaker-music-worker"),
        (ScoringWorker, "songmaker-scoring-worker"),
    ],
)
def test_a_worker_writes_its_lines_under_its_own_service_name(
    worker_class: type[WorkerBase],
    service: str,
    redis_url: str,
    readiness_file: Path,
    capsys: pytest.CaptureFixture[str],
    installed_scorer_restored: None,
) -> None:
    worker = worker_class(settings=_settings_on(redis_url), readiness_file=readiness_file)
    worker.get_db_factory = MagicMock()

    async def start_log_and_stop() -> None:
        await worker.start()
        logging.getLogger("songmaker_cli.probe").info("probe.ended")
        await worker.stop()

    with configured("restored-after-the-test"):
        _run(start_log_and_stop())

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {line["service"] for line in lines} == {service}
    assert "probe.ended" in {line["event"] for line in lines}


# ── owner lease ───────────────────────────────────────────────────


@pytest.fixture
def restored_logging() -> Iterator[None]:
    with configured("restored-after-the-test"):
        yield


def _worker_on(redis_url: str, readiness_file: Path) -> _DummyWorker:
    worker = _DummyWorker(settings=_settings_on(redis_url), readiness_file=readiness_file)
    worker.get_db_factory = MagicMock()
    return worker


async def _held_leases(redis_url: str) -> set[str]:
    reader = create_async_redis(redis_url)
    try:
        return set((await owner_leases(reader).live()).holders)
    finally:
        await reader.aclose()


def test_a_worker_holds_a_lease_from_its_start_until_its_shutdown(
    restored_logging: None, redis_url: str, readiness_file: Path,
) -> None:
    worker = _worker_on(redis_url, readiness_file)

    async def start_and_stop() -> tuple[set[str], set[str]]:
        await worker.start()
        held_while_running = await _held_leases(redis_url)
        await worker.stop()
        return held_while_running, await _held_leases(redis_url)

    assert _run(start_and_stop()) == ({worker.owner_id}, set())


def test_a_worker_names_itself_on_its_jobs_with_the_generation_of_its_lease(
    restored_logging: None, redis_url: str, readiness_file: Path,
) -> None:
    worker = _worker_on(redis_url, readiness_file)

    async def read_the_lease_while_running() -> str | None:
        await worker.start()
        reader = create_async_redis(redis_url)
        try:
            return (await owner_leases(reader).state([worker.owner_id]))[
                worker.owner_id
            ].generation
        finally:
            await reader.aclose()
            await worker.stop()

    generation = _run(read_the_lease_while_running())

    assert (worker.owner.owner_id, worker.owner.generation) == (worker.owner_id, generation)


class _ServingWorker(_DummyWorker):
    """A worker whose ``run`` serves what its test names."""

    def __init__(
        self, settings: Settings, readiness_file: Path,
        *servings: Callable[[], Coroutine[None, None, None]],
    ):
        super().__init__(settings, readiness_file=readiness_file)
        self._servings = servings

    def servings(self) -> tuple[Coroutine[None, None, None], ...]:
        return tuple(serving() for serving in self._servings)


def _serving_worker_on(redis_url: str, readiness_file: Path, *servings) -> _ServingWorker:
    worker = _ServingWorker(_settings_on(redis_url), readiness_file, *servings)
    worker.get_db_factory = MagicMock()
    return worker


def test_run_holds_the_lease_while_it_serves_and_ends_on_a_stop_signal_after_its_servings(
    restored_logging: None, send_stop_signal: Callable[[asyncio.Task[None]], bool],
    redis_url: str, readiness_file: Path,
) -> None:
    serving, held_while_stopping = asyncio.Event(), []

    async def serves_until_stopped() -> None:
        try:
            serving.set()
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            held_while_stopping.append(await _held_leases(redis_url))
            raise

    worker = _serving_worker_on(redis_url, readiness_file, serves_until_stopped)

    async def run_and_stop() -> tuple[set[str], set[str]]:
        running = asyncio.create_task(worker.run())
        await serving.wait()
        held_while_serving = await _held_leases(redis_url)
        assert send_stop_signal(running)
        async with asyncio.timeout(WORKER_STOP_BOUND_SECONDS):
            await running
        return held_while_serving, await _held_leases(redis_url)

    assert _run(run_and_stop()) == ({worker.owner_id}, set())
    assert held_while_stopping == [{worker.owner_id}]


def test_a_serving_that_fails_ends_the_others_and_run_with_its_error_and_releases_the_lease(
    restored_logging: None, stop_signal_handlers: None, redis_url: str, readiness_file: Path,
) -> None:
    other_was_cut = asyncio.Event()

    async def serves_until_cut() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            other_was_cut.set()
            raise

    async def fails_once_the_other_serves() -> None:
        await asyncio.sleep(0)
        raise RuntimeError("the serving failed")

    worker = _serving_worker_on(
        redis_url, readiness_file, serves_until_cut, fails_once_the_other_serves,
    )

    async def run_within_the_stop_bound() -> None:
        async with asyncio.timeout(WORKER_STOP_BOUND_SECONDS):
            await worker.run()

    async def run_until_it_fails() -> tuple[BaseExceptionGroup, set[str]]:
        with pytest.raises(ExceptionGroup) as raised:
            await run_within_the_stop_bound()
        return raised.value, await _held_leases(redis_url)

    failure, held = _run(run_until_it_fails())

    assert [str(error) for error in failure.exceptions] == ["the serving failed"]
    assert other_was_cut.is_set()
    assert held == set()


def test_a_worker_whose_database_cannot_open_holds_no_lease(
    restored_logging: None, redis_url: str, readiness_file: Path,
) -> None:
    worker = _worker_on(redis_url, readiness_file)
    worker.get_db_factory = MagicMock(side_effect=OSError("the database is down"))

    async def start_and_read_the_leases() -> set[str]:
        with pytest.raises(OSError, match="the database is down"):
            await worker.start()
        return await _held_leases(redis_url)

    assert _run(start_and_read_the_leases()) == set()


def test_a_worker_whose_signal_has_no_worker_kind_fails_its_start_and_holds_no_lease(
    restored_logging: None, redis_url: str, readiness_file: Path,
) -> None:
    worker = _worker_on(redis_url, readiness_file)
    worker.lease_kind = WorkerLivenessSignal.MODEL_EXECUTION

    async def start_and_read_the_leases() -> set[str]:
        with pytest.raises(KeyError):
            await worker.start()
        return await _held_leases(redis_url)

    assert _run(start_and_read_the_leases()) == set()


def test_a_shutdown_that_cannot_end_the_lease_still_ends(
    restored_logging: None, redis_url: str, readiness_file: Path,
) -> None:
    with redis_proxy(redis_url) as proxy:
        worker = _worker_on(proxy.url, readiness_file)

        async def start_and_stop_with_redis_cut() -> None:
            await worker.start()
            proxy.cut()
            await worker.stop()

        _run(start_and_stop_with_redis_cut())


async def _lease_generation(redis_url: str, owner_id: str) -> str | None:
    reader = create_async_redis(redis_url)
    try:
        return (await owner_leases(reader).state([owner_id]))[owner_id].generation
    finally:
        await reader.aclose()


class _QueueServingWorker(_DummyWorker):
    """A worker whose serving claims the rows put in its queue, as a claiming loop does."""

    def __init__(self, settings: Settings, readiness_file: Path) -> None:
        super().__init__(settings, readiness_file=readiness_file)
        self.queued_rows: list[str] = []
        self.claimed_rows: list[str] = []

    def servings(self) -> tuple[Coroutine[None, None, None], ...]:
        return (self._claim_queued_rows(),)

    async def _claim_queued_rows(self) -> None:
        while True:
            if self.queued_rows:
                self.claimed_rows.append(self.queued_rows.pop(0))
            await asyncio.sleep(0.1)


def _queue_serving_worker_on(redis_url: str, readiness_file: Path) -> _QueueServingWorker:
    return _QueueServingWorker(_settings_on(redis_url), readiness_file)


def test_a_worker_rides_out_a_redis_outage_longer_than_its_lease_and_keeps_serving(
    restored_logging: None, database_engine: DatabaseEngine,
    send_stop_signal: Callable[[asyncio.Task[None]], bool],
    redis_url: str, readiness_file: Path,
) -> None:
    with redis_proxy(redis_url) as proxy:
        worker = _queue_serving_worker_on(proxy.url, readiness_file)

        async def cut_restore_and_queue_a_row() -> tuple[bool, str | None, str | None, list[str]]:
            running = asyncio.create_task(worker.run())
            try:
                while (before := await _lease_generation(redis_url, worker.owner_id)) is None:
                    await asyncio.sleep(0.1)
                proxy.refuse()
                await asyncio.sleep(OWNER_LEASE_TTL_SECONDS + 2)
                proxy.restore()
                worker.queued_rows.append("row-after-the-outage")
                async with asyncio.timeout(OWNER_LEASE_REFRESH_SECONDS * 2):
                    while (after := await _lease_generation(redis_url, worker.owner_id)) in (
                        None, before,
                    ):
                        await asyncio.sleep(0.2)
                    while not worker.claimed_rows:
                        await asyncio.sleep(0.1)
                return not running.done(), before, after, worker.claimed_rows
            finally:
                send_stop_signal(running)
                await asyncio.gather(running, return_exceptions=True)

        still_serving, before, after, claimed = _run(cut_restore_and_queue_a_row())

    assert (still_serving, claimed) == (True, ["row-after-the-outage"])
    assert after != before


def test_a_worker_stopped_during_a_redis_outage_ends_within_seconds_with_its_database_pool_disposed(
    restored_logging: None, database_engine: DatabaseEngine,
    send_stop_signal: Callable[[asyncio.Task[None]], bool],
    redis_url: str, readiness_file: Path,
) -> None:
    with redis_proxy(redis_url) as proxy:
        worker = _queue_serving_worker_on(proxy.url, readiness_file)

        async def stop_during_the_outage() -> float:
            running = asyncio.create_task(worker.run())
            while await _lease_generation(redis_url, worker.owner_id) is None:
                await asyncio.sleep(0.1)
            proxy.refuse()
            await asyncio.sleep(1)
            started = time.monotonic()
            assert send_stop_signal(running), "run() ended on its own during the outage"
            async with asyncio.timeout(WORKER_STOP_BOUND_SECONDS):
                await running
            return time.monotonic() - started

        assert _run(stop_during_the_outage()) < WORKER_STOP_BOUND_SECONDS
        database_engine.engine.dispose.assert_called_once_with()


def test_a_worker_that_never_started_shuts_down_without_a_lease() -> None:
    _run(_DummyWorker().stop())


# ── audit_orphaned_files ──────────────────────────────────────────


def test_audit_reports_only_files_no_take_owns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, pg_factory,
) -> None:
    with pg_factory() as session:
        session.add(Album(id="u1", title="Album", artist="Artist"))
        session.add(Song(id="s1", title="Song", album_id="u1", track_number=1, slug="song"))
        session.add(Version(id="v1", song_id="s1", version_number=1, lyrics="la", prompt="rock"))
        session.add(Generation(
            id="g1", song_id="s1", version_id="v1", generation_number=1,
            mp3_path="u1/g1.mp3", wav_path="u1/g1.wav",
        ))
        session.commit()
    audio_dir = tmp_path / "audio"
    (audio_dir / "u1").mkdir(parents=True)
    names = (
        "g1.mp3", "g1.wav", "g1.raw.wav",
        "g1.pre-remaster.wav", "g1.pre-remaster.mp3", "g9.raw.wav",
    )
    for name in names:
        (audio_dir / "u1" / name).write_bytes(b"fake")
    worker = _DummyWorker()
    worker.audio_dir = lambda: audio_dir
    worker.get_db_factory = lambda: pg_factory

    with caplog.at_level(logging.WARNING):
        worker.audit_orphaned_files()

    reported = caplog.records[-1].getMessage()
    assert "g9.raw.wav" in reported
    assert "g1." not in reported
