"""Tests for the music worker."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import songmaker_cli.music_worker as mw_mod


def _run(coro):
    return asyncio.run(coro)


def _mock_ctx():
    return {"redis": AsyncMock()}


def test_generate_skips_completed_job() -> None:
    with (
        patch("songmaker_cli.music_worker.check_job_still_valid", return_value=False),
        patch("songmaker_cli.music_worker.run_generation_job", new_callable=AsyncMock) as mock_run,
    ):
        _run(mw_mod.generate(
            _mock_ctx(), "j1", "s1", "v1", 2, "u1", None, "sft",
        ))

    mock_run.assert_not_called()


def test_generate_runs_queued_job() -> None:
    ctx = _mock_ctx()
    with (
        patch("songmaker_cli.music_worker.check_job_still_valid", return_value=True),
        patch("songmaker_cli.music_worker.run_generation_job", new_callable=AsyncMock) as mock_run,
        patch("songmaker_cli.music_worker._audio_dir", return_value="audio"),
        patch("songmaker_cli.music_worker._data_dir", return_value="data"),
        patch("songmaker_cli.music_worker._get_db_factory", return_value=MagicMock()),
    ):
        _run(mw_mod.generate(ctx, "j1", "s1", "v1", 2, "u1", None, "sft"))

    mock_run.assert_awaited_once()
    kwargs = mock_run.await_args.kwargs
    assert kwargs["redis"] is ctx["redis"]


def test_generate_passes_seed_and_target_model() -> None:
    ctx = _mock_ctx()
    with (
        patch("songmaker_cli.music_worker.check_job_still_valid", return_value=True),
        patch("songmaker_cli.music_worker.run_generation_job", new_callable=AsyncMock) as mock_run,
        patch("songmaker_cli.music_worker._audio_dir", return_value="audio"),
        patch("songmaker_cli.music_worker._data_dir", return_value="data"),
        patch("songmaker_cli.music_worker._get_db_factory", return_value=MagicMock()),
    ):
        _run(mw_mod.generate(
            ctx, "j1", "s1", "v1", 2, "u1", 42, "xl-sft",
        ))

    kwargs = mock_run.await_args.kwargs
    assert kwargs["seed"] == 42
    assert kwargs["target_model"] == "xl-sft"


def test_generate_passes_repaint_params() -> None:
    ctx = _mock_ctx()
    repaint = {"src_wav_path": "/x.wav", "repainting_start": 0.0, "repainting_end": 1.0}
    with (
        patch("songmaker_cli.music_worker.check_job_still_valid", return_value=True),
        patch("songmaker_cli.music_worker.run_generation_job", new_callable=AsyncMock) as mock_run,
        patch("songmaker_cli.music_worker._audio_dir", return_value="audio"),
        patch("songmaker_cli.music_worker._data_dir", return_value="data"),
        patch("songmaker_cli.music_worker._get_db_factory", return_value=MagicMock()),
    ):
        _run(mw_mod.generate(
            ctx, "j1", "s1", "v1", 1, "u1", None, "sft", repaint_params=repaint,
        ))

    kwargs = mock_run.await_args.kwargs
    assert kwargs["repaint_params"] == repaint


def test_cleanup_stale_calls_base_cleanup_and_orphan_audit() -> None:
    with (
        patch.object(mw_mod, "_base_cleanup", new_callable=AsyncMock) as mock_base,
        patch.object(mw_mod, "audit_orphaned_files") as mock_audit,
        patch("songmaker_cli.cleanup.run_cleanup_expired") as mock_expired,
        patch.object(mw_mod, "_get_db_factory", return_value=MagicMock()),
        patch.object(mw_mod, "_audio_dir", return_value="audio"),
    ):
        ctx = _mock_ctx()
        _run(mw_mod.cleanup_stale(ctx))

    mock_base.assert_called_once_with(ctx)
    mock_audit.assert_called_once()
    mock_expired.assert_called_once()


def test_on_startup_calls_recover_on_startup() -> None:
    ctx = _mock_ctx()
    with (
        patch(
            "songmaker_cli.music_worker.recover_on_startup", new_callable=AsyncMock,
        ) as mock_recover,
        patch("songmaker_cli.music_worker.common_startup", new_callable=AsyncMock),
    ):
        _run(mw_mod.on_startup(ctx))

    from songmaker_cli.constants import RECOVERY_LOCK_MUSIC_KEY
    mock_recover.assert_called_once_with(ctx, RECOVERY_LOCK_MUSIC_KEY, "generate")


def test_on_shutdown_calls_common_shutdown() -> None:
    ctx = _mock_ctx()
    with patch(
        "songmaker_cli.music_worker.common_shutdown", new_callable=AsyncMock,
    ) as mock_shutdown:
        _run(mw_mod.on_shutdown(ctx))

    from songmaker_cli.constants import RECOVERY_LOCK_MUSIC_KEY
    mock_shutdown.assert_called_once_with(RECOVERY_LOCK_MUSIC_KEY, "generate", ctx["redis"])


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
    assert "load_model_on_worker" in func_names
    assert "download_model_on_worker" in func_names
    assert len(MusicWorkerSettings.functions) == 3
