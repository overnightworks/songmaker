"""System-wide GPU memory queries via NVML."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def get_gpu_memory_used_mb(device_index: int = 0) -> float | None:
    """Return total GPU memory used across all processes in MB, or None."""
    try:
        import pynvml
    except ImportError:
        log.debug("pynvml not available")
        return None

    try:
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return round(info.used / 1024 / 1024, 1)
    except pynvml.NVMLError as exc:
        log.warning("NVML query failed: %s", exc)
        return None
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass
