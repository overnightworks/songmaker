"""Tests for the arq worker tasks."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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

    with (
        patch.object(worker_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker.get_job", return_value=mock_job),
        patch("songmaker_cli.worker.run_scoring_job") as mock_run,
        patch.object(worker_mod, "_audio_dir", return_value="audio"),
    ):
        _run(worker_mod.score(_mock_ctx(), "j1", "g1", ["silence"]))

    mock_run.assert_called_once()


# ── cleanup_stale ──────────────────────────────────────────────────


def test_cleanup_stale_commits_on_recovery() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)
    mock_mgr = MagicMock()
    mock_mgr.active_model = "turbo"

    with (
        patch.object(worker_mod, "_get_db_factory", return_value=mock_factory),
        patch.object(worker_mod, "_require_acestep_manager", return_value=mock_mgr),
        patch("songmaker_cli.worker.recover_stale_jobs_by_age", return_value=2),
        patch("songmaker_cli.worker._publish_acestep_status", new_callable=AsyncMock),
    ):
        _run(worker_mod.cleanup_stale(_mock_ctx()))

    mock_session.commit.assert_called_once()


def test_cleanup_stale_no_commit_when_zero() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)
    mock_mgr = MagicMock()
    mock_mgr.active_model = "turbo"

    with (
        patch.object(worker_mod, "_get_db_factory", return_value=mock_factory),
        patch.object(worker_mod, "_require_acestep_manager", return_value=mock_mgr),
        patch("songmaker_cli.worker.recover_stale_jobs_by_age", return_value=0),
        patch("songmaker_cli.worker._publish_acestep_status", new_callable=AsyncMock),
    ):
        _run(worker_mod.cleanup_stale(_mock_ctx()))

    mock_session.commit.assert_not_called()


# ── on_startup ─────────────────────────────────────────────────────


def test_on_startup_warns_on_redis_url_mismatch() -> None:
    mock_mgr = MagicMock()
    mock_mgr.active_model = "sft"
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    mock_log = MagicMock()

    with (
        patch.object(worker_mod, "_IMPORT_TIME_REDIS_URL", "redis://localhost:6379/0"),
        patch.dict("os.environ", {"REDIS_URL": "redis://prod:6379/0"}),
        patch.object(worker_mod, "log", mock_log),
        patch.object(worker_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker.recover_stale_jobs"),
        patch("songmaker_cli.acestep_manager.AceStepManager", return_value=mock_mgr),
        patch("songmaker_cli.worker._publish_acestep_status", new_callable=AsyncMock),
    ):
        _run(worker_mod.on_startup(_mock_ctx()))

    warning_calls = [c for c in mock_log.warning.call_args_list if "redis://prod:6379/0" in str(c)]
    assert len(warning_calls) == 1


def test_on_startup_no_warning_when_redis_url_matches() -> None:
    mock_mgr = MagicMock()
    mock_mgr.active_model = "sft"
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    mock_log = MagicMock()

    with (
        patch.object(worker_mod, "_IMPORT_TIME_REDIS_URL", "redis://localhost:6379/0"),
        patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379/0"}),
        patch.object(worker_mod, "log", mock_log),
        patch.object(worker_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker.recover_stale_jobs"),
        patch("songmaker_cli.acestep_manager.AceStepManager", return_value=mock_mgr),
        patch("songmaker_cli.worker._publish_acestep_status", new_callable=AsyncMock),
    ):
        _run(worker_mod.on_startup(_mock_ctx()))

    warning_calls = [c for c in mock_log.warning.call_args_list if "REDIS_URL" in str(c)]
    assert len(warning_calls) == 0


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
        patch("songmaker_cli.worker._publish_acestep_status", new_callable=AsyncMock),
    ):
        _run(worker_mod.on_startup(ctx))

    mock_recover.assert_called_once()
    mock_session.commit.assert_called_once()
    mock_mgr.ensure.assert_called_once()


# ── on_shutdown ────────────────────────────────────────────────────


def test_on_shutdown_recovers_stale_and_stops_manager() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    mock_mgr = MagicMock()
    original_mgr = worker_mod._acestep_manager
    worker_mod._acestep_manager = mock_mgr

    with (
        patch.object(worker_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker.recover_stale_jobs", return_value=1) as mock_recover,
    ):
        _run(worker_mod.on_shutdown(_mock_ctx()))

    mock_recover.assert_called_once_with(mock_session)
    mock_session.commit.assert_called_once()
    mock_mgr.stop.assert_called_once()
    worker_mod._acestep_manager = original_mgr


def test_on_shutdown_no_manager() -> None:
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)

    original_mgr = worker_mod._acestep_manager
    worker_mod._acestep_manager = None

    with (
        patch.object(worker_mod, "_get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker.recover_stale_jobs", return_value=0),
    ):
        _run(worker_mod.on_shutdown(_mock_ctx()))

    mock_session.commit.assert_called_once()
    worker_mod._acestep_manager = original_mgr


# ── reinitialize_acestep ───────────────────────────────────────────


def _mock_urlopen_response(payload: bytes):
    cm = MagicMock()
    cm.__enter__ = MagicMock(
        return_value=MagicMock(read=MagicMock(return_value=payload)),
    )
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def test_reinitialize_acestep_success() -> None:
    import json

    mock_mgr = MagicMock()
    mock_mgr.active_model = "sft"
    ctx = _mock_ctx()

    cm = _mock_urlopen_response(json.dumps({"code": 200}).encode())

    with (
        patch.object(worker_mod, "_acestep_manager", mock_mgr),
        patch("urllib.request.urlopen", return_value=cm),
        patch("songmaker_cli.worker._publish_acestep_status", new_callable=AsyncMock),
    ):
        _run(worker_mod.reinitialize_acestep(ctx))

    mock_mgr.refresh_cached_model.assert_called_once()
    ctx["redis"].set.assert_called()


def test_reinitialize_acestep_failure() -> None:
    import json

    mock_mgr = MagicMock()
    ctx = _mock_ctx()

    cm = _mock_urlopen_response(json.dumps({"code": 500}).encode())

    with pytest.raises(RuntimeError, match="reinitialize failed"):
        with (
            patch.object(worker_mod, "_acestep_manager", mock_mgr),
            patch("urllib.request.urlopen", return_value=cm),
        ):
            _run(worker_mod.reinitialize_acestep(ctx))


# ── _publish_acestep_status ───────────────────────────────────────


def test_publish_acestep_status_online() -> None:
    import json

    redis = AsyncMock()
    health_data = {"data": {"loaded_model": "sft", "loaded_lm_model": "4B"}}
    stats_data = {"data": {"jobs": {"pending": 1}}}

    call_count = 0

    def fake_urlopen(req, timeout=None):
        nonlocal call_count
        data = health_data if call_count == 0 else stats_data
        call_count += 1
        return _mock_urlopen_response(json.dumps(data).encode())

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        _run(worker_mod._publish_acestep_status(redis))

    redis.set.assert_called_once()
    stored = json.loads(redis.set.call_args[0][1])
    assert stored["online"] is True
    assert stored["model"] == "sft"


def test_publish_acestep_status_offline() -> None:
    import json

    redis = AsyncMock()

    with patch("urllib.request.urlopen", side_effect=OSError("refused")):
        _run(worker_mod._publish_acestep_status(redis))

    redis.set.assert_called_once()
    stored = json.loads(redis.set.call_args[0][1])
    assert stored["online"] is False


# ── WorkerSettings ─────────────────────────────────────────────────


def test_worker_settings_max_jobs() -> None:
    from songmaker_cli.worker import WorkerSettings
    assert WorkerSettings.max_jobs == 1


def test_worker_settings_has_cron() -> None:
    from songmaker_cli.worker import WorkerSettings
    assert len(WorkerSettings.cron_jobs) == 1


def test_worker_settings_drain_timeout() -> None:
    from songmaker_cli.worker import DRAIN_TIMEOUT_SECONDS, WorkerSettings
    assert WorkerSettings.job_completion_wait == DRAIN_TIMEOUT_SECONDS
