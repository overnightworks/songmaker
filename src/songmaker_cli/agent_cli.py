"""Bounded, cached login probes for mounted agent CLIs."""

from __future__ import annotations

import json
import os
import selectors
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from songmaker_cli.constants import (
    CLAUDE_CLI_AUTH_METHOD_FIELD,
    CLAUDE_CLI_LOGGED_IN_FIELD,
    CLAUDE_CLI_STATUS_ARGS,
    CLI_LOGIN_STATUS_CACHE_SECONDS,
    CLI_MAX_CONCURRENT_SPAWNS,
    CLI_OUTPUT_READ_LIMIT_BYTES,
    CLI_TERMINATION_GRACE_SECONDS,
    CODEX_CLI_BINARY,
    CODEX_CLI_LOGGED_IN_MARKER,
    CODEX_CLI_LOGGED_OUT_MARKER,
    CODEX_CLI_STATUS_ARGS,
    COWRITER_MODELS_TIMEOUT_SECONDS,
    GROK_CLI_BINARY,
    GROK_CLI_LOGGED_IN_MARKER,
    GROK_CLI_LOGGED_OUT_MARKER,
    GROK_CLI_MODEL_BULLETS,
    GROK_CLI_MODEL_LIST_MARKER,
    GROK_CLI_STATUS_ARGS,
    SECRET_ENV_KEYS,
)


class AgentCliUnavailableError(Exception):
    """Raised when a CLI's login response does not match its contract."""


@dataclass(frozen=True)
class CliLogin:
    """The subscription login reported by an agent CLI."""

    logged_in: bool
    auth_method: str | None


@dataclass(frozen=True)
class GrokCliStatus:
    """The login and model catalog emitted by ``grok models``."""

    login: CliLogin
    model_names: tuple[str, ...]


@dataclass(frozen=True)
class CliRun:
    """The bounded output and completion state of one CLI invocation."""

    returncode: int | None
    stdout: str
    stderr: str
    complete: bool


@dataclass
class _SpawnState:
    completed: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    process: subprocess.Popen[bytes] | None = None
    unavailable: bool = False
    abandoned: bool = False


LOGGED_OUT = CliLogin(logged_in=False, auth_method=None)
_spawn_admission = threading.BoundedSemaphore(CLI_MAX_CONCURRENT_SPAWNS)


def scrubbed_env() -> dict[str, str]:
    """Return the inherited environment without application secrets."""
    env = os.environ.copy()
    for key in SECRET_ENV_KEYS:
        env.pop(key, None)
    return env


class CachedProbe[T]:
    """A single-flight probe whose answer or failure has a bounded lifetime."""

    def __init__(self, probe: Callable[[], T]) -> None:
        self._probe = probe
        self._lock = threading.Lock()
        self._value: T | None = None
        self._failure: Exception | None = None
        self._answered_at = 0.0

    def get(self) -> T:
        with self._lock:
            if self._is_fresh():
                return self._answer()
            try:
                self._value = self._probe()
                self._failure = None
            except Exception as exc:  # noqa: BLE001 - preserve a probe's failure for its TTL
                self._value = None
                self._failure = exc
            self._answered_at = time.monotonic()
            return self._answer()

    def clear(self) -> None:
        with self._lock:
            self._value = None
            self._failure = None
            self._answered_at = 0.0

    def _is_fresh(self) -> bool:
        if self._value is None and self._failure is None:
            return False
        return time.monotonic() - self._answered_at < CLI_LOGIN_STATUS_CACHE_SECONDS

    def _answer(self) -> T:
        if self._failure is not None:
            raise self._failure
        if self._value is None:
            raise RuntimeError("A fresh CLI probe has no result")
        return self._value


def run_cli(binary: str, args: tuple[str, ...]) -> CliRun | None:
    """Run one CLI with bounded output and bounded process-group cleanup."""
    process = _spawn_cli(binary, args)
    if process is None:
        return None
    output: _CliOutput | None = None
    try:
        output = _read_bounded(process)
    finally:
        _reap_process_group(process)
    if output is None:
        return CliRun(returncode=process.returncode, stdout="", stderr="", complete=False)
    return CliRun(
        returncode=process.returncode,
        stdout=_decode(output.stdout),
        stderr=_decode(output.stderr),
        complete=output.complete,
    )


def _spawn_cli(binary: str, args: tuple[str, ...]) -> subprocess.Popen[bytes] | None:
    if not _spawn_admission.acquire(blocking=False):
        return None
    state = _SpawnState()

    def spawn() -> None:
        try:
            process = subprocess.Popen(  # noqa: S603 - argv comes from named probe constants
                [binary, *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=scrubbed_env(),
                start_new_session=True,
            )
        except OSError:
            with state.lock:
                state.unavailable = True
            state.completed.set()
        else:
            reap_late_process = False
            with state.lock:
                if state.abandoned:
                    reap_late_process = True
                else:
                    state.process = process
            if reap_late_process:
                _reap_process_group(process)
            state.completed.set()
        finally:
            _spawn_admission.release()

    threading.Thread(target=spawn, daemon=True).start()
    if state.completed.wait(timeout=COWRITER_MODELS_TIMEOUT_SECONDS):
        with state.lock:
            return state.process
    with state.lock:
        state.abandoned = True
        process = state.process
    if process is not None:
        _reap_process_group(process)
    return None


@dataclass(frozen=True)
class _CliOutput:
    stdout: bytearray
    stderr: bytearray
    complete: bool


def _cli_output(binary_name: str, args: tuple[str, ...]) -> str | None:
    binary = shutil.which(binary_name)
    return _combined_cli_output(binary, args)


def _combined_cli_output(binary: str | None, args: tuple[str, ...]) -> str | None:
    run = _successful_cli_run(binary, args)
    return None if run is None else run.stdout + run.stderr


def _claude_output(binary: str | None) -> str | None:
    run = _successful_cli_run(binary, CLAUDE_CLI_STATUS_ARGS)
    return None if run is None else run.stdout


def _successful_cli_run(binary: str | None, args: tuple[str, ...]) -> CliRun | None:
    if binary is None:
        return None
    run = run_cli(binary, args)
    if run is None or not run.complete or run.returncode != 0:
        return None
    return run


def _read_bounded(process: subprocess.Popen[bytes]) -> _CliOutput | None:
    deadline = time.monotonic() + COWRITER_MODELS_TIMEOUT_SECONDS
    stdout = bytearray()
    stderr = bytearray()
    with selectors.DefaultSelector() as selector:
        for stream, collected in ((process.stdout, stdout), (process.stderr, stderr)):
            if stream is not None:
                selector.register(stream, selectors.EVENT_READ, collected)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            for key, _ in selector.select(timeout=remaining):
                collected = key.data
                room = CLI_OUTPUT_READ_LIMIT_BYTES - len(stdout) - len(stderr)
                if room <= 0:
                    return _CliOutput(stdout, stderr, complete=False)
                chunk = key.fileobj.read1(room)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                collected.extend(chunk)
                if len(stdout) + len(stderr) >= CLI_OUTPUT_READ_LIMIT_BYTES:
                    return _CliOutput(stdout, stderr, complete=False)
    return _CliOutput(stdout, stderr, complete=True)


def _decode(collected: bytearray) -> str:
    return collected.decode(errors="replace")


def _reap_process_group(process: subprocess.Popen[bytes]) -> None:
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            stream.close()
    _signal_process_group(process.pid, signal.SIGTERM)
    _bounded_wait(process, CLI_TERMINATION_GRACE_SECONDS)
    if _process_group_exists(process.pid):
        _signal_process_group(process.pid, signal.SIGKILL)
    _bounded_wait(process, CLI_TERMINATION_GRACE_SECONDS)


def _signal_process_group(process_id: int, signal_number: signal.Signals) -> None:
    try:
        os.killpg(process_id, signal_number)
    except ProcessLookupError:
        return


def _process_group_exists(process_id: int) -> bool:
    try:
        os.killpg(process_id, 0)
    except ProcessLookupError:
        return False
    return True


def _bounded_wait(process: subprocess.Popen[bytes], timeout: float) -> bool:
    try:
        process.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False


def _probe_claude_login(binary: str) -> CliLogin:
    output = _claude_output(binary)
    if output is None:
        return LOGGED_OUT
    try:
        payload: Any = json.loads(output)
    except ValueError:
        return LOGGED_OUT
    if not isinstance(payload, dict):
        return LOGGED_OUT
    logged_in = payload.get(CLAUDE_CLI_LOGGED_IN_FIELD)
    if not isinstance(logged_in, bool):
        return LOGGED_OUT
    auth_method = payload.get(CLAUDE_CLI_AUTH_METHOD_FIELD)
    return CliLogin(
        logged_in=logged_in,
        auth_method=auth_method if isinstance(auth_method, str) else None,
    )


def _probe_grok_status() -> GrokCliStatus:
    output = _cli_output(GROK_CLI_BINARY, GROK_CLI_STATUS_ARGS)
    if output is None:
        return GrokCliStatus(login=LOGGED_OUT, model_names=())
    login = _parse_grok_login(output)
    if not login.logged_in:
        return GrokCliStatus(login=login, model_names=())
    return GrokCliStatus(login=login, model_names=_parse_grok_model_names(output))


def _parse_grok_login(output: str) -> CliLogin:
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith(GROK_CLI_LOGGED_IN_MARKER):
            account = stripped.removeprefix(GROK_CLI_LOGGED_IN_MARKER).rstrip(".")
            return CliLogin(logged_in=True, auth_method=account or None)
        if stripped == GROK_CLI_LOGGED_OUT_MARKER:
            return LOGGED_OUT
    raise AgentCliUnavailableError("grok models did not report its login status")


def _parse_grok_model_names(output: str) -> tuple[str, ...]:
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != GROK_CLI_MODEL_LIST_MARKER:
            continue
        names = tuple(_grok_model_names_under(lines[index + 1:]))
        if names:
            return names
        break
    raise AgentCliUnavailableError("grok models did not list a model name")


def _grok_model_names_under(lines: list[str]) -> list[str]:
    names: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or not stripped.startswith(GROK_CLI_MODEL_BULLETS):
            break
        name = stripped.split(maxsplit=1)[1].split(maxsplit=1)[0]
        names.append(name)
    return names


def _probe_codex_login() -> CliLogin:
    output = _cli_output(CODEX_CLI_BINARY, CODEX_CLI_STATUS_ARGS)
    if output is None:
        return LOGGED_OUT
    return _parse_codex_login(output)


def _parse_codex_login(output: str) -> CliLogin:
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith(CODEX_CLI_LOGGED_IN_MARKER):
            account = stripped.removeprefix(CODEX_CLI_LOGGED_IN_MARKER)
            return CliLogin(logged_in=True, auth_method=account or None)
        if stripped == CODEX_CLI_LOGGED_OUT_MARKER:
            return LOGGED_OUT
    raise AgentCliUnavailableError("codex login status did not report its login status")


_grok_status_probe = CachedProbe(_probe_grok_status)
_codex_login_probe = CachedProbe(_probe_codex_login)
_claude_login_probes: dict[str, CachedProbe[CliLogin]] = {}
_claude_login_probes_lock = threading.Lock()


def claude_cli_login(binary: str | None) -> CliLogin:
    if binary is None:
        return LOGGED_OUT
    with _claude_login_probes_lock:
        probe = _claude_login_probes.setdefault(
            binary,
            CachedProbe(lambda: _probe_claude_login(binary)),
        )
    return probe.get()


def grok_cli_status() -> GrokCliStatus:
    return _grok_status_probe.get()


def codex_cli_login() -> CliLogin:
    return _codex_login_probe.get()


def clear_claude_cli_login_cache() -> None:
    with _claude_login_probes_lock:
        _claude_login_probes.clear()


def clear_agent_cli_caches() -> None:
    clear_claude_cli_login_cache()
    _grok_status_probe.clear()
    _codex_login_probe.clear()
