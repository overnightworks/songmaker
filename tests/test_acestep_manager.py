"""Tests for the ACE-Step manager — lifecycle, health, model cache, GPU cleanup."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from songmaker_cli.acestep_manager import AceStepManager

# ── start / stop ───────────────────────────────────────────────────


def test_start_acestep(tmp_path: Path) -> None:
    mgr = AceStepManager()
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    with (
        patch.object(mgr, "_find_uv", return_value=["uv"]),
        patch("subprocess.Popen", return_value=mock_proc),
        patch("songmaker_cli.acestep_manager.ACESTEP_DIR", tmp_path),
    ):
        mgr.start()
    assert mgr._process is mock_proc


def test_start_acestep_no_uv() -> None:
    mgr = AceStepManager()
    with patch.object(mgr, "_find_uv", return_value=None):
        with pytest.raises(RuntimeError, match="uv not found"):
            mgr.start()


def test_start_strips_secrets(tmp_path: Path) -> None:
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
        patch("songmaker_cli.acestep_manager.ACESTEP_DIR", tmp_path),
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

    mgr.stop()

    proc.send_signal.assert_called_once_with(signal.SIGTERM)
    assert mgr._process is None


def test_stop_force_kill() -> None:
    mgr = AceStepManager()
    proc = MagicMock()
    proc.poll.return_value = None
    proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="acestep", timeout=15), None]
    mgr._process = proc

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
        patch.object(mgr, "ensure") as mock_ensure,
        patch.object(mgr, "refresh_cached_model"),
    ):
        mgr.prepare_generate_mode()
    mock_ensure.assert_called_once()
    assert mgr.current_mode == "generate"


def test_prepare_generate_mode_sets_mode_on_repeat() -> None:
    mgr = AceStepManager()
    mgr._current_mode = "generate"
    with (
        patch.object(mgr, "ensure") as mock_ensure,
        patch.object(mgr, "refresh_cached_model"),
    ):
        mgr.prepare_generate_mode()
    mock_ensure.assert_called_once()


# ── switch_model ──────────────────────────────────────────────────


def _mock_refresh_with_model(mgr, model):
    def _side_effect():
        mgr._cached_model = model
    return _side_effect


def test_switch_model_success() -> None:
    mgr = AceStepManager()
    old = os.environ.get("ACESTEP_CONFIG_PATH")
    try:
        with (
            patch.object(mgr, "stop") as mock_stop,
            patch.object(mgr, "start") as mock_start,
            patch.object(mgr, "wait_for_health") as mock_wait,
            patch.object(
                mgr, "refresh_cached_model",
                side_effect=_mock_refresh_with_model(mgr, "turbo"),
            ) as mock_refresh,
        ):
            mgr.switch_model("turbo")

        mock_stop.assert_called_once()
        mock_start.assert_called_once()
        mock_wait.assert_called_once()
        mock_refresh.assert_called_once()
        assert os.environ.get("ACESTEP_CONFIG_PATH") == "acestep-v15-turbo"
    finally:
        if old is None:
            os.environ.pop("ACESTEP_CONFIG_PATH", None)
        else:
            os.environ["ACESTEP_CONFIG_PATH"] = old


def test_switch_model_sft() -> None:
    mgr = AceStepManager()
    old = os.environ.get("ACESTEP_CONFIG_PATH")
    try:
        with (
            patch.object(mgr, "stop"),
            patch.object(mgr, "start"),
            patch.object(mgr, "wait_for_health"),
            patch.object(
                mgr, "refresh_cached_model",
                side_effect=_mock_refresh_with_model(mgr, "sft"),
            ),
        ):
            mgr.switch_model("sft")

        assert os.environ.get("ACESTEP_CONFIG_PATH") == "acestep-v15-sft"
    finally:
        if old is None:
            os.environ.pop("ACESTEP_CONFIG_PATH", None)
        else:
            os.environ["ACESTEP_CONFIG_PATH"] = old


def test_switch_model_verification_failure() -> None:
    mgr = AceStepManager()
    old = os.environ.get("ACESTEP_CONFIG_PATH")
    try:
        with (
            patch.object(mgr, "stop"),
            patch.object(mgr, "start"),
            patch.object(mgr, "wait_for_health"),
            patch.object(
                mgr, "refresh_cached_model",
                side_effect=_mock_refresh_with_model(mgr, "sft"),
            ),
        ):
            with pytest.raises(RuntimeError, match="Model switch to turbo failed"):
                mgr.switch_model("turbo")
    finally:
        if old is None:
            os.environ.pop("ACESTEP_CONFIG_PATH", None)
        else:
            os.environ["ACESTEP_CONFIG_PATH"] = old


def test_switch_model_unknown() -> None:
    mgr = AceStepManager()
    with pytest.raises(ValueError, match="Unknown model mode"):
        mgr.switch_model("nonexistent")


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
