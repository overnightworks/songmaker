"""Live GPU memory queries via NVML for acestep_worker.

The only NVML reader in the project: this worker's container is the sole
one holding a GPU, so it measures its own VRAM and publishes it in its
heartbeat, from which songmaker-web republishes it on /metrics.

``check_gpu_health`` shares the same NVML round trip but answers a
different question: not "how much VRAM is free" but "can this worker still
reach its GPU at all". The two must disagree on one thing on purpose — a
missing ``pynvml`` package (any non-GPU host: CI, a unit test, a laptop) is
not a broken worker, while ``pynvml`` present but unable to open the device
(the September incident: driver/GPU mismatch after a host reboot) is. Only
the latter may ever turn a worker's healthcheck red.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from acestep_worker.model_cache import VramStats

log = logging.getLogger(__name__)

_BYTES_PER_GB = 1024 * 1024 * 1024


class GpuHealthStatus(str, Enum):
    OK = "ok"
    NOT_INSTALLED = "not_installed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class GpuHealth:
    status: GpuHealthStatus
    detail: str | None = None

    @property
    def is_broken(self) -> bool:
        """True only when NVML is present but the GPU itself did not answer.

        A host with no ``pynvml`` install (``NOT_INSTALLED``) is expected in
        CI and local dev and must never fail a worker's healthcheck.
        """
        return self.status is GpuHealthStatus.UNAVAILABLE


@dataclass(frozen=True)
class _NvmlQuery:
    health: GpuHealth
    stats: VramStats | None


def _query_nvml(device_index: int) -> _NvmlQuery:
    try:
        import pynvml
    except ImportError:
        log.debug("pynvml not available")
        return _NvmlQuery(health=GpuHealth(GpuHealthStatus.NOT_INSTALLED), stats=None)

    try:
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        stats = VramStats(
            used_gb=round(info.used / _BYTES_PER_GB, 2),
            total_gb=round(info.total / _BYTES_PER_GB, 2),
        )
        return _NvmlQuery(health=GpuHealth(GpuHealthStatus.OK), stats=stats)
    except pynvml.NVMLError as exc:
        log.warning("NVML query failed: %s", exc)
        return _NvmlQuery(
            health=GpuHealth(GpuHealthStatus.UNAVAILABLE, detail=str(exc)),
            stats=None,
        )
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass


def read_gpu_vram_stats(device_index: int = 0) -> VramStats | None:
    return _query_nvml(device_index).stats


def check_gpu_health(device_index: int = 0) -> GpuHealth:
    return _query_nvml(device_index).health
