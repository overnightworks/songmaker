"""Tests for system-wide GPU memory queries via NVML."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from songmaker_cli.gpu_util import get_gpu_memory_used_mb


def test_no_pynvml() -> None:
    with patch.dict("sys.modules", {"pynvml": None}):
        assert get_gpu_memory_used_mb() is None


def test_nvml_error() -> None:
    mock_pynvml = MagicMock()
    mock_pynvml.NVMLError = type("NVMLError", (Exception,), {})
    mock_pynvml.nvmlDeviceGetHandleByIndex.side_effect = mock_pynvml.NVMLError("driver error")
    with patch.dict("sys.modules", {"pynvml": mock_pynvml}):
        assert get_gpu_memory_used_mb() is None
    mock_pynvml.nvmlShutdown.assert_called_once()


def test_success() -> None:
    mock_info = MagicMock()
    mock_info.used = 500 * 1024 * 1024

    mock_pynvml = MagicMock()
    mock_pynvml.NVMLError = type("NVMLError", (Exception,), {})
    mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = mock_info
    with patch.dict("sys.modules", {"pynvml": mock_pynvml}):
        result = get_gpu_memory_used_mb()

    assert result == 500.0
    mock_pynvml.nvmlInit.assert_called_once()
    mock_pynvml.nvmlShutdown.assert_called_once()


def test_shutdown_called_on_error() -> None:
    mock_pynvml = MagicMock()
    mock_pynvml.NVMLError = type("NVMLError", (Exception,), {})
    mock_pynvml.nvmlInit.side_effect = mock_pynvml.NVMLError("init failed")
    with patch.dict("sys.modules", {"pynvml": mock_pynvml}):
        assert get_gpu_memory_used_mb() is None
    mock_pynvml.nvmlShutdown.assert_called_once()
