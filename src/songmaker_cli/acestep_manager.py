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
    MODEL_CONFIG_PATHS,
)

log = logging.getLogger(__name__)

ACESTEP_DIR = Path(__file__).resolve().parent.parent.parent / "_models" / "acestep"
_ACESTEP_PORT = int(os.environ.get("ACESTEP_API_PORT", str(ACESTEP_PORT)))
_ACESTEP_HEALTH_URL = ACESTEP_HEALTH_URL_TEMPLATE.format(port=_ACESTEP_PORT)
_SHUTDOWN_GRACE_SECONDS = 15
_SHUTDOWN_KILL_SECONDS = 5
_HEALTH_POLL_SECONDS = 2


class AceStepManager:
    """Manages an ACE-Step subprocess: start, stop, health, model caching."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._cached_model: str | None = None
        self._current_mode: str | None = None
        self._stderr_path: Path | None = None
        self._stderr_file = None

    def start(self) -> None:
        log.info("Starting ACE-Step server...")
        uv = self._find_uv()
        if not uv:
            raise RuntimeError("uv not found — cannot start ACE-Step server")

        env = os.environ.copy()
        env["ACESTEP_API_PORT"] = str(_ACESTEP_PORT)
        env["ACESTEP_API_HOST"] = "127.0.0.1"
        env.setdefault("ACESTEP_DEVICE", "cuda")
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
        self._stderr_path = ACESTEP_DIR / "acestep_stderr.log"
        if self._stderr_file:
            try:
                self._stderr_file.close()
            except OSError:
                log.debug("Failed to close previous stderr file", exc_info=True)
        self._stderr_file = self._stderr_path.open("w")
        self._process = subprocess.Popen(
            cmd, env=env, cwd=ACESTEP_DIR,
            stdout=subprocess.DEVNULL, stderr=self._stderr_file,
        )
        log.info("ACE-Step server process started (PID %d)", self._process.pid)

    def stop(self) -> None:
        if self._stderr_file:
            try:
                self._stderr_file.close()
            except OSError:
                log.debug("Failed to close stderr file during stop", exc_info=True)
            self._stderr_file = None
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
        log.info("ACE-Step server stopped")

    def is_healthy(self) -> bool:
        try:
            req = Request(_ACESTEP_HEALTH_URL, method="GET")
            with urlopen(req, timeout=5):
                return True
        except (OSError, ValueError):
            return False
        except Exception:
            log.debug("Unexpected error during ACE-Step health check", exc_info=True)
            return False

    def wait_for_health(self) -> None:
        deadline = time.time() + ACESTEP_STARTUP_TIMEOUT_SECONDS
        while time.time() < deadline:
            if self.is_healthy():
                log.info("ACE-Step server is ready")
                return
            if self._process and self._process.poll() is not None:
                err = self._read_stderr_tail()
                raise RuntimeError(f"ACE-Step server exited: {err}")
            time.sleep(_HEALTH_POLL_SECONDS)
        raise RuntimeError(
            f"ACE-Step server did not start within {ACESTEP_STARTUP_TIMEOUT_SECONDS}s"
        )

    def _read_stderr_tail(self, max_chars: int = 500) -> str:
        if self._stderr_path and self._stderr_path.exists():
            text = self._stderr_path.read_text(errors="replace")
            return text[-max_chars:] if len(text) > max_chars else text
        return ""

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
            log.debug("Failed to refresh cached model info", exc_info=True)
        self._cached_model = None

    @property
    def current_mode(self) -> str | None:
        return self._current_mode

    def switch_model(self, target_model: str) -> None:
        config_path = MODEL_CONFIG_PATHS.get(target_model)
        if not config_path:
            raise ValueError(f"Unknown model mode: {target_model}")
        log.info("Switching ACE-Step model to %s (%s)...", target_model, config_path)
        self.stop()
        os.environ["ACESTEP_CONFIG_PATH"] = config_path
        self.start()
        self.wait_for_health()
        self.refresh_cached_model()
        if self._cached_model != target_model:
            log.error(
                "Model switch verification failed: expected %s, got %s",
                target_model, self._cached_model,
            )
            raise RuntimeError(
                f"Model switch to {target_model} failed — "
                f"server reports {self._cached_model or 'unknown'}"
            )
        log.info("Model switch complete: %s", self._cached_model)

    def prepare_generate_mode(self) -> None:
        self.ensure()
        self.refresh_cached_model()
        self._current_mode = "generate"

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


