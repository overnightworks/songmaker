"""Tests for the ACE-Step manager — lifecycle, health, model cache, GPU cleanup."""

from __future__ import annotations

import signal
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from songmaker_cli.acestep_manager import (
    AceStepManager,
    clear_scoring_models,
    gc_gpu,
    verify_vram_freed,
)

# ── start / stop ───────────────────────────────────────────────────


def test_start_acestep() -> None:
    mgr = AceStepManager()
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    with (
        patch.object(mgr, "_find_uv", return_value=["uv"]),
        patch("subprocess.Popen", return_value=mock_proc),
    ):
        mgr.start()
    assert mgr._process is mock_proc


def test_start_acestep_no_uv() -> None:
    mgr = AceStepManager()
    with patch.object(mgr, "_find_uv", return_value=None):
        with pytest.raises(RuntimeError, match="uv not found"):
            mgr.start()


def test_start_strips_secrets() -> None:
    mgr = AceStepManager()
    mock_proc = MagicMock()
    mock_proc.pid = 1
    captured_env = {}

    def capture_popen(*args, **kwargs):
        captured_env.update(kwargs.get("env", {}))
        return mock_proc

    with (
        patch.object(mgr, "_find_uv", return_value=["uv"]),
        patch("subprocess.Popen", side_effect=capture_popen),
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "secret", "SESSION_SECRET": "secret2"}),
    ):
        mgr.start()

    assert "ANTHROPIC_API_KEY" not in captured_env
    assert "SESSION_SECRET" not in captured_env


def test_stop_no_process() -> None:
    mgr = AceStepManager()
    mgr._process = None
    mgr.stop()


def test_stop_already_exited() -> None:
    mgr = AceStepManager()
    proc = MagicMock()
    proc.poll.return_value = 0
    mgr._process = proc
    mgr.stop()
    assert mgr._process is None


def test_stop_graceful() -> None:
    mgr = AceStepManager()
    proc = MagicMock()
    proc.poll.return_value = None
    proc.wait.return_value = 0
    mgr._process = proc

    with patch("songmaker_cli.acestep_manager.gc_gpu"):
        mgr.stop()

    proc.send_signal.assert_called_once_with(signal.SIGTERM)
    assert mgr._process is None


def test_stop_force_kill() -> None:
    mgr = AceStepManager()
    proc = MagicMock()
    proc.poll.return_value = None
    proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="acestep", timeout=15), None]
    mgr._process = proc

    with patch("songmaker_cli.acestep_manager.gc_gpu"):
        mgr.stop()

    proc.kill.assert_called_once()
    assert mgr._process is None


# ── health checks ──────────────────────────────────────────────────


def test_is_healthy_success() -> None:
    mgr = AceStepManager()
    mock_response = MagicMock()
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    with patch("songmaker_cli.acestep_manager.urlopen", return_value=mock_response):
        assert mgr.is_healthy() is True


def test_is_healthy_failure() -> None:
    mgr = AceStepManager()
    with patch("songmaker_cli.acestep_manager.urlopen", side_effect=ConnectionError):
        assert mgr.is_healthy() is False


def test_ensure_already_healthy() -> None:
    mgr = AceStepManager()
    with patch.object(mgr, "is_healthy", return_value=True):
        mgr.ensure()


def test_ensure_starts_and_waits() -> None:
    mgr = AceStepManager()
    with (
        patch.object(mgr, "is_healthy", return_value=False),
        patch.object(mgr, "start"),
        patch.object(mgr, "wait_for_health"),
    ):
        mgr.ensure()


def test_wait_for_health_success() -> None:
    mgr = AceStepManager()
    mgr._process = MagicMock()
    mgr._process.poll.return_value = None

    calls = [False, True]
    with (
        patch.object(mgr, "is_healthy", side_effect=calls),
        patch("time.sleep"),
    ):
        mgr.wait_for_health()


def test_wait_for_health_process_exits() -> None:
    mgr = AceStepManager()
    stderr_mock = MagicMock()
    stderr_mock.read.return_value = b"fatal error"
    mgr._process = MagicMock()
    mgr._process.poll.return_value = 1
    mgr._process.stderr = stderr_mock

    with (
        patch.object(mgr, "is_healthy", return_value=False),
        patch("time.sleep"),
    ):
        with pytest.raises(RuntimeError, match="ACE-Step server exited"):
            mgr.wait_for_health()


def test_wait_for_health_timeout() -> None:
    mgr = AceStepManager()
    mgr._process = MagicMock()
    mgr._process.poll.return_value = None

    with (
        patch.object(mgr, "is_healthy", return_value=False),
        patch("time.sleep"),
        patch("time.time", side_effect=[0, 0, 999]),
    ):
        with pytest.raises(RuntimeError, match="did not start"):
            mgr.wait_for_health()


# ── active_model ───────────────────────────────────────────────────


def test_active_model_sft() -> None:
    mgr = AceStepManager()
    mock_info = MagicMock()
    mock_info.model = "acestep-v15-sft"
    mock_client = MagicMock()
    mock_client.server_info.return_value = mock_info
    with patch("acestep_engine.client.AceStepClient", return_value=mock_client):
        mgr.refresh_cached_model()
        assert mgr.active_model == "sft"


def test_active_model_turbo() -> None:
    mgr = AceStepManager()
    mock_info = MagicMock()
    mock_info.model = "acestep-v15-turbo"
    mock_client = MagicMock()
    mock_client.server_info.return_value = mock_info
    with patch("acestep_engine.client.AceStepClient", return_value=mock_client):
        mgr.refresh_cached_model()
        assert mgr.active_model == "turbo"


def test_active_model_server_unavailable() -> None:
    mgr = AceStepManager()
    mock_client = MagicMock()
    mock_client.server_info.return_value = None
    with patch("acestep_engine.client.AceStepClient", return_value=mock_client):
        mgr.refresh_cached_model()
        assert mgr.active_model is None


def test_active_model_exception() -> None:
    mgr = AceStepManager()
    with patch("acestep_engine.client.AceStepClient", side_effect=Exception("boom")):
        mgr.refresh_cached_model()
        assert mgr.active_model is None


# ── prepare modes ──────────────────────────────────────────────────


def test_prepare_generate_mode() -> None:
    mgr = AceStepManager()
    with (
        patch("songmaker_cli.gpu_util.get_gpu_memory_used_mb", return_value=18000.0),
        patch("songmaker_cli.acestep_manager._release_scorer_gpu") as mock_release,
        patch("songmaker_cli.acestep_manager.verify_vram_freed") as mock_verify,
        patch.object(mgr, "ensure") as mock_ensure,
        patch.object(mgr, "refresh_cached_model"),
    ):
        mgr.prepare_generate_mode()
    mock_release.assert_called_once()
    mock_verify.assert_called_once_with(baseline_mb=18000.0)
    mock_ensure.assert_called_once()


def test_prepare_generate_mode_vram_failure_propagates() -> None:
    mgr = AceStepManager()
    with (
        patch("songmaker_cli.gpu_util.get_gpu_memory_used_mb", return_value=18000.0),
        patch("songmaker_cli.acestep_manager._release_scorer_gpu"),
        patch(
            "songmaker_cli.acestep_manager.verify_vram_freed",
            side_effect=RuntimeError("GPU memory not freed"),
        ),
    ):
        with pytest.raises(RuntimeError, match="GPU memory not freed"):
            mgr.prepare_generate_mode()


# ── clear_scoring_models ───────────────────────────────────────────


def test_clear_scoring_models_calls_clear_cache() -> None:
    with (
        patch("songmaker_cli.scoring.text_accuracy.clear_cache") as mock_whisper,
        patch("songmaker_cli.scoring.audiobox_aesthetics.clear_cache") as mock_audiobox,
        patch("songmaker_cli.acestep_manager.gc_gpu"),
    ):
        clear_scoring_models()

    mock_whisper.assert_called_once()
    mock_audiobox.assert_called_once()


def test_clear_scoring_models_handles_import_error() -> None:
    with patch("songmaker_cli.acestep_manager.gc_gpu"):
        clear_scoring_models()


def test_clear_scoring_models_whisper_import_error() -> None:
    with (
        patch.dict("sys.modules", {"songmaker_cli.scoring.text_accuracy": None}),
        patch("songmaker_cli.acestep_manager.gc_gpu"),
    ):
        clear_scoring_models()


def test_clear_scoring_models_audiobox_import_error() -> None:
    with (
        patch(
            "songmaker_cli.scoring.text_accuracy.clear_cache",
            side_effect=ImportError,
        ),
        patch.dict("sys.modules", {"songmaker_cli.scoring.audiobox_aesthetics": None}),
        patch("songmaker_cli.acestep_manager.gc_gpu"),
    ):
        clear_scoring_models()


# ── verify_vram_freed ──────────────────────────────────────────────


def test_verify_vram_freed_no_pynvml() -> None:
    with patch("songmaker_cli.gpu_util.get_gpu_memory_used_mb", return_value=None):
        verify_vram_freed(baseline_mb=None)


def test_verify_vram_freed_delta_success() -> None:
    mock_get = MagicMock(return_value=18100.0)
    with (
        patch("songmaker_cli.gpu_util.get_gpu_memory_used_mb", mock_get),
        patch("songmaker_cli.acestep_manager.gc_gpu"),
    ):
        verify_vram_freed(baseline_mb=18000.0, max_wait=1)
    mock_get.assert_called_once()


def test_verify_vram_freed_just_over_margin_fails() -> None:
    with (
        patch(
            "songmaker_cli.gpu_util.get_gpu_memory_used_mb",
            return_value=18201.0,
        ),
        patch("songmaker_cli.acestep_manager.gc_gpu"),
        patch("time.sleep"),
    ):
        with pytest.raises(RuntimeError, match="GPU memory not freed"):
            verify_vram_freed(baseline_mb=18000.0, max_wait=1)


def test_verify_vram_freed_gradual_release() -> None:
    readings = [21000.0, 19000.0, 18100.0]
    with (
        patch(
            "songmaker_cli.gpu_util.get_gpu_memory_used_mb",
            side_effect=readings,
        ),
        patch("songmaker_cli.acestep_manager.gc_gpu"),
        patch("time.sleep"),
    ):
        verify_vram_freed(baseline_mb=18000.0, max_wait=5)


def test_verify_vram_freed_not_freed_raises() -> None:
    with (
        patch(
            "songmaker_cli.gpu_util.get_gpu_memory_used_mb",
            return_value=21000.0,
        ),
        patch("songmaker_cli.acestep_manager.gc_gpu"),
        patch("time.sleep"),
    ):
        with pytest.raises(RuntimeError, match="GPU memory not freed"):
            verify_vram_freed(baseline_mb=18000.0, max_wait=2)


def test_verify_vram_freed_nvml_fails_midpoll() -> None:
    readings = [21000.0, None]
    with (
        patch(
            "songmaker_cli.gpu_util.get_gpu_memory_used_mb",
            side_effect=readings,
        ),
        patch("songmaker_cli.acestep_manager.gc_gpu"),
        patch("time.sleep"),
    ):
        verify_vram_freed(baseline_mb=18000.0, max_wait=5)


# ── gc_gpu ─────────────────────────────────────────────────────────


def test_gc_gpu_with_cuda() -> None:
    mock_torch = MagicMock()
    mock_torch.cuda.is_available.return_value = True
    with patch.dict("sys.modules", {"torch": mock_torch}):
        gc_gpu()
    mock_torch.cuda.empty_cache.assert_called_once()


def test_gc_gpu_no_torch() -> None:
    with patch.dict("sys.modules", {"torch": None}):
        gc_gpu()


# ── _find_uv ──────────────────────────────────────────────────────


def test_find_uv_found() -> None:
    mgr = AceStepManager()
    with patch("subprocess.run"):
        result = mgr._find_uv()
    assert result is not None


def test_find_uv_not_found() -> None:
    mgr = AceStepManager()
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = mgr._find_uv()
    assert result is None
