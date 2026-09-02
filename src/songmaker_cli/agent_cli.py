"""Bounded, cached login probes for mounted agent CLIs."""

from __future__ import annotations

import concurrent.futures
import json
import logging
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


class CliProbeBudgetExceeded(AgentCliUnavailableError):
    """Raised when one caller outwaits a still-running cached probe."""


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
    abandoned: bool = False


LOGGED_OUT = CliLogin(logged_in=False, auth_method=None)

# A probe can spend its answer budget and then two termination grace periods
# reaping its process group. Give callers enough time to receive that outcome.
CLI_PROBE_CALLER_TIMEOUT_MARGIN_SECONDS = 0.1
CLI_PROBE_CALLER_TIMEOUT_SECONDS = (
    COWRITER_MODELS_TIMEOUT_SECONDS
    + (2 * CLI_TERMINATION_GRACE_SECONDS)
    + CLI_PROBE_CALLER_TIMEOUT_MARGIN_SECONDS
)

log = logging.getLogger(__name__)


def scrubbed_env() -> dict[str, str]:
    """Return the inherited environment without application secrets."""
    env = os.environ.copy()
    for key in SECRET_ENV_KEYS:
        env.pop(key, None)
    return env


class CachedProbe[T]:
    """A cached probe with a published future for each cold flight.

    The state lock only protects the cache and the future's publication.  The
    probe runs without it, so every caller waits at most its own answer budget
    instead of inheriting a predecessor's whole probe.
    """

    def __init__(self, probe: Callable[[], T]) -> None:
        self._probe = probe
        self._lock = threading.Lock()
        self._value: T | None = None
        self._failure: Exception | None = None
        self._answered_at = 0.0
        self._inflight: concurrent.futures.Future[T] | None = None
        self._generation = 0

    def get(self) -> T:
        with self._lock:
            if self._is_fresh():
                return self._answer()
            future = self._inflight
            if future is None:
                future = concurrent.futures.Future()
                self._inflight = future
                threading.Thread(
                    target=self._run_and_resolve,
                    args=(future, self._generation),
                    daemon=True,
                ).start()

        deadline = time.monotonic() + CLI_PROBE_CALLER_TIMEOUT_SECONDS
        try:
            return future.result(timeout=max(deadline - time.monotonic(), 0))
        except concurrent.futures.TimeoutError as exc:
            raise CliProbeBudgetExceeded(
                "agent CLI probe did not answer within its caller budget",
            ) from exc

    def clear(self) -> None:
        with self._lock:
            self._value = None
            self._failure = None
            self._answered_at = 0.0
            self._generation += 1
            self._inflight = None

    def _run_and_resolve(
        self, future: concurrent.futures.Future[T], generation: int,
    ) -> None:
        try:
            result = self._probe()
        except Exception as exc:  # noqa: BLE001 - preserve a probe's failure for its TTL
            with self._lock:
                if generation == self._generation:
                    self._value = None
                    self._failure = exc
                    self._answered_at = time.monotonic()
                    if self._inflight is future:
                        self._inflight = None
            future.set_exception(exc)
        else:
            with self._lock:
                if generation == self._generation:
                    self._value = result
                    self._failure = None
                    self._answered_at = time.monotonic()
                    if self._inflight is future:
                        self._inflight = None
            future.set_result(result)

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
    """Run one CLI with one answer budget and separate bounded cleanup."""
    deadline = time.monotonic() + COWRITER_MODELS_TIMEOUT_SECONDS
    process = _spawn_cli(binary, args, deadline)
    if process is None:
        return None
    output: _CliOutput | None = None
    try:
        output = _read_bounded(process, deadline)
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


def _spawn_cli(
    binary: str, args: tuple[str, ...], deadline: float,
) -> subprocess.Popen[bytes] | None:
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

    threading.Thread(target=spawn, daemon=True).start()
    remaining = max(deadline - time.monotonic(), 0)
    if state.completed.wait(timeout=remaining):
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
    # Grok and Codex place status diagnostics on either stream across releases;
    # their line contracts must not become dependent on that presentation choice.
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


def _read_bounded(process: subprocess.Popen[bytes], deadline: float) -> _CliOutput | None:
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
        if not _wait_for_process_group_exit(process, CLI_TERMINATION_GRACE_SECONDS):
            log.warning("agent CLI process group %s survived its SIGKILL grace period", process.pid)


def _wait_for_process_group_exit(process: subprocess.Popen[bytes], timeout: float) -> bool:
    """Wait until SIGKILL has made the whole group unaddressable.

    Waiting only for the direct child can return while one of its children
    still runs, which would make a completed probe lie about its cleanup.
    """
    deadline = time.monotonic() + timeout
    while _process_group_exists(process.pid):
        # `poll()` performs the non-blocking waitpid that reaps the direct
        # child. Without it, its zombie can keep the process group addressable
        # after SIGKILL even though no runnable process remains.
        process.poll()
        if not _process_group_exists(process.pid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(min(0.01, max(deadline - time.monotonic(), 0)))
    return True


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
    # Claude offers structured status, so accepting a near-match would turn a
    # changed authentication contract into a false logged-in report.
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
        # These exact markers reject prose changes rather than guessing a
        # subscription state from incidental account text.
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
        # Codex has no structured status output; its documented markers are
        # deliberately narrower than a heuristic that could forge a login.
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
    try:
        return probe.get()
    except CliProbeBudgetExceeded:
        return LOGGED_OUT


def grok_cli_status() -> GrokCliStatus:
    try:
        return _grok_status_probe.get()
    except CliProbeBudgetExceeded:
        return GrokCliStatus(login=LOGGED_OUT, model_names=())


def codex_cli_login() -> CliLogin:
    try:
        return _codex_login_probe.get()
    except CliProbeBudgetExceeded:
        return LOGGED_OUT


def clear_claude_cli_login_cache() -> None:
    with _claude_login_probes_lock:
        _claude_login_probes.clear()


def clear_agent_cli_caches() -> None:
    clear_claude_cli_login_cache()
    _grok_status_probe.clear()
    _codex_login_probe.clear()
