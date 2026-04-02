"""Tests for the legacy combined worker shim."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import songmaker_cli.worker as worker_mod


def _run(coro):
    return asyncio.run(coro)


def _mock_ctx():
    ctx = {"redis": AsyncMock()}
    return ctx


def test_worker_settings_max_jobs() -> None:
    from songmaker_cli.worker import WorkerSettings
    assert WorkerSettings.max_jobs == 1


def test_worker_settings_has_cron() -> None:
    from songmaker_cli.worker import WorkerSettings
    assert len(WorkerSettings.cron_jobs) == 2


def test_worker_settings_drain_timeout() -> None:
    from songmaker_cli.worker import DRAIN_TIMEOUT_SECONDS, WorkerSettings
    assert WorkerSettings.job_completion_wait == DRAIN_TIMEOUT_SECONDS


def test_worker_settings_has_all_functions() -> None:
    from songmaker_cli.worker import WorkerSettings
    func_names = [f.__name__ for f in WorkerSettings.functions]
    assert "generate" in func_names
    assert "score" in func_names
    assert "reinitialize_acestep" in func_names


def test_on_startup_logs_deprecation_warning() -> None:
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
        patch("songmaker_cli.worker_base._get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker._get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.worker.recover_stale_jobs"),
        patch("songmaker_cli.acestep_manager.AceStepManager", return_value=mock_mgr),
        patch("songmaker_cli.music_worker._publish_acestep_status", new_callable=AsyncMock),
    ):
        _run(worker_mod.on_startup(_mock_ctx()))

    deprecation_calls = [
        c for c in mock_log.warning.call_args_list
        if "legacy combined worker" in str(c)
    ]
    assert len(deprecation_calls) == 1
