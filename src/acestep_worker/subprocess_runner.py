from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Final
from urllib.error import URLError
from urllib.request import Request, urlopen

from acestep_engine.constants import MODEL_CONFIG_PATHS
from acestep_worker.constants import SECRET_ENV_KEYS
from acestep_worker.model_cache import LoadedModel, Loader, Unloader
from acestep_worker.settings import get_worker_settings

log = logging.getLogger(__name__)

SUBPROCESS_BIND_HOST: Final = "127.0.0.1"

# One inner port per model mode, derived deterministically from the mode's
# position in MODEL_CONFIG_PATHS (not a hash — stable across restarts and
# easy to reason about). Without this, two loaded modes would share one
# port: the second subprocess dies at EADDRINUSE while wait_for_health sees
# the FIRST subprocess's still-running /health and reports "ready" anyway
# (issue #205), so generations for the second mode silently ran on the
# first mode's model.
MODEL_INNER_PORT_OFFSETS: Final[dict[str, int]] = {
    mode: offset for offset, mode in enumerate(MODEL_CONFIG_PATHS)
}

LogLineSink = Callable[[str], None]


class SubprocessStartError(RuntimeError):
    pass


@dataclass
class SubprocessHandle:
    process: subprocess.Popen[bytes]
    stderr_path: Path | None
    port: int
    stderr_file: IO[str] | None = None
    log_thread: threading.Thread | None = None


def find_uv() -> list[str] | None:
    candidates = [
        "uv",
        os.path.expanduser("~/.local/bin/uv"),
        os.path.expanduser("~/.cargo/bin/uv"),
    ]
    for candidate in candidates:
        try:
            subprocess.run([candidate, "--version"], capture_output=True, timeout=5, check=False)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            result = None
        else:
            result = candidate
        if result is not None:
            return [result]
    return None


def _as_env_flag(enabled: bool) -> str:
    return "1" if enabled else "0"


def build_env(
    mode: str,
    port: int,
    vram_budget_gb: float,
    gpu_id: int | None = None,
) -> dict[str, str]:
    config_path = MODEL_CONFIG_PATHS.get(mode)
    if not config_path:
        raise SubprocessStartError(f"Unknown mode: {mode}")
    settings = get_worker_settings()
    env = os.environ.copy()
    env["ACESTEP_API_PORT"] = str(port)
    env["ACESTEP_API_HOST"] = SUBPROCESS_BIND_HOST
    env["ACESTEP_CONFIG_PATH"] = config_path
    env["ACESTEP_DEVICE"] = settings.acestep_device
    env["ACESTEP_INIT_LLM"] = _as_env_flag(settings.acestep_init_llm)
    env["ACESTEP_LM_MODEL_PATH"] = settings.acestep_lm_model_path
    env["ACESTEP_LM_BACKEND"] = settings.acestep_lm_backend
    env["ACESTEP_COMPILE_MODEL"] = _as_env_flag(settings.acestep_compile_model)
    env["MAX_CUDA_VRAM"] = str(vram_budget_gb)
    env["PYTORCH_CUDA_ALLOC_CONF"] = settings.pytorch_cuda_alloc_conf
    env["PYTHONUNBUFFERED"] = "1"
    if gpu_id is not None:
        env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
    for secret in SECRET_ENV_KEYS:
        env.pop(secret, None)
    # Inherited VIRTUAL_ENV doesn't apply to the child's project; it only makes uv warn.
    env.pop("VIRTUAL_ENV", None)
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
    tail = _read_stderr_tail(handle.stderr_path, max_chars=2000)
    suffix = f"\n--- last log lines ---\n{tail}" if tail else ""
    raise SubprocessStartError(
        f"ACE-Step did not become healthy within {timeout}s{suffix}",
    )


def inner_port_for_mode(base_port: int, mode: str) -> int:
    try:
        offset = MODEL_INNER_PORT_OFFSETS[mode]
    except KeyError as exc:
        raise SubprocessStartError(f"Unknown mode: {mode}") from exc
    return base_port + offset


def _read_stderr_tail(path: Path | None, max_chars: int = 500) -> str:
    if path is None or not path.exists():
        return ""
    text = path.read_text(errors="replace")
    return text[-max_chars:] if len(text) > max_chars else text


def _stream_subprocess_logs(
    *,
    mode: str,
    process: subprocess.Popen[bytes],
    log_file: IO[str] | None,
    on_log_line: LogLineSink | None,
) -> None:
    stdout = process.stdout
    if stdout is None:
        return
    try:
        for raw in iter(stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line:
                continue
            if log_file is not None:
                try:
                    log_file.write(line + "\n")
                    log_file.flush()
                except (OSError, ValueError):
                    pass
            log.info("[ace-step %s] %s", mode, line)
            if on_log_line is not None:
                try:
                    on_log_line(line)
                except Exception:
                    log.warning("on_log_line callback raised", exc_info=True)
    except Exception:
        log.warning("Subprocess log streamer crashed", exc_info=True)


def _open_log_file(log_dir: Path | None, mode: str) -> tuple[Path | None, IO[str] | None]:
    if log_dir is None:
        return None, None
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"acestep-{mode}.stderr.log"
    handle = path.open("a", encoding="utf-8")
    header = f"\n=== {mode} attempt at {datetime.now(timezone.utc).isoformat()} ===\n"
    handle.write(header)
    handle.flush()
    return path, handle


def start_acestep_subprocess(
    mode: str,
    *,
    port: int,
    checkpoint_dir: Path,
    vram_budget_gb: float,
    gpu_id: int | None = None,
    log_dir: Path | None = None,
    on_log_line: LogLineSink | None = None,
) -> SubprocessHandle:
    uv = find_uv()
    if uv is None:
        raise SubprocessStartError("uv not found — cannot start ACE-Step subprocess")
    env = build_env(mode, port, vram_budget_gb, gpu_id)
    stderr_path, stderr_file = _open_log_file(log_dir, mode)
    cmd = [*uv, "run", "acestep-api", "--port", str(port)]
    process = subprocess.Popen(  # noqa: S603
        cmd,
        env=env,
        cwd=checkpoint_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    handle = SubprocessHandle(
        process=process,
        stderr_path=stderr_path,
        port=port,
        stderr_file=stderr_file,
    )
    log_thread = threading.Thread(
        target=_stream_subprocess_logs,
        kwargs={
            "mode": mode,
            "process": process,
            "log_file": stderr_file,
            "on_log_line": on_log_line,
        },
        name=f"ace-step-log-{mode}",
        daemon=True,
    )
    log_thread.start()
    handle.log_thread = log_thread
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
        if process.stdout is not None:
            try:
                process.stdout.close()
            except OSError:
                pass
        if handle.log_thread is not None and handle.log_thread.is_alive():
            handle.log_thread.join(timeout=2.0)
            handle.log_thread = None
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
    gpu_id: int | None = None,
    log_dir: Path | None = None,
    on_log_line: LogLineSink | None = None,
) -> tuple[Loader, Unloader]:
    async def loader(mode: str) -> LoadedModel:
        port = inner_port_for_mode(base_port, mode)
        handle = await asyncio.to_thread(
            start_acestep_subprocess,
            mode,
            port=port,
            checkpoint_dir=checkpoint_dir,
            vram_budget_gb=vram_budget_gb,
            gpu_id=gpu_id,
            log_dir=log_dir,
            on_log_line=on_log_line,
        )
        return LoadedModel(mode=mode, handle=handle, port=handle.port)

    async def unloader(model: LoadedModel) -> None:
        handle = model.handle
        if isinstance(handle, SubprocessHandle):
            await asyncio.to_thread(stop_acestep_subprocess, handle)

    return loader, unloader


__all__ = [
    "MODEL_INNER_PORT_OFFSETS",
    "LogLineSink",
    "SubprocessHandle",
    "SubprocessStartError",
    "_read_stderr_tail",
    "build_env",
    "find_uv",
    "inner_port_for_mode",
    "is_acestep_healthy",
    "make_acestep_runner",
    "start_acestep_subprocess",
    "stop_acestep_subprocess",
    "wait_for_health",
]
