"""GPU job queue — serializes GPU-bound work with model switching.

Currently runs as a single-threaded queue on the local host.
Designed to be replaceable with a distributed queue (Celery/Redis)
without changing the submission interface.

Usage:
    queue = GpuQueue()
    queue.start()
    queue.submit(job_id, "generate", fn, args, kwargs)
    queue.shutdown()
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from typing import Any
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

ACESTEP_DIR = Path(__file__).resolve().parent.parent.parent / "_models" / "acestep"
ACESTEP_PORT = int(os.environ.get("ACESTEP_API_PORT", "8001"))
ACESTEP_HEALTH_URL = f"http://localhost:{ACESTEP_PORT}/health"
ACESTEP_STARTUP_TIMEOUT = 120


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
        self._acestep_process: subprocess.Popen | None = None

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
        self._stop_acestep()

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
        if self._current_mode != job.job_type:
            if self._current_mode:
                log.info("Switching GPU mode: %s → %s", self._current_mode, job.job_type)
            self._prepare_mode(job.job_type)

        self._current_mode = job.job_type
        log.info("GPU queue: running %s job %s", job.job_type, job.job_id)

        try:
            job.fn(*job.args, **job.kwargs)
        except Exception:
            log.exception("GPU job %s failed", job.job_id)

    def _prepare_mode(self, mode: str) -> None:
        """Prepare GPU for the given mode — clear old models, start services."""
        try:
            if mode == "generate":
                self._clear_scoring_models()
                self._verify_vram_freed()
                self._ensure_acestep()
            elif mode == "score":
                self._stop_acestep()
                self._gc_gpu()
                self._verify_vram_freed()
        except Exception:
            log.exception("Failed to prepare GPU mode: %s", mode)

    def _clear_scoring_models(self) -> None:
        try:
            import songmaker_cli.scoring.text_accuracy as ta
            for key in list(ta._whisper_model_cache.keys()):
                model = ta._whisper_model_cache.pop(key)
                del model
            log.info("Cleared Whisper model cache")
        except (ImportError, AttributeError):
            pass

        try:
            import songmaker_cli.scoring.audiobox_aesthetics as ab
            for key in list(ab._predictor_cache.keys()):
                predictor = ab._predictor_cache.pop(key)
                del predictor
            log.info("Cleared AudioBox model cache")
        except (ImportError, AttributeError):
            pass

        self._gc_gpu()

    def _verify_vram_freed(self, max_wait: int = 10) -> None:
        """Wait for VRAM to be released after model clearing."""
        try:
            import torch
            if not torch.cuda.is_available():
                return
            for i in range(max_wait):
                allocated = torch.cuda.memory_allocated() / 1024 / 1024
                if allocated < 100:
                    log.info("VRAM freed: %.0f MB allocated", allocated)
                    return
                log.info("Waiting for VRAM release... %.0f MB still allocated", allocated)
                import gc
                gc.collect()
                torch.cuda.empty_cache()
                time.sleep(1)
            log.warning("VRAM not fully freed after %ds (%.0f MB remaining)",
                        max_wait, torch.cuda.memory_allocated() / 1024 / 1024)
        except ImportError:
            pass

    # ── ACE-Step server lifecycle ────────────────────────────────────

    def _ensure_acestep(self) -> None:
        """Start ACE-Step server if not running, wait for health check."""
        if self._is_acestep_healthy():
            log.info("ACE-Step server already running")
            return

        self._start_acestep()
        self._wait_for_acestep()

    def _is_acestep_healthy(self) -> bool:
        try:
            req = Request(ACESTEP_HEALTH_URL, method="GET")
            with urlopen(req, timeout=5):
                return True
        except Exception:
            return False

    def _start_acestep(self) -> None:
        log.info("Starting ACE-Step server...")

        uv = self._find_uv()
        if not uv:
            raise RuntimeError("uv not found — cannot start ACE-Step server")

        env = os.environ.copy()
        env["ACESTEP_API_PORT"] = str(ACESTEP_PORT)
        env["ACESTEP_API_HOST"] = "0.0.0.0"
        env["ACESTEP_DEVICE"] = "cuda"
        env.setdefault("ACESTEP_CONFIG_PATH", "acestep-v15-sft")
        env.setdefault("ACESTEP_INIT_LLM", "1")
        env.setdefault("ACESTEP_LM_MODEL_PATH", "acestep-5Hz-lm-4B")
        env.setdefault("ACESTEP_LM_BACKEND", "vllm")
        env.setdefault("MAX_CUDA_VRAM", "20")
        env.setdefault("ACESTEP_COMPILE_MODEL", "0")

        cmd = [*uv, "run", "acestep-api", "--port", str(ACESTEP_PORT)]
        self._acestep_process = subprocess.Popen(
            cmd, env=env, cwd=ACESTEP_DIR,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        log.info("ACE-Step server process started (PID %d)", self._acestep_process.pid)

    def _wait_for_acestep(self) -> None:
        deadline = time.time() + ACESTEP_STARTUP_TIMEOUT
        while time.time() < deadline:
            if self._is_acestep_healthy():
                log.info("ACE-Step server is ready")
                return
            if self._acestep_process and self._acestep_process.poll() is not None:
                stderr = self._acestep_process.stderr
                err = stderr.read().decode() if stderr else ""
                raise RuntimeError(f"ACE-Step server exited: {err[:500]}")
            time.sleep(2)
        raise RuntimeError(f"ACE-Step server did not start within {ACESTEP_STARTUP_TIMEOUT}s")

    def _stop_acestep(self) -> None:
        if not self._acestep_process:
            return
        if self._acestep_process.poll() is not None:
            self._acestep_process = None
            return

        log.info("Stopping ACE-Step server (PID %d)...", self._acestep_process.pid)
        self._acestep_process.send_signal(signal.SIGTERM)
        try:
            self._acestep_process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self._acestep_process.kill()
            self._acestep_process.wait(timeout=5)
        self._acestep_process = None
        self._gc_gpu()
        log.info("ACE-Step server stopped")

    def _find_uv(self) -> list[str] | None:
        """Find the uv binary."""
        for candidate in ["uv", os.path.expanduser("~/.local/bin/uv"),
                          os.path.expanduser("~/.cargo/bin/uv")]:
            try:
                subprocess.run(
                    [candidate, "--version"],
                    capture_output=True, timeout=5,
                )
                return [candidate]
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        return None

    def _gc_gpu(self) -> None:
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
