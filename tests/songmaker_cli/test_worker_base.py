"""Tests for the WorkerBase shared infrastructure class."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from redis.exceptions import RedisError

import songmaker_cli.worker_base as wb_mod
from songmaker_cli.db.models import Album, Generation, Song, Version
from songmaker_cli.worker_base import WorkerBase
from songmaker_cli.worker_liveness import owner_lease_key


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

LEASE_DEADLINE_SECONDS = 5.0


class _LeaseRedis:
    """The Redis calls a lease makes, over a dict; the renewals in `failing_sets` raise."""

    def __init__(self, *, failing_sets: frozenset[int] = frozenset(), drop_fails: bool = False):
        self.leases: dict[str, str] = {}
        self.sets = 0
        self.successful_sets = 0
        self._failing_sets = failing_sets
        self._drop_fails = drop_fails
        self.closed = False

    def set(self, key: str, value: str, ex: int) -> None:
        self.sets += 1
        if self.sets in self._failing_sets:
            raise RedisError("unreachable")
        self.successful_sets += 1
        self.leases[key] = value

    def delete(self, key: str) -> None:
        if self._drop_fails:
            raise RedisError("unreachable")
        self.leases.pop(key, None)

    def close(self) -> None:
        self.closed = True


def _worker_on(redis: _LeaseRedis, monkeypatch: pytest.MonkeyPatch) -> _DummyWorker:
    monkeypatch.setattr(wb_mod, "create_redis", lambda _url: redis)
    monkeypatch.setattr(wb_mod, "OWNER_LEASE_REFRESH_SECONDS", 0)
    monkeypatch.setattr("songmaker_cli.logging_config.configure_logging", lambda: None)
    worker = _DummyWorker()
    worker.get_db_factory = MagicMock()
    return worker


async def _until(condition) -> None:
    async with asyncio.timeout(LEASE_DEADLINE_SECONDS):
        while not condition():
            await asyncio.sleep(0)


def test_a_worker_holds_a_lease_from_its_start_until_its_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _LeaseRedis()
    worker = _worker_on(redis, monkeypatch)
    lease = owner_lease_key(worker.owner_id)

    async def start_and_stop() -> tuple[bool, bool, bool]:
        await worker.on_startup({})
        held_while_running = lease in redis.leases
        await worker.on_shutdown({})
        return held_while_running, lease in redis.leases, redis.closed

    assert _run(start_and_stop()) == (True, False, True)


def test_two_workers_hold_leases_of_their_own() -> None:
    assert _DummyWorker().owner_id != _DummyWorker().owner_id


def test_a_worker_leases_only_after_its_database_has_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _LeaseRedis()
    worker = _worker_on(redis, monkeypatch)
    leases_while_opening: list[dict[str, str]] = []
    worker.get_db_factory = lambda: leases_while_opening.append(dict(redis.leases))

    async def start_and_stop() -> None:
        await worker.on_startup({})
        await worker.on_shutdown({})

    _run(start_and_stop())

    assert leases_while_opening == [{}]


def test_a_lease_renewal_that_fails_is_tried_again(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _LeaseRedis(failing_sets=frozenset({2, 3}))
    worker = _worker_on(redis, monkeypatch)

    async def renewed_after_the_failures() -> int:
        await worker.on_startup({})
        await _until(lambda: redis.successful_sets >= 2)
        await worker.on_shutdown({})
        return redis.successful_sets

    assert _run(renewed_after_the_failures()) >= 2


def test_a_shutdown_that_cannot_drop_the_lease_still_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = _LeaseRedis(drop_fails=True)
    worker = _worker_on(redis, monkeypatch)

    async def start_and_stop() -> None:
        await worker.on_startup({})
        await worker.on_shutdown({})

    _run(start_and_stop())

    assert redis.closed


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
