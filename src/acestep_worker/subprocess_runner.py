from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from acestep_engine.constants import MODEL_CONFIG_PATHS
from acestep_worker.model_cache import LoadedModel, Loader, Unloader
from songmaker_cli.settings import get_worker_settings

log = logging.getLogger(__name__)

SECRET_ENV_KEYS = ("ANTHROPIC_API_KEY", "SESSION_SECRET", "SONGMAKER_INTERNAL_TOKEN")


class SubprocessStartError(RuntimeError):
    pass


@dataclass
class SubprocessHandle:
    process: subprocess.Popen[bytes]
    stderr_path: Path | None
    port: int
    stderr_file: Any = None


def find_uv() -> list[str] | None:
    candidates = [
        "uv",
        os.path.expanduser("~/.local/bin/uv"),
        os.path.expanduser("~/.cargo/bin/uv"),
    ]
    for candidate in candidates:
        try:
            subprocess.run([candidate, "--version"], capture_output=True, timeout=5, check=False)
            return [candidate]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def build_env(mode: str, port: int, vram_budget_gb: float) -> dict[str, str]:
    config_path = MODEL_CONFIG_PATHS.get(mode)
    if not config_path:
        raise SubprocessStartError(f"Unknown mode: {mode}")
    env = os.environ.copy()
    env["ACESTEP_API_PORT"] = str(port)
    env["ACESTEP_API_HOST"] = "127.0.0.1"
    env["ACESTEP_CONFIG_PATH"] = config_path
    env.setdefault("ACESTEP_DEVICE", "cuda")
    env.setdefault("ACESTEP_INIT_LLM", "1")
    env.setdefault("ACESTEP_LM_MODEL_PATH", "acestep-5Hz-lm-4B")
    env.setdefault("ACESTEP_LM_BACKEND", "vllm")
    env.setdefault("MAX_CUDA_VRAM", str(vram_budget_gb))
    env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    env.setdefault("ACESTEP_COMPILE_MODEL", "0")
    for secret in SECRET_ENV_KEYS:
        env.pop(secret, None)
    return env


def is_acestep_healthy(port: int, timeout: float = 5.0) -> bool:
    try:
        req = Request(f"http://127.0.0.1:{port}/health", method="GET")
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.status == 200
    except (URLError, OSError):
        return False


def wait_for_health(
    handle: SubprocessHandle,
    *,
    timeout: float | None = None,
    poll: float | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    settings = get_worker_settings()
    if timeout is None:
        timeout = settings.acestep_startup_timeout_seconds
    if poll is None:
        poll = settings.acestep_health_poll_seconds
    deadline = clock() + timeout
    while clock() < deadline:
        if is_acestep_healthy(handle.port):
            return
        if handle.process.poll() is not None:
            tail = _read_stderr_tail(handle.stderr_path)
            raise SubprocessStartError(f"ACE-Step subprocess exited: {tail}")
        sleeper(poll)
    raise SubprocessStartError(f"ACE-Step did not become healthy within {timeout}s")


def _read_stderr_tail(path: Path | None, max_chars: int = 500) -> str:
    if path is None or not path.exists():
        return ""
    text = path.read_text(errors="replace")
    return text[-max_chars:] if len(text) > max_chars else text


def start_acestep_subprocess(
    mode: str,
    *,
    port: int,
    checkpoint_dir: Path,
    vram_budget_gb: float,
    log_dir: Path | None = None,
) -> SubprocessHandle:
    uv = find_uv()
    if uv is None:
        raise SubprocessStartError("uv not found — cannot start ACE-Step subprocess")
    env = build_env(mode, port, vram_budget_gb)
    stderr_path: Path | None = None
    stderr_file = None
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        stderr_path = log_dir / f"acestep-{mode}.stderr.log"
        stderr_file = stderr_path.open("w")
    cmd = [*uv, "run", "acestep-api", "--port", str(port)]
    process = subprocess.Popen(  # noqa: S603
        cmd,
        env=env,
        cwd=checkpoint_dir,
        stdout=subprocess.DEVNULL,
        stderr=stderr_file or subprocess.DEVNULL,
    )
    handle = SubprocessHandle(
        process=process,
        stderr_path=stderr_path,
        port=port,
        stderr_file=stderr_file,
    )
    try:
        wait_for_health(handle)
    except Exception:
        stop_acestep_subprocess(handle)
        raise
    log.info("ACE-Step subprocess for %s ready on port %d (PID %d)", mode, port, process.pid)
    return handle


def stop_acestep_subprocess(handle: SubprocessHandle) -> None:
    settings = get_worker_settings()
    process = handle.process
    try:
        if process.poll() is not None:
            return
        log.info("Stopping ACE-Step subprocess (PID %d)", process.pid)
        try:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=settings.acestep_shutdown_grace_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=settings.acestep_shutdown_kill_seconds)
        except ProcessLookupError:
            pass
    finally:
        if handle.stderr_file is not None:
            try:
                handle.stderr_file.close()
            except OSError:
                log.debug("Failed to close stderr file", exc_info=True)
            handle.stderr_file = None


def make_acestep_runner(
    *,
    checkpoint_dir: Path,
    base_port: int,
    vram_budget_gb: float,
    log_dir: Path | None = None,
) -> tuple[Loader, Unloader]:
    async def loader(mode: str) -> LoadedModel:
        handle = await asyncio.to_thread(
            start_acestep_subprocess,
            mode,
            port=base_port,
            checkpoint_dir=checkpoint_dir,
            vram_budget_gb=vram_budget_gb,
            log_dir=log_dir,
        )
        return LoadedModel(mode=mode, handle=handle, port=handle.port)

    async def unloader(model: LoadedModel) -> None:
        handle = model.handle
        if isinstance(handle, SubprocessHandle):
            await asyncio.to_thread(stop_acestep_subprocess, handle)

    return loader, unloader
