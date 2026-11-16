"""Tests for the WorkerBase shared infrastructure class."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import logging
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from arq.connections import create_pool
from arq.worker import Worker, func
from logline.testing import configured
from support.redis_proxy import redis_proxy

from songmaker_cli.db.models import Album, Generation, Song, Version
from songmaker_cli.job_timing import OWNER_LEASE_REFRESH_SECONDS, OWNER_LEASE_TTL_SECONDS
from songmaker_cli.music_worker import MusicWorker
from songmaker_cli.redis_client import build_arq_redis_settings, create_async_redis
from songmaker_cli.scoring import subprocess_runner
from songmaker_cli.scoring_worker import ScoringWorker
from songmaker_cli.settings import Settings
from songmaker_cli.worker_base import WorkerBase
from songmaker_cli.worker_liveness import owner_leases

WORKER_SETTINGS_PATHS = (
    "songmaker_cli.music_worker.MusicWorkerSettings",
    "songmaker_cli.scoring_worker.ScoringWorkerSettings",
)
WORKER_STOP_BOUND_SECONDS = 10


def _run(coro):
    return asyncio.run(coro)


_ARQ_CTX = {"redis": MagicMock()}


class _DummyWorker(WorkerBase):
    service_name = "dummy-worker"
    job_types = ("dummy",)
    queue_name = "dummy_queue"
    max_jobs = 1


def _make_worker_with_db(mock_session: MagicMock) -> _DummyWorker:
    worker = _DummyWorker()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)
    worker.get_db_factory = MagicMock(return_value=mock_factory)
    return worker


# ── check_job_still_valid ─────────────────────────────────────────


def test_check_job_still_valid_returns_false_for_completed() -> None:
    mock_job = MagicMock()
    mock_job.status = "completed"
    worker = _make_worker_with_db(MagicMock())
    with patch("songmaker_cli.worker_base.get_job", return_value=mock_job):
        assert worker.check_job_still_valid("j1") is False


def test_check_job_still_valid_returns_false_for_missing() -> None:
    worker = _make_worker_with_db(MagicMock())
    with patch("songmaker_cli.worker_base.get_job", return_value=None):
        assert worker.check_job_still_valid("j1") is False


def test_check_job_still_valid_returns_true_for_queued() -> None:
    mock_job = MagicMock()
    mock_job.status = "queued"
    worker = _make_worker_with_db(MagicMock())
    with patch("songmaker_cli.worker_base.get_job", return_value=mock_job):
        assert worker.check_job_still_valid("j1") is True


def test_check_job_still_valid_returns_false_for_cancelled() -> None:
    mock_job = MagicMock()
    mock_job.status = "cancelled"
    worker = _make_worker_with_db(MagicMock())
    with patch("songmaker_cli.worker_base.get_job", return_value=mock_job):
        assert worker.check_job_still_valid("j1") is False


# ── get_db_factory caches per instance ────────────────────────────


def test_get_db_factory_caches() -> None:
    worker = _DummyWorker()
    mock_engine = MagicMock()
    mock_factory = MagicMock()
    mock_factory.kw = {"bind": mock_engine}

    with patch(
        "songmaker_cli.worker_base.init_db", return_value=mock_factory,
    ) as mock_init:
        result1 = worker.get_db_factory()
        result2 = worker.get_db_factory()

    assert result1 is result2
    mock_init.assert_called_once()


def test_get_db_factory_independent_per_instance() -> None:
    a = _DummyWorker()
    b = _DummyWorker()
    mock_factory = MagicMock()
    mock_factory.kw = {"bind": MagicMock()}

    with patch(
        "songmaker_cli.worker_base.init_db", return_value=mock_factory,
    ) as mock_init:
        a.get_db_factory()
        b.get_db_factory()

    assert mock_init.call_count == 2


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
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(subprocess_runner, "_scorer_process", None)
    worker = worker_class(settings=_settings_on(redis_url))
    worker.get_db_factory = MagicMock()

    async def start_log_and_stop() -> None:
        await worker.on_startup(_ARQ_CTX)
        logging.getLogger("songmaker_cli.probe").info("probe.ended")
        await worker.on_shutdown({})

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


def _worker_on(redis_url: str) -> _DummyWorker:
    worker = _DummyWorker(settings=_settings_on(redis_url))
    worker.get_db_factory = MagicMock()
    return worker


async def _held_leases(redis_url: str) -> set[str]:
    reader = create_async_redis(redis_url)
    try:
        return set((await owner_leases(reader).live()).holders)
    finally:
        await reader.aclose()


def test_a_worker_holds_a_lease_from_its_start_until_its_shutdown(
    restored_logging: None, redis_url: str,
) -> None:
    worker = _worker_on(redis_url)

    async def start_and_stop() -> tuple[set[str], set[str]]:
        await worker.on_startup(_ARQ_CTX)
        held_while_running = await _held_leases(redis_url)
        await worker.on_shutdown({})
        return held_while_running, await _held_leases(redis_url)

    assert _run(start_and_stop()) == ({worker.owner_id}, set())


def test_a_worker_whose_database_cannot_open_holds_no_lease(
    restored_logging: None, redis_url: str,
) -> None:
    worker = _worker_on(redis_url)
    worker.get_db_factory = MagicMock(side_effect=OSError("the database is down"))

    async def start_and_read_the_leases() -> set[str]:
        with pytest.raises(OSError, match="the database is down"):
            await worker.on_startup(_ARQ_CTX)
        return await _held_leases(redis_url)

    assert _run(start_and_read_the_leases()) == set()


def test_a_shutdown_that_cannot_end_the_lease_still_ends(
    restored_logging: None, redis_url: str,
) -> None:
    with redis_proxy(redis_url) as proxy:
        worker = _worker_on(proxy.url)

        async def start_and_stop_with_redis_cut() -> None:
            await worker.on_startup(_ARQ_CTX)
            proxy.cut()
            await worker.on_shutdown({})

        _run(start_and_stop_with_redis_cut())


def _arq_worker_of(settings_path: str, worker: _DummyWorker, redis_url: str) -> Worker:
    """An arq worker with the real settings class's Redis connection, aimed at ``redis_url``."""
    module_path, _, class_name = settings_path.rpartition(".")
    settings_class = getattr(importlib.import_module(module_path), class_name)
    server = build_arq_redis_settings(redis_url)
    return Worker(
        functions=[func(_answer, name="answer")],
        on_startup=worker.on_startup,
        redis_settings=replace(
            settings_class.redis_settings,
            host=server.host, port=server.port, database=server.database,
            username=server.username, password=server.password,
        ),
        queue_name=settings_class.queue_name,
        handle_signals=False,
        poll_delay=0.1,
    )


async def _answer(_ctx) -> str:
    return "answered"


async def _lease_generation(redis_url: str, owner_id: str) -> str | None:
    reader = create_async_redis(redis_url)
    try:
        return (await owner_leases(reader).state([owner_id]))[owner_id].generation
    finally:
        await reader.aclose()


@pytest.mark.parametrize("settings_path", WORKER_SETTINGS_PATHS)
def test_a_worker_rides_out_a_redis_outage_longer_than_its_lease_and_keeps_serving(
    restored_logging: None, redis_url: str, settings_path: str,
) -> None:
    with redis_proxy(redis_url) as proxy:
        worker = _worker_on(proxy.url)

        async def cut_restore_and_enqueue() -> tuple[str, bool, str | None, str | None]:
            arq_worker = _arq_worker_of(settings_path, worker, proxy.url)
            serving = asyncio.create_task(arq_worker.main())
            while (before := await _lease_generation(redis_url, worker.owner_id)) is None:
                await asyncio.sleep(0.1)
            proxy.refuse()
            await asyncio.sleep(OWNER_LEASE_TTL_SECONDS + 2)
            proxy.restore()
            client = await create_pool(
                build_arq_redis_settings(redis_url), default_queue_name=arq_worker.queue_name,
            )
            try:
                result = await (await client.enqueue_job("answer")).result(timeout=20)
                still_serving = not serving.done()
                async with asyncio.timeout(OWNER_LEASE_REFRESH_SECONDS * 2):
                    while (after := await _lease_generation(redis_url, worker.owner_id)) in (
                        None, before,
                    ):
                        await asyncio.sleep(0.2)
            finally:
                await client.aclose()
                serving.cancel()
                await asyncio.gather(serving, return_exceptions=True)
                await worker.on_shutdown({})
            return result, still_serving, before, after

        result, still_serving, before, after = _run(cut_restore_and_enqueue())

    assert (result, still_serving) == ("answered", True)
    assert after != before


@pytest.mark.parametrize("settings_path", WORKER_SETTINGS_PATHS)
def test_a_worker_stopped_during_a_redis_outage_ends_within_seconds(
    restored_logging: None, redis_url: str, settings_path: str,
) -> None:
    with redis_proxy(redis_url) as proxy:
        worker = _worker_on(proxy.url)

        async def stop_during_the_outage() -> float:
            arq_worker = _arq_worker_of(settings_path, worker, proxy.url)
            arq_worker.main_task = asyncio.create_task(arq_worker.main())
            while await _lease_generation(redis_url, worker.owner_id) is None:
                await asyncio.sleep(0.1)
            proxy.refuse()
            await asyncio.sleep(1)
            started = time.monotonic()
            arq_worker.main_task.cancel()
            await asyncio.gather(arq_worker.main_task, return_exceptions=True)
            async with asyncio.timeout(WORKER_STOP_BOUND_SECONDS):
                with contextlib.suppress(Exception):
                    await arq_worker.close()
            return time.monotonic() - started

        assert _run(stop_during_the_outage()) < WORKER_STOP_BOUND_SECONDS


def test_a_worker_that_never_started_shuts_down_without_a_lease() -> None:
    _run(_DummyWorker().on_shutdown({}))


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
