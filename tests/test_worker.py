"""Tests for the arq worker tasks."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import songmaker_cli.worker as worker_mod


def _run(coro):
    return asyncio.run(coro)


def _mock_ctx():
    ctx = {"redis": AsyncMock()}
    return ctx


# ── generate task ──────────────────────────────────────────────────


def test_generate_skips_completed_job() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    mock_job = MagicMock()
    mock_job.status = "completed"

    with (
        patch.object(worker_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker.get_job", return_value=mock_job),
        patch("songmaker_cli.worker.run_generation_job") as mock_run,
    ):
        _run(worker_mod.generate(_mock_ctx(), "j1", "s1", "v1", 2, "u1"))

    mock_run.assert_not_called()


def test_generate_skips_failed_job() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    mock_job = MagicMock()
    mock_job.status = "failed"

    with (
        patch.object(worker_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker.get_job", return_value=mock_job),
        patch("songmaker_cli.worker.run_generation_job") as mock_run,
    ):
        _run(worker_mod.generate(_mock_ctx(), "j1", "s1", "v1", 2, "u1"))

    mock_run.assert_not_called()


def test_generate_skips_missing_job() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    with (
        patch.object(worker_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker.get_job", return_value=None),
        patch("songmaker_cli.worker.run_generation_job") as mock_run,
    ):
        _run(worker_mod.generate(_mock_ctx(), "j1", "s1", "v1", 2, "u1"))

    mock_run.assert_not_called()


def test_generate_runs_queued_job() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    mock_job = MagicMock()
    mock_job.status = "queued"

    mock_mgr = MagicMock()
    mock_mgr.active_model = "sft"

    ctx = _mock_ctx()

    with (
        patch.object(worker_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker.get_job", return_value=mock_job),
        patch("songmaker_cli.worker.run_generation_job") as mock_run,
        patch.object(worker_mod, "_acestep_manager", mock_mgr),
        patch.object(worker_mod, "_audio_dir", return_value="audio"),
        patch.object(worker_mod, "_data_dir", return_value="data"),
    ):
        _run(worker_mod.generate(ctx, "j1", "s1", "v1", 2, "u1"))

    mock_run.assert_called_once()
    call_kwargs = mock_run.call_args
    assert call_kwargs[0][0] == "j1"
    assert call_kwargs[0][1] == "s1"
    mock_mgr.prepare_generate_mode.assert_called_once()


# ── score task ─────────────────────────────────────────────────────


def test_score_skips_completed_job() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    mock_job = MagicMock()
    mock_job.status = "completed"

    with (
        patch.object(worker_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker.get_job", return_value=mock_job),
        patch("songmaker_cli.worker.run_scoring_job") as mock_run,
    ):
        _run(worker_mod.score(_mock_ctx(), "j1", "g1", None))

    mock_run.assert_not_called()


def test_score_runs_queued_job() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    mock_job = MagicMock()
    mock_job.status = "queued"

    mock_mgr = MagicMock()

    with (
        patch.object(worker_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker.get_job", return_value=mock_job),
        patch("songmaker_cli.worker.run_scoring_job") as mock_run,
        patch.object(worker_mod, "_acestep_manager", mock_mgr),
        patch.object(worker_mod, "_audio_dir", return_value="audio"),
    ):
        _run(worker_mod.score(_mock_ctx(), "j1", "g1", ["silence"]))

    mock_run.assert_called_once()
    mock_mgr.prepare_score_mode.assert_called_once()


# ── cleanup_stale ──────────────────────────────────────────────────


def test_cleanup_stale_commits_on_recovery() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    with (
        patch.object(worker_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker.recover_stale_jobs_by_age", return_value=2),
    ):
        _run(worker_mod.cleanup_stale(_mock_ctx()))

    mock_session.commit.assert_called_once()


def test_cleanup_stale_no_commit_when_zero() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    with (
        patch.object(worker_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker.recover_stale_jobs_by_age", return_value=0),
    ):
        _run(worker_mod.cleanup_stale(_mock_ctx()))

    mock_session.commit.assert_not_called()


# ── on_startup ─────────────────────────────────────────────────────


def test_on_startup_recovers_jobs() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    mock_mgr = MagicMock()
    mock_mgr.active_model = "sft"
    ctx = _mock_ctx()

    with (
        patch.object(worker_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker.recover_stale_jobs") as mock_recover,
        patch("songmaker_cli.acestep_manager.AceStepManager", return_value=mock_mgr),
    ):
        _run(worker_mod.on_startup(ctx))

    mock_recover.assert_called_once()
    mock_session.commit.assert_called_once()
    mock_mgr.ensure.assert_called_once()


# ── on_shutdown ────────────────────────────────────────────────────


def test_on_shutdown_stops_manager() -> None:
    mock_mgr = MagicMock()
    original = worker_mod._acestep_manager
    worker_mod._acestep_manager = mock_mgr

    _run(worker_mod.on_shutdown(_mock_ctx()))

    mock_mgr.stop.assert_called_once()
    worker_mod._acestep_manager = original


def test_on_shutdown_no_manager() -> None:
    original = worker_mod._acestep_manager
    worker_mod._acestep_manager = None

    _run(worker_mod.on_shutdown(_mock_ctx()))

    worker_mod._acestep_manager = original


# ── WorkerSettings ─────────────────────────────────────────────────


def test_worker_settings_max_jobs() -> None:
    from songmaker_cli.worker import WorkerSettings
    assert WorkerSettings.max_jobs == 1


def test_worker_settings_has_cron() -> None:
    from songmaker_cli.worker import WorkerSettings
    assert len(WorkerSettings.cron_jobs) == 1
