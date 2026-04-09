"""Live GPU memory queries via NVML for acestep_worker.

Kept separate from songmaker_cli.gpu_util because engine isolation forbids
acestep_worker from importing songmaker_cli.
"""

from __future__ import annotations

import logging

from acestep_worker.model_cache import VramStats

log = logging.getLogger(__name__)

_BYTES_PER_GB = 1024 * 1024 * 1024


def read_gpu_vram_stats(device_index: int = 0) -> VramStats | None:
    try:
        import pynvml
    except ImportError:
        log.debug("pynvml not available")
        return None

    try:
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return VramStats(
            used_gb=round(info.used / _BYTES_PER_GB, 2),
            total_gb=round(info.total / _BYTES_PER_GB, 2),
        )
    except pynvml.NVMLError as exc:
        log.warning("NVML query failed: %s", exc)
        return None
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass
