"""GPU job queue — serializes GPU-bound work with model switching.

Currently runs as a single-threaded queue on the local host.
Designed to be replaceable with a distributed queue (Celery/Redis)
without changing the submission interface.

Usage:
    queue = GpuQueue()
    queue.start()
    job_id = queue.submit("generate", fn, args, kwargs)
    queue.shutdown()
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from queue import Queue
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class GpuJob:
    job_id: str
    job_type: str
    fn: Callable[..., Any]
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)


class GpuQueue:
    """Sequential GPU job queue with model cache clearing between job types."""

    def __init__(self) -> None:
        self._queue: Queue[GpuJob | None] = Queue()
        self._worker: threading.Thread | None = None
        self._current_mode: str | None = None
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._worker = threading.Thread(target=self._run, daemon=True, name="gpu-queue")
        self._worker.start()
        log.info("GPU queue started")

    def shutdown(self) -> None:
        self._running = False
        self._queue.put(None)
        if self._worker:
            self._worker.join(timeout=5)

    def submit(
        self, job_id: str, job_type: str, fn: Callable[..., Any],
        args: tuple = (), kwargs: dict | None = None,
    ) -> None:
        self._queue.put(GpuJob(
            job_id=job_id, job_type=job_type, fn=fn,
            args=args, kwargs=kwargs or {},
        ))

    def _run(self) -> None:
        while self._running:
            job = self._queue.get()
            if job is None:
                break
            self._execute(job)

    def _execute(self, job: GpuJob) -> None:
        if self._current_mode and self._current_mode != job.job_type:
            log.info("Switching GPU mode: %s → %s", self._current_mode, job.job_type)
            self._clear_models(self._current_mode)

        self._current_mode = job.job_type
        log.info("GPU queue: running %s job %s", job.job_type, job.job_id)

        try:
            job.fn(*job.args, **job.kwargs)
        except Exception:
            log.exception("GPU job %s failed", job.job_id)

    def _clear_models(self, mode: str) -> None:
        """Clear cached models from the previous mode to free VRAM."""
        try:
            if mode == "score":
                self._clear_scoring_models()
            elif mode == "generate":
                self._clear_generation_models()
        except Exception:
            log.exception("Failed to clear %s models", mode)

    def _clear_scoring_models(self) -> None:
        """Unload Whisper and AudioBox models from VRAM."""
        try:
            import songmaker_cli.scoring.text_accuracy as ta
            ta._whisper_model_cache.clear()
            log.info("Cleared Whisper model cache")
        except (ImportError, AttributeError):
            pass

        try:
            import songmaker_cli.scoring.audiobox_aesthetics as ab
            ab._predictor_cache.clear()
            log.info("Cleared AudioBox model cache")
        except (ImportError, AttributeError):
            pass

        self._gc_gpu()

    def _clear_generation_models(self) -> None:
        """ACE-Step runs as separate server — nothing to unload in-process."""
        pass

    def _gc_gpu(self) -> None:
        """Force garbage collection and clear CUDA cache."""
        import gc
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                log.info("Cleared CUDA cache")
        except ImportError:
            pass


# ── Singleton ────────────────────────────────────────────────────────

_instance: GpuQueue | None = None


def get_gpu_queue() -> GpuQueue:
    global _instance
    if _instance is None:
        _instance = GpuQueue()
        _instance.start()
    return _instance
