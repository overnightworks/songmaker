"""Tests for the music worker."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import songmaker_cli.music_worker as mw_mod
from songmaker_cli.music_worker import MusicWorker


def _run(coro):
    return asyncio.run(coro)


def _mock_ctx():
    return {"redis": AsyncMock()}


def _make_worker() -> MusicWorker:
    """Fresh worker with DB / dirs / job-validity stubbed."""
    worker = MusicWorker()
    worker.check_job_still_valid = MagicMock(return_value=True)
    worker.audio_dir = MagicMock(return_value="audio")
    worker.data_dir = MagicMock(return_value="data")
    worker.get_db_factory = MagicMock(return_value=MagicMock())
    return worker


def test_generate_skips_completed_job() -> None:
    worker = _make_worker()
    worker.check_job_still_valid = MagicMock(return_value=False)

    with patch(
        "songmaker_cli.music_worker.run_generation_job", new_callable=AsyncMock,
    ) as mock_run:
        _run(worker.generate(_mock_ctx(), "j1", "s1", "v1", 2, "u1", None, "sft"))

    mock_run.assert_not_called()


def test_generate_runs_queued_job() -> None:
    worker = _make_worker()
    ctx = _mock_ctx()
    with patch(
        "songmaker_cli.music_worker.run_generation_job", new_callable=AsyncMock,
    ) as mock_run:
        _run(worker.generate(ctx, "j1", "s1", "v1", 2, "u1", None, "sft"))

    mock_run.assert_awaited_once()
    kwargs = mock_run.await_args.kwargs
    assert kwargs["redis"] is ctx["redis"]


def test_generate_passes_seed_and_target_model() -> None:
    worker = _make_worker()
    with patch(
        "songmaker_cli.music_worker.run_generation_job", new_callable=AsyncMock,
    ) as mock_run:
        _run(worker.generate(
            _mock_ctx(), "j1", "s1", "v1", 2, "u1", 42, "xl-sft",
        ))

    kwargs = mock_run.await_args.kwargs
    assert kwargs["seed"] == 42
    assert kwargs["target_model"] == "xl-sft"


def test_generate_passes_repaint_params() -> None:
    from songmaker_cli.api_models import RepaintTaskParams

    worker = _make_worker()
    repaint = {
        "src_wav_path": "/x.wav",
        "src_generation_id": "g0",
        "repainting_start": 0.0,
        "repainting_end": 1.0,
        "lyrics": "la",
        "prompt": "rock",
    }
    with patch(
        "songmaker_cli.music_worker.run_generation_job", new_callable=AsyncMock,
    ) as mock_run:
        _run(worker.generate(
            _mock_ctx(), "j1", "s1", "v1", 1, "u1", None, "sft", repaint_params=repaint,
        ))

    kwargs = mock_run.await_args.kwargs
    assert isinstance(kwargs["repaint_params"], RepaintTaskParams)
    assert kwargs["repaint_params"].src_wav_path == "/x.wav"
    assert kwargs["repaint_params"].repainting_end == 1.0


def test_cleanup_stale_calls_base_cleanup_and_orphan_audit() -> None:
    worker = _make_worker()
    worker.audit_orphaned_files = MagicMock()

    with (
        patch.object(
            MusicWorker.__mro__[1],  # WorkerBase
            "cleanup_stale_cron",
            new_callable=AsyncMock,
            return_value=0,
        ) as mock_base,
        patch("songmaker_cli.cleanup.run_cleanup_expired") as mock_expired,
    ):
        ctx = _mock_ctx()
        _run(worker.cleanup_stale_cron(ctx))

    mock_base.assert_called_once_with(ctx)
    worker.audit_orphaned_files.assert_called_once()
    mock_expired.assert_called_once()


def test_on_startup_calls_recover_on_startup() -> None:
    worker = MusicWorker()
    worker._recover_on_startup = AsyncMock(return_value=0)

    ctx = _mock_ctx()
    with patch("songmaker_cli.logging_config.configure_logging"):
        _run(worker.on_startup(ctx))

    worker._recover_on_startup.assert_called_once_with(ctx)


def test_on_shutdown_disposes_db() -> None:
    worker = MusicWorker()
    mock_session = MagicMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_factory.return_value.__exit__ = MagicMock(return_value=False)
    worker.get_db_factory = MagicMock(return_value=mock_factory)
    worker._db_engine = MagicMock()

    with patch(
        "songmaker_cli.db.queries.recover_stale_jobs_by_type", return_value=0,
    ):
        _run(worker.on_shutdown(_mock_ctx()))

    worker._db_engine.dispose.assert_called_once()


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


def test_music_worker_settings_uses_singleton_methods() -> None:
    """The arq Settings shim must expose bound methods of _music_worker."""
    from songmaker_cli.music_worker import MusicWorkerSettings
    for func in MusicWorkerSettings.functions:
        assert func.__self__ is mw_mod._music_worker
