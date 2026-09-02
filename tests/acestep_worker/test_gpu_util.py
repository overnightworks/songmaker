from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from acestep_worker.gpu_util import (
    GpuHealthStatus,
    check_gpu_health,
    read_gpu_vram_stats,
)


@pytest.fixture(autouse=True)
def _clear_pynvml_module():
    sys.modules.pop("pynvml", None)
    yield
    sys.modules.pop("pynvml", None)


def test_check_gpu_health_when_pynvml_not_installed_is_not_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A CI box or a laptop with no NVIDIA driver is expected, not an incident."""
    monkeypatch.setitem(sys.modules, "pynvml", None)
    health = check_gpu_health()
    assert health.status is GpuHealthStatus.NOT_INSTALLED
    assert health.is_broken is False


def test_read_gpu_vram_stats_when_pynvml_not_installed_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "pynvml", None)
    assert read_gpu_vram_stats() is None


class _FakeNVMLError(Exception):
    pass


def _install_fake_pynvml(monkeypatch: pytest.MonkeyPatch, *, fails: bool) -> MagicMock:
    fake = ModuleType("pynvml")
    fake.NVMLError = _FakeNVMLError  # type: ignore[attr-defined]
    fake.nvmlInit = MagicMock()  # type: ignore[attr-defined]
    fake.nvmlShutdown = MagicMock()  # type: ignore[attr-defined]

    if fails:
        def _raise_handle(_index: int):
            raise _FakeNVMLError("Driver/library version mismatch")

        fake.nvmlDeviceGetHandleByIndex = _raise_handle  # type: ignore[attr-defined]
    else:
        handle = MagicMock()
        fake.nvmlDeviceGetHandleByIndex = MagicMock(return_value=handle)  # type: ignore[attr-defined]
        info = MagicMock(used=2 * 1024 * 1024 * 1024, total=24 * 1024 * 1024 * 1024)
        fake.nvmlDeviceGetMemoryInfo = MagicMock(return_value=info)  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "pynvml", fake)
    return fake


def test_check_gpu_health_when_nvml_call_fails_is_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NVML is present but the GPU itself does not answer — the real incident:
    a driver/GPU mismatch after a host reboot. This, and only this, must
    turn a worker's healthcheck red."""
    fake = _install_fake_pynvml(monkeypatch, fails=True)
    health = check_gpu_health()
    assert health.status is GpuHealthStatus.UNAVAILABLE
    assert health.is_broken is True
    assert "Driver/library version mismatch" in health.detail
    fake.nvmlShutdown.assert_called_once()


def test_read_gpu_vram_stats_when_nvml_call_fails_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_pynvml(monkeypatch, fails=True)
    assert read_gpu_vram_stats() is None


def test_check_gpu_health_when_nvml_reachable_is_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_pynvml(monkeypatch, fails=False)
    health = check_gpu_health()
    assert health.status is GpuHealthStatus.OK
    assert health.is_broken is False


def test_read_gpu_vram_stats_when_nvml_reachable_returns_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_pynvml(monkeypatch, fails=False)
    stats = read_gpu_vram_stats()
    assert stats is not None
    assert stats.used_gb == 2.0
    assert stats.total_gb == 24.0
