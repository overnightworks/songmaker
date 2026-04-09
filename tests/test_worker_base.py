"""Tests for the WorkerBase shared infrastructure class."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import songmaker_cli.worker_base as wb_mod
from songmaker_cli.worker_base import WorkerBase


def _run(coro):
    return asyncio.run(coro)


class _DummyWorker(WorkerBase):
    job_type = "dummy"
    recovery_lock_key = "test:lock:dummy"
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


# ── on_startup ────────────────────────────────────────────────────


# ── on_shutdown ───────────────────────────────────────────────────


def test_on_shutdown_recovers_jobs() -> None:
    mock_session = MagicMock()
    worker = _make_worker_with_db(mock_session)

    redis = AsyncMock()
    with patch(
        "songmaker_cli.db.queries.recover_stale_jobs_by_type", return_value=2,
    ) as mock_recover:
        _run(worker.on_shutdown({"redis": redis}))

    mock_recover.assert_called_once_with(mock_session, "dummy")
    mock_session.commit.assert_called_once()


def test_on_shutdown_skips_when_lock_held() -> None:
    worker = _DummyWorker()
    worker.get_db_factory = MagicMock()  # not called when lock is held

    redis = AsyncMock()
    redis.set = AsyncMock(return_value=False)

    with patch(
        "songmaker_cli.db.queries.recover_stale_jobs_by_type",
    ) as mock_recover:
        _run(worker.on_shutdown({"redis": redis}))

    mock_recover.assert_not_called()


# ── _recover_on_startup ───────────────────────────────────────────


def test_recover_on_startup_acquires_lock_and_recovers() -> None:
    mock_session = MagicMock()
    worker = _make_worker_with_db(mock_session)

    ctx = {"redis": AsyncMock()}
    with patch(
        "songmaker_cli.db.queries.recover_stale_jobs_by_type", return_value=3,
    ) as mock_recover:
        result = _run(worker._recover_on_startup(ctx))

    assert result == 3
    mock_recover.assert_called_once_with(mock_session, "dummy")
    mock_session.commit.assert_called_once()
    ctx["redis"].delete.assert_called_once_with("test:lock:dummy")


def test_recover_on_startup_skips_when_lock_held() -> None:
    worker = _DummyWorker()
    worker.get_db_factory = MagicMock()  # not called when lock is held

    ctx = {"redis": AsyncMock()}
    ctx["redis"].set = AsyncMock(return_value=False)

    with patch(
        "songmaker_cli.db.queries.recover_stale_jobs_by_type",
    ) as mock_recover:
        result = _run(worker._recover_on_startup(ctx))

    assert result == 0
    mock_recover.assert_not_called()


def test_recover_on_startup_releases_lock_on_error() -> None:
    worker = _DummyWorker()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(
        side_effect=RuntimeError("db error"),
    )
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)
    worker.get_db_factory = MagicMock(return_value=mock_factory)

    ctx = {"redis": AsyncMock()}

    with patch("songmaker_cli.db.queries.recover_stale_jobs_by_type"):
        try:
            _run(worker._recover_on_startup(ctx))
        except RuntimeError:
            pass

    ctx["redis"].delete.assert_called_once_with("test:lock:dummy")


# ── cleanup_stale_cron ────────────────────────────────────────────


def test_cleanup_stale_cron_commits_on_recovery() -> None:
    mock_session = MagicMock()
    worker = _make_worker_with_db(mock_session)

    with patch(
        "songmaker_cli.db.queries.recover_stale_jobs_by_age_and_type",
        return_value=2,
    ) as mock_recover:
        result = _run(worker.cleanup_stale_cron({"redis": AsyncMock()}))

    assert result == 2
    mock_recover.assert_called_once_with(mock_session, "dummy")
    mock_session.commit.assert_called_once()


def test_cleanup_stale_cron_no_commit_when_zero() -> None:
    mock_session = MagicMock()
    worker = _make_worker_with_db(mock_session)

    with patch(
        "songmaker_cli.db.queries.recover_stale_jobs_by_age_and_type",
        return_value=0,
    ):
        result = _run(worker.cleanup_stale_cron({"redis": AsyncMock()}))

    assert result == 0
    mock_session.commit.assert_not_called()


# ── module-level helpers ──────────────────────────────────────────


def test_build_redis_settings() -> None:
    settings = wb_mod.build_redis_settings()
    assert settings is not None
