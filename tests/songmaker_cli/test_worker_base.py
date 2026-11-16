"""Tests for the WorkerBase shared infrastructure class."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from support.redis_proxy import redis_proxy

from songmaker_cli.db.models import Album, Generation, Song, Version
from songmaker_cli.redis_client import create_async_redis
from songmaker_cli.settings import Settings
from songmaker_cli.worker_base import WorkerBase
from songmaker_cli.worker_liveness import owner_leases


def _run(coro):
    return asyncio.run(coro)


class _DummyWorker(WorkerBase):
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


# ── owner lease ───────────────────────────────────────────────────


def _worker_on(redis_url: str, monkeypatch: pytest.MonkeyPatch) -> _DummyWorker:
    monkeypatch.setattr("songmaker_cli.logging_config.configure_logging", lambda: None)
    worker = _DummyWorker(settings=Settings(
        database_url="postgresql://example", redis_url=redis_url,
        session_secret="session-secret", songmaker_internal_token="internal-token",
    ))
    worker.get_db_factory = MagicMock()
    return worker


async def _held_leases(redis_url: str) -> set[str]:
    reader = create_async_redis(redis_url)
    try:
        return set((await owner_leases(reader).live()).holders)
    finally:
        await reader.aclose()


def test_a_worker_holds_a_lease_from_its_start_until_its_shutdown(
    monkeypatch: pytest.MonkeyPatch, redis_url: str,
) -> None:
    worker = _worker_on(redis_url, monkeypatch)

    async def start_and_stop() -> tuple[set[str], set[str]]:
        await worker.on_startup({})
        held_while_running = await _held_leases(redis_url)
        await worker.on_shutdown({})
        return held_while_running, await _held_leases(redis_url)

    assert _run(start_and_stop()) == ({worker.owner_id}, set())


def test_a_worker_names_itself_on_its_jobs_with_the_generation_of_its_lease(
    monkeypatch: pytest.MonkeyPatch, redis_url: str,
) -> None:
    worker = _worker_on(redis_url, monkeypatch)

    async def read_the_lease_while_running() -> str | None:
        await worker.on_startup({})
        reader = create_async_redis(redis_url)
        try:
            return (await owner_leases(reader).state([worker.owner_id]))[
                worker.owner_id
            ].generation
        finally:
            await reader.aclose()
            await worker.on_shutdown({})

    generation = _run(read_the_lease_while_running())

    assert (worker.owner.owner_id, worker.owner.generation) == (worker.owner_id, generation)


def test_a_worker_whose_database_cannot_open_holds_no_lease(
    monkeypatch: pytest.MonkeyPatch, redis_url: str,
) -> None:
    worker = _worker_on(redis_url, monkeypatch)
    worker.get_db_factory = MagicMock(side_effect=OSError("the database is down"))

    async def start_and_read_the_leases() -> set[str]:
        with pytest.raises(OSError, match="the database is down"):
            await worker.on_startup({})
        return await _held_leases(redis_url)

    assert _run(start_and_read_the_leases()) == set()


def test_a_shutdown_that_cannot_end_the_lease_still_ends(
    monkeypatch: pytest.MonkeyPatch, redis_url: str,
) -> None:
    with redis_proxy(redis_url) as proxy:
        worker = _worker_on(proxy.url, monkeypatch)

        async def start_and_stop_with_redis_cut() -> None:
            await worker.on_startup({})
            proxy.cut()
            await worker.on_shutdown({})

        _run(start_and_stop_with_redis_cut())


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
