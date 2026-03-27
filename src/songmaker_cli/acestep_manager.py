"""ACE-Step server lifecycle management.

Manages starting, stopping, and health-checking the ACE-Step subprocess.
Extracted from GpuQueue to be shared between the arq worker and tests.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen

from songmaker_cli.constants import (
    ACESTEP_HEALTH_URL_TEMPLATE,
    ACESTEP_PORT,
    ACESTEP_STARTUP_TIMEOUT_SECONDS,
)

log = logging.getLogger(__name__)

ACESTEP_DIR = Path(__file__).resolve().parent.parent.parent / "_models" / "acestep"
_ACESTEP_PORT = int(os.environ.get("ACESTEP_API_PORT", str(ACESTEP_PORT)))
_ACESTEP_HEALTH_URL = ACESTEP_HEALTH_URL_TEMPLATE.format(port=_ACESTEP_PORT)
_SHUTDOWN_GRACE_SECONDS = 15
_SHUTDOWN_KILL_SECONDS = 5
_HEALTH_POLL_SECONDS = 2
_VRAM_THRESHOLD_MB = 100
_VRAM_POLL_SECONDS = 1


class AceStepManager:
    """Manages an ACE-Step subprocess: start, stop, health, model caching."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._cached_model: str | None = None

    def start(self) -> None:
        log.info("Starting ACE-Step server...")
        uv = self._find_uv()
        if not uv:
            raise RuntimeError("uv not found — cannot start ACE-Step server")

        env = os.environ.copy()
        env["ACESTEP_API_PORT"] = str(_ACESTEP_PORT)
        env["ACESTEP_API_HOST"] = "127.0.0.1"
        env["ACESTEP_DEVICE"] = "cuda"
        env.setdefault("ACESTEP_CONFIG_PATH", "acestep-v15-sft")
        env.setdefault("ACESTEP_INIT_LLM", "1")
        env.setdefault("ACESTEP_LM_MODEL_PATH", "acestep-5Hz-lm-4B")
        env.setdefault("ACESTEP_LM_BACKEND", "vllm")
        from songmaker_cli.constants import ACESTEP_DEFAULT_VRAM_GB
        env.setdefault("MAX_CUDA_VRAM", ACESTEP_DEFAULT_VRAM_GB)
        env.setdefault("ACESTEP_COMPILE_MODEL", "0")

        for secret_key in ("ANTHROPIC_API_KEY", "SESSION_SECRET"):
            env.pop(secret_key, None)

        cmd = [*uv, "run", "acestep-api", "--port", str(_ACESTEP_PORT)]
        self._process = subprocess.Popen(
            cmd, env=env, cwd=ACESTEP_DIR,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        log.info("ACE-Step server process started (PID %d)", self._process.pid)

    def stop(self) -> None:
        if not self._process:
            return
        if self._process.poll() is not None:
            self._process = None
            return

        log.info("Stopping ACE-Step server (PID %d)...", self._process.pid)
        self._process.send_signal(signal.SIGTERM)
        try:
            self._process.wait(timeout=_SHUTDOWN_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=_SHUTDOWN_KILL_SECONDS)
        self._process = None
        self._cached_model = None
        gc_gpu()
        log.info("ACE-Step server stopped")

    def is_healthy(self) -> bool:
        try:
            req = Request(_ACESTEP_HEALTH_URL, method="GET")
            with urlopen(req, timeout=5):
                return True
        except Exception:
            return False

    def wait_for_health(self) -> None:
        deadline = time.time() + ACESTEP_STARTUP_TIMEOUT_SECONDS
        while time.time() < deadline:
            if self.is_healthy():
                log.info("ACE-Step server is ready")
                return
            if self._process and self._process.poll() is not None:
                stderr = self._process.stderr
                err = stderr.read().decode() if stderr else ""
                raise RuntimeError(f"ACE-Step server exited: {err[:500]}")
            time.sleep(_HEALTH_POLL_SECONDS)
        raise RuntimeError(
            f"ACE-Step server did not start within {ACESTEP_STARTUP_TIMEOUT_SECONDS}s"
        )

    def ensure(self) -> None:
        if self.is_healthy():
            log.info("ACE-Step server already running")
            return
        self.start()
        self.wait_for_health()

    @property
    def active_model(self) -> str | None:
        return self._cached_model

    def refresh_cached_model(self) -> None:
        try:
            from acestep_engine.client import AceStepClient
            from songmaker_cli.config import resolve_model_mode
            info = AceStepClient().server_info()
            if info and info.model:
                self._cached_model = resolve_model_mode(info.model)
                return
        except Exception:
            pass
        self._cached_model = None

    def prepare_generate_mode(self) -> None:
        clear_scoring_models()
        verify_vram_freed()
        self.ensure()
        self.refresh_cached_model()

    def prepare_score_mode(self) -> None:
        pass

    def _find_uv(self) -> list[str] | None:
        for candidate in [
            "uv",
            os.path.expanduser("~/.local/bin/uv"),
            os.path.expanduser("~/.cargo/bin/uv"),
        ]:
            try:
                subprocess.run(
                    [candidate, "--version"],
                    capture_output=True, timeout=5,
                )
                return [candidate]
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        return None


def clear_scoring_models() -> None:
    try:
        from songmaker_cli.scoring.text_accuracy import clear_cache as clear_whisper
        clear_whisper()
    except ImportError:
        pass

    try:
        from songmaker_cli.scoring.audiobox_aesthetics import clear_cache as clear_audiobox
        clear_audiobox()
    except ImportError:
        pass

    gc_gpu()


def verify_vram_freed(max_wait: int = 10) -> None:
    try:
        import torch
        if not torch.cuda.is_available():
            return
        for _i in range(max_wait):
            allocated = torch.cuda.memory_allocated() / 1024 / 1024
            if allocated < _VRAM_THRESHOLD_MB:
                log.info("VRAM freed: %.0f MB allocated", allocated)
                return
            log.info("Waiting for VRAM release... %.0f MB still allocated", allocated)
            import gc
            gc.collect()
            torch.cuda.empty_cache()
            time.sleep(_VRAM_POLL_SECONDS)
        log.warning(
            "VRAM not fully freed after %ds (%.0f MB remaining)",
            max_wait, torch.cuda.memory_allocated() / 1024 / 1024,
        )
    except ImportError:
        pass


def gc_gpu() -> None:
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            log.info("Cleared CUDA cache")
    except ImportError:
        pass
