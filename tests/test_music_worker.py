"""Tests for the music worker."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import songmaker_cli.music_worker as mw_mod


def _run(coro):
    return asyncio.run(coro)


def _mock_ctx():
    return {"redis": AsyncMock()}


def _mock_db_factory():
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)
    return mock_factory, mock_session


def test_generate_skips_completed_job() -> None:
    with (
        patch("songmaker_cli.music_worker.check_job_still_valid", return_value=False),
        patch("songmaker_cli.music_worker.run_generation_job") as mock_run,
    ):
        _run(mw_mod.generate(_mock_ctx(), "j1", "s1", "v1", 2, "u1"))

    mock_run.assert_not_called()


def test_generate_runs_queued_job() -> None:
    mock_mgr = MagicMock()
    mock_mgr.active_model = "sft"
    ctx = _mock_ctx()

    with (
        patch("songmaker_cli.music_worker.check_job_still_valid", return_value=True),
        patch("songmaker_cli.music_worker.run_generation_job") as mock_run,
        patch.object(mw_mod, "_acestep_manager", mock_mgr),
        patch("songmaker_cli.music_worker._audio_dir", return_value="audio"),
        patch("songmaker_cli.music_worker._data_dir", return_value="data"),
        patch("songmaker_cli.music_worker._get_db_factory", return_value=MagicMock()),
    ):
        _run(mw_mod.generate(ctx, "j1", "s1", "v1", 2, "u1"))

    mock_run.assert_called_once()
    mock_mgr.prepare_generate_mode.assert_called_once()


def test_generate_passes_seed() -> None:
    mock_mgr = MagicMock()
    mock_mgr.active_model = "sft"
    ctx = _mock_ctx()

    with (
        patch("songmaker_cli.music_worker.check_job_still_valid", return_value=True),
        patch("songmaker_cli.music_worker.run_generation_job") as mock_run,
        patch.object(mw_mod, "_acestep_manager", mock_mgr),
        patch("songmaker_cli.music_worker._audio_dir", return_value="audio"),
        patch("songmaker_cli.music_worker._data_dir", return_value="data"),
        patch("songmaker_cli.music_worker._get_db_factory", return_value=MagicMock()),
    ):
        _run(mw_mod.generate(ctx, "j1", "s1", "v1", 2, "u1", seed=42))

    assert mock_run.call_args.kwargs["seed"] == 42


def test_cleanup_stale_commits_on_recovery() -> None:
    mock_factory, mock_session = _mock_db_factory()
    mock_mgr = MagicMock()
    mock_mgr.active_model = "turbo"

    with (
        patch("songmaker_cli.music_worker._get_db_factory", return_value=mock_factory),
        patch.object(mw_mod, "_require_acestep_manager", return_value=mock_mgr),
        patch(
            "songmaker_cli.db.queries.recover_stale_jobs_by_age_and_type",
            return_value=2,
        ),
        patch("songmaker_cli.music_worker._publish_acestep_status", new_callable=AsyncMock),
    ):
        _run(mw_mod.cleanup_stale(_mock_ctx()))

    mock_session.commit.assert_called_once()


def test_cleanup_stale_no_commit_when_zero() -> None:
    mock_factory, mock_session = _mock_db_factory()
    mock_mgr = MagicMock()
    mock_mgr.active_model = "turbo"

    with (
        patch("songmaker_cli.music_worker._get_db_factory", return_value=mock_factory),
        patch.object(mw_mod, "_require_acestep_manager", return_value=mock_mgr),
        patch(
            "songmaker_cli.db.queries.recover_stale_jobs_by_age_and_type",
            return_value=0,
        ),
        patch("songmaker_cli.music_worker._publish_acestep_status", new_callable=AsyncMock),
    ):
        _run(mw_mod.cleanup_stale(_mock_ctx()))

    mock_session.commit.assert_not_called()


def test_on_startup_initializes_acestep() -> None:
    mock_factory, mock_session = _mock_db_factory()
    mock_mgr = MagicMock()
    mock_mgr.active_model = "sft"
    ctx = _mock_ctx()

    with (
        patch("songmaker_cli.music_worker._get_db_factory", return_value=mock_factory),
        patch("songmaker_cli.db.queries.recover_stale_jobs_by_type"),
        patch("songmaker_cli.acestep_manager.AceStepManager", return_value=mock_mgr),
        patch("songmaker_cli.music_worker._publish_acestep_status", new_callable=AsyncMock),
        patch("songmaker_cli.music_worker.common_startup", new_callable=AsyncMock),
    ):
        _run(mw_mod.on_startup(ctx))

    mock_mgr.ensure.assert_called_once()
    mock_mgr.refresh_cached_model.assert_called_once()


def test_on_startup_recovers_stale_generate_jobs() -> None:
    mock_factory, mock_session = _mock_db_factory()
    mock_mgr = MagicMock()
    mock_mgr.active_model = "sft"
    ctx = _mock_ctx()

    with (
        patch("songmaker_cli.music_worker._get_db_factory", return_value=mock_factory),
        patch(
            "songmaker_cli.db.queries.recover_stale_jobs_by_type",
        ) as mock_recover,
        patch("songmaker_cli.acestep_manager.AceStepManager", return_value=mock_mgr),
        patch("songmaker_cli.music_worker._publish_acestep_status", new_callable=AsyncMock),
        patch("songmaker_cli.music_worker.common_startup", new_callable=AsyncMock),
    ):
        _run(mw_mod.on_startup(ctx))

    mock_recover.assert_called_once_with(mock_session, "generate")
    mock_session.commit.assert_called_once()


def test_on_shutdown_stops_acestep() -> None:
    mock_mgr = MagicMock()
    original_mgr = mw_mod._acestep_manager
    mw_mod._acestep_manager = mock_mgr
    ctx = _mock_ctx()

    with patch("songmaker_cli.music_worker.common_shutdown", new_callable=AsyncMock):
        _run(mw_mod.on_shutdown(ctx))

    mock_mgr.stop.assert_called_once()
    mw_mod._acestep_manager = original_mgr


def test_on_shutdown_deletes_active_model_key() -> None:
    mock_mgr = MagicMock()
    original_mgr = mw_mod._acestep_manager
    mw_mod._acestep_manager = mock_mgr
    ctx = _mock_ctx()

    with patch("songmaker_cli.music_worker.common_shutdown", new_callable=AsyncMock):
        _run(mw_mod.on_shutdown(ctx))

    from songmaker_cli.constants import ACTIVE_MODEL_REDIS_KEY
    ctx["redis"].delete.assert_called_with(ACTIVE_MODEL_REDIS_KEY)
    mw_mod._acestep_manager = original_mgr


def _mock_httpx_response(data: dict, status_code: int = 200):
    resp = MagicMock()
    resp.json.return_value = data
    resp.status_code = status_code
    return resp


def test_reinitialize_acestep_success() -> None:
    mock_mgr = MagicMock()
    mock_mgr.active_model = "sft"
    ctx = _mock_ctx()

    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_httpx_response({"code": 200})
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.object(mw_mod, "_acestep_manager", mock_mgr),
        patch("httpx.AsyncClient", return_value=mock_client),
        patch("songmaker_cli.music_worker._publish_acestep_status", new_callable=AsyncMock),
    ):
        _run(mw_mod.reinitialize_acestep(ctx))

    mock_mgr.refresh_cached_model.assert_called_once()
    ctx["redis"].set.assert_called()


def test_reinitialize_acestep_failure() -> None:
    mock_mgr = MagicMock()
    ctx = _mock_ctx()

    mock_client = AsyncMock()
    mock_client.post.return_value = _mock_httpx_response({"code": 500})
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with pytest.raises(RuntimeError, match="reinitialize failed"):
        with (
            patch.object(mw_mod, "_acestep_manager", mock_mgr),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            _run(mw_mod.reinitialize_acestep(ctx))


def test_publish_acestep_status_online() -> None:
    import json

    redis = AsyncMock()
    health_data = {"data": {"loaded_model": "sft", "loaded_lm_model": "4B"}}
    stats_data = {"data": {"jobs": {"pending": 1}}}

    mock_client = AsyncMock()
    mock_client.get.side_effect = [
        _mock_httpx_response(health_data),
        _mock_httpx_response(stats_data),
    ]
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=mock_client):
        _run(mw_mod._publish_acestep_status(redis))

    redis.set.assert_called_once()
    stored = json.loads(redis.set.call_args[0][1])
    assert stored["online"] is True
    assert stored["model"] == "sft"


def test_publish_acestep_status_offline() -> None:
    import json

    redis = AsyncMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get.side_effect = OSError("refused")

    with patch("httpx.AsyncClient", return_value=mock_client):
        _run(mw_mod._publish_acestep_status(redis))

    redis.set.assert_called_once()
    stored = json.loads(redis.set.call_args[0][1])
    assert stored["online"] is False


def test_music_worker_settings_queue_name() -> None:
    from songmaker_cli.constants import ARQ_MUSIC_QUEUE_NAME
    from songmaker_cli.music_worker import MusicWorkerSettings
    assert MusicWorkerSettings.queue_name == ARQ_MUSIC_QUEUE_NAME


def test_music_worker_settings_has_cron() -> None:
    from songmaker_cli.music_worker import MusicWorkerSettings
    assert len(MusicWorkerSettings.cron_jobs) == 1


def test_music_worker_settings_functions() -> None:
    from songmaker_cli.music_worker import MusicWorkerSettings
    func_names = [f.__name__ for f in MusicWorkerSettings.functions]
    assert "generate" in func_names
    assert "reinitialize_acestep" in func_names
    assert "score" not in func_names
