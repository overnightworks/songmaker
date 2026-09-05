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
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, Literal, NotRequired, Required, Sequence, TypedDict, Unpack

from songmaker_cli.constants import (
    CLAUDE_CLI_AUTH_METHOD_FIELD,
    CLAUDE_CLI_LOGGED_IN_FIELD,
    CLAUDE_CLI_STATUS_ARGS,
    CLI_LOGIN_STATUS_CACHE_SECONDS,
    CLI_OUTPUT_READ_LIMIT_BYTES,
    CLI_TERMINATION_GRACE_SECONDS,
    CODEX_CLI_AUTH_FILE,
    CODEX_CLI_BINARY,
    CODEX_CLI_LOGGED_IN_MARKER,
    CODEX_CLI_LOGGED_OUT_MARKER,
    CODEX_CLI_STATUS_ARGS,
    COWRITER_MODELS_TIMEOUT_SECONDS,
    GROK_CLI_AUTH_FILE,
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


class CliRunReason(str, Enum):
    """Why a bounded CLI invocation did or did not complete."""

    SPAWN_FAILED = "spawn_failed"
    DEADLINE_BEFORE_SPAWN = "deadline_before_spawn"
    DEADLINE_WHILE_WRITING = "deadline_while_writing"
    DEADLINE_WHILE_READING = "deadline_while_reading"
    IO_ERROR = "io_error"
    OUTPUT_LIMIT_REACHED = "output_limit_reached"
    OUTPUT_CHANNEL_FULL = "output_channel_full"
    CANCELLED = "cancelled"
    CLEANUP_OVERRAN = "cleanup_overran"
    COMPLETE = "complete"


@dataclass(frozen=True)
class CliRunOutcome:
    """The result of a bounded CLI invocation and its cleanup."""

    started: bool
    spawn_error: BaseException | None
    returncode: int | None
    stdout: str
    stderr: str
    complete: bool
    became_zombie: bool
    reason: CliRunReason
    io_error: OSError | None = None


class CliLineChannel:
    """A bounded stream of complete stdout lines from one CLI run."""

    def __init__(self, maximum_lines: int) -> None:
        if maximum_lines < 1:
            raise ValueError("CLI line channel must hold at least one line")
        self._maximum_lines = maximum_lines
        self._lines: deque[bytes] = deque()
        self._outcome: CliRunOutcome | None = None
        self._abort_requested = threading.Event()
        self._condition = threading.Condition()

    def request_abort(self) -> None:
        self._abort_requested.set()
        with self._condition:
            self._lines.clear()
            self._condition.notify_all()

    def abort_requested(self) -> bool:
        return self._abort_requested.is_set()

    def receive(self, timeout: float | None = None) -> bytes | CliRunOutcome:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while True:
                if self._lines:
                    return self._lines.popleft()
                if self._outcome is not None:
                    return self._outcome
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("CLI line channel did not produce an item in time")
                self._condition.wait(timeout=remaining)

    def _send(self, line: bytes) -> bool:
        with self._condition:
            if self._abort_requested.is_set() or len(self._lines) >= self._maximum_lines:
                return False
            self._lines.append(line)
            self._condition.notify_all()
            return True

    def _close(self, outcome: CliRunOutcome) -> None:
        with self._condition:
            if not outcome.complete:
                self._lines.clear()
            self._outcome = outcome
            self._condition.notify_all()


@dataclass
class _BoundedRunState:
    started: threading.Event = field(default_factory=threading.Event)
    completed: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    outcome: CliRunOutcome | None = None


LOGGED_OUT = CliLogin(logged_in=False, auth_method=None)

# A probe can spend its answer budget and then two termination grace periods
# reaping its process group. Give callers enough time to receive that outcome.
CLI_PROBE_CALLER_TIMEOUT_MARGIN_SECONDS = 0.1
CLI_PROBE_CALLER_TIMEOUT_SECONDS = (
    COWRITER_MODELS_TIMEOUT_SECONDS
    + (2 * CLI_TERMINATION_GRACE_SECONDS)
    + CLI_PROBE_CALLER_TIMEOUT_MARGIN_SECONDS
)
_BACKGROUND_REAP_POLL_SECONDS: Final = 0.1

log = logging.getLogger(__name__)

GROK_CLI_CREDENTIALS_INVALID_DETAIL: Final = "could not parse Grok CLI credentials"
CODEX_CLI_CREDENTIALS_INVALID_DETAIL: Final = "could not parse Codex CLI credentials"


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
        return self.refresh()

    def refresh(self) -> T:
        """Start or join one single-flight refresh."""
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
        self,
        future: concurrent.futures.Future[T],
        generation: int,
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
    outcome = run_cli_bounded(
        (binary, *args),
        stdin_payload=None,
        read="all",
        deadline=deadline,
        output_read_limit_bytes=CLI_OUTPUT_READ_LIMIT_BYTES,
    )
    if outcome.reason in {
        CliRunReason.SPAWN_FAILED,
        CliRunReason.DEADLINE_BEFORE_SPAWN,
    }:
        return None
    return CliRun(
        returncode=outcome.returncode,
        stdout=outcome.stdout,
        stderr=outcome.stderr,
        complete=outcome.complete,
    )


class _CliRunKeywordArgs(TypedDict, total=False):
    stdin_payload: Required[bytes | None]
    read: Required[Literal["all", "first_line"]]
    deadline: Required[float]
    stderr: NotRequired[Literal["capture", "devnull"]]
    output_read_limit_bytes: NotRequired[int | None]
    cleanup_margin_seconds: NotRequired[float | None]
    on_spawned: NotRequired[Callable[[int], None] | None]
    on_spawn_failed: NotRequired[Callable[[], None] | None]
    on_reaped: NotRequired[Callable[[int, bool], None] | None]
    stdout_line_channel: NotRequired[CliLineChannel | None]
    prompt_file_bytes: NotRequired[bytes | None]
    prompt_file_arg_index: NotRequired[int | None]
    cwd: NotRequired[str | None]
    extra_env: NotRequired[Mapping[str, str] | None]
    unset_env: NotRequired[Collection[str]]


@dataclass(frozen=True)
class _CliRunRequest:
    stdin_payload: bytes | None
    read: Literal["all", "first_line"]
    deadline: float
    stderr: Literal["capture", "devnull"]
    output_read_limit_bytes: int
    on_spawned: Callable[[int], None] | None
    on_spawn_failed: Callable[[], None] | None
    on_reaped: Callable[[int, bool], None] | None
    stdout_line_channel: CliLineChannel | None
    prompt_file_bytes: bytes | None
    prompt_file_arg_index: int | None
    cwd: str | None
    extra_env: Mapping[str, str] | None
    unset_env: Collection[str]


def run_cli_bounded(
    argv: Sequence[str],
    **options: Unpack[_CliRunKeywordArgs],
) -> CliRunOutcome:
    """Run a CLI with bounded input, output, and caller cleanup waits.

    The child deliberately receives no terminal stdin: its pipe is closed
    immediately when no input payload is supplied.
    """
    output_read_limit_bytes = options.get("output_read_limit_bytes")
    request = _CliRunRequest(
        stdin_payload=options["stdin_payload"],
        read=options["read"],
        deadline=options["deadline"],
        stderr=options.get("stderr", "capture"),
        output_read_limit_bytes=(
            CLI_OUTPUT_READ_LIMIT_BYTES
            if output_read_limit_bytes is None
            else output_read_limit_bytes
        ),
        on_spawned=options.get("on_spawned"),
        on_spawn_failed=options.get("on_spawn_failed"),
        on_reaped=options.get("on_reaped"),
        stdout_line_channel=options.get("stdout_line_channel"),
        prompt_file_bytes=options.get("prompt_file_bytes"),
        prompt_file_arg_index=options.get("prompt_file_arg_index"),
        cwd=options.get("cwd"),
        extra_env=options.get("extra_env"),
        unset_env=tuple(options.get("unset_env", ())),
    )
    state = _BoundedRunState()
    threading.Thread(
        target=_run_cli_bounded,
        args=(
            state,
            tuple(argv),
            request,
        ),
        daemon=True,
    ).start()
    if not state.completed.wait(timeout=max(request.deadline - time.monotonic(), 0)):
        if not state.started.is_set():
            return CliRunOutcome(
                started=False,
                spawn_error=None,
                returncode=None,
                stdout="",
                stderr="",
                complete=False,
                became_zombie=False,
                reason=CliRunReason.DEADLINE_BEFORE_SPAWN,
            )
        cleanup_margin = options.get("cleanup_margin_seconds")
        if cleanup_margin is None:
            cleanup_margin = (
                2 * CLI_TERMINATION_GRACE_SECONDS + CLI_PROBE_CALLER_TIMEOUT_MARGIN_SECONDS
            )
        if not state.completed.wait(timeout=cleanup_margin):
            return CliRunOutcome(
                started=True,
                spawn_error=None,
                returncode=None,
                stdout="",
                stderr="",
                complete=False,
                became_zombie=False,
                reason=CliRunReason.CLEANUP_OVERRAN,
            )
    with state.lock:
        if state.outcome is None:
            raise RuntimeError("bounded CLI runner completed without an outcome")
        return state.outcome


@dataclass(frozen=True)
class _CliOutput:
    stdout: bytearray
    stderr: bytearray
    complete: bool
    reason: CliRunReason
    io_error: OSError | None = None


@dataclass
class _CliExchange:
    stdout: bytearray
    stderr: bytearray
    pending_stdin: memoryview
    stdout_line_remainder: bytearray


def _run_cli_bounded(
    state: _BoundedRunState,
    argv: tuple[str, ...],
    request: _CliRunRequest,
) -> None:
    process, prompt_file_path, outcome = _start_bounded_cli(
        argv,
        request.stderr,
        request.on_spawn_failed,
        request.prompt_file_bytes,
        request.prompt_file_arg_index,
        request.cwd,
        request.extra_env,
        request.unset_env,
    )
    output = _CliOutput(
        bytearray(),
        bytearray(),
        complete=False,
        reason=CliRunReason.IO_ERROR,
    )
    try:
        if process is not None:
            state.started.set()
            _notify_spawned(request.on_spawned, process.pid)
            output = _exchange_bounded(
                process,
                request.stdin_payload,
                request.read,
                request.deadline,
                request.output_read_limit_bytes,
                request.stdout_line_channel,
            )
    finally:
        if process is not None:
            outcome = _finished_bounded_cli_run(process, output, request.on_reaped)
        outcome = _cleanup_bounded_cli_prompt_file(prompt_file_path, outcome)
        if outcome is None:
            raise RuntimeError("bounded CLI runner exited without an outcome")
        _publish_bounded_outcome(state, outcome)
        if request.stdout_line_channel is not None:
            request.stdout_line_channel._close(outcome)


def _start_bounded_cli(
    argv: tuple[str, ...],
    stderr: Literal["capture", "devnull"],
    on_spawn_failed: Callable[[], None] | None,
    prompt_file_bytes: bytes | None,
    prompt_file_arg_index: int | None,
    cwd: str | None,
    extra_env: Mapping[str, str] | None,
    unset_env: Collection[str],
) -> tuple[subprocess.Popen[bytes] | None, str | None, CliRunOutcome | None]:
    prompt_file_path: str | None = None
    try:
        command, prompt_file_path = _with_private_prompt_file(
            argv,
            prompt_file_bytes,
            prompt_file_arg_index,
        )
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if stderr == "capture" else subprocess.DEVNULL,
            env=_child_env(extra_env, unset_env),
            start_new_session=True,
            cwd=cwd,
        )
    except Exception as error:
        _notify_spawn_failed(on_spawn_failed)
        return None, prompt_file_path, _spawn_failure_outcome(error)
    return process, prompt_file_path, None


def _spawn_failure_outcome(error: BaseException) -> CliRunOutcome:
    return CliRunOutcome(
        started=False,
        spawn_error=error,
        returncode=None,
        stdout="",
        stderr="",
        complete=False,
        became_zombie=False,
        reason=CliRunReason.SPAWN_FAILED,
    )


def _finished_bounded_cli_run(
    process: subprocess.Popen[bytes],
    output: _CliOutput,
    on_reaped: Callable[[int, bool], None] | None,
) -> CliRunOutcome:
    became_zombie = _reap_process_group(process)
    if became_zombie and on_reaped is not None:
        threading.Thread(
            target=_reap_in_background,
            args=(process, on_reaped),
            daemon=True,
        ).start()
    else:
        _notify_reaped(on_reaped, process.pid, became_zombie=False)
    return CliRunOutcome(
        started=True,
        spawn_error=None,
        returncode=process.returncode,
        stdout="" if output.reason in _DEADLINE_REASONS else _decode(output.stdout),
        stderr="" if output.reason in _DEADLINE_REASONS else _decode(output.stderr),
        complete=output.complete,
        became_zombie=became_zombie,
        reason=output.reason,
        io_error=output.io_error,
    )


def _cleanup_bounded_cli_prompt_file(
    prompt_file_path: str | None,
    outcome: CliRunOutcome | None,
) -> CliRunOutcome | None:
    if prompt_file_path is None:
        return outcome
    try:
        _unlink_prompt_file(prompt_file_path)
    except OSError as error:
        if outcome is None:
            raise RuntimeError("bounded CLI runner exited without an outcome")
        return CliRunOutcome(
            started=outcome.started,
            spawn_error=outcome.spawn_error,
            returncode=outcome.returncode,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            complete=False,
            became_zombie=outcome.became_zombie,
            reason=CliRunReason.IO_ERROR,
            io_error=error,
        )
    return outcome


def _child_env(
    extra_env: Mapping[str, str] | None,
    unset_env: Collection[str] = (),
) -> dict[str, str]:
    """Build the scrubbed child environment with explicit local additions."""
    env = scrubbed_env()
    if extra_env is not None:
        env.update(extra_env)
    for key in unset_env:
        env.pop(key, None)
    return env


def _with_private_prompt_file(
    argv: tuple[str, ...],
    prompt_file_bytes: bytes | None,
    prompt_file_arg_index: int | None,
) -> tuple[tuple[str, ...], str | None]:
    if prompt_file_bytes is None:
        if prompt_file_arg_index is not None:
            raise ValueError("A prompt file index requires prompt bytes")
        return argv, None
    if prompt_file_arg_index is None:
        raise ValueError("Prompt bytes require a prompt file index")
    if prompt_file_arg_index < 0 or prompt_file_arg_index >= len(argv):
        raise ValueError("Prompt file index is outside the CLI command")
    descriptor, path = tempfile.mkstemp(prefix="songmaker-cli-prompt-")
    try:
        with os.fdopen(descriptor, "wb") as prompt_file:
            prompt_file.write(prompt_file_bytes)
        os.chmod(path, 0o600)
    except BaseException:
        _unlink_prompt_file(path)
        raise
    command = list(argv)
    command[prompt_file_arg_index] = path
    return tuple(command), path


def _unlink_prompt_file(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return


_DEADLINE_REASONS = frozenset(
    {
        CliRunReason.DEADLINE_WHILE_WRITING,
        CliRunReason.DEADLINE_WHILE_READING,
    }
)


def _publish_bounded_outcome(state: _BoundedRunState, outcome: CliRunOutcome) -> None:
    with state.lock:
        state.outcome = outcome
    state.completed.set()


def _notify_spawned(callback: Callable[[int], None] | None, process_id: int) -> None:
    if callback is not None:
        callback(process_id)


def _notify_spawn_failed(callback: Callable[[], None] | None) -> None:
    if callback is not None:
        callback()


def _notify_reaped(
    callback: Callable[[int, bool], None] | None,
    process_id: int,
    became_zombie: bool,
) -> None:
    if callback is not None:
        callback(process_id, became_zombie)


def _exchange_bounded(
    process: subprocess.Popen[bytes],
    stdin_payload: bytes | None,
    read: Literal["all", "first_line"],
    deadline: float,
    output_read_limit_bytes: int,
    stdout_line_channel: CliLineChannel | None,
) -> _CliOutput:
    exchange = _CliExchange(
        stdout=bytearray(),
        stderr=bytearray(),
        pending_stdin=memoryview(stdin_payload) if stdin_payload else memoryview(b""),
        stdout_line_remainder=bytearray(),
    )
    try:
        with selectors.DefaultSelector() as selector:
            _register_exchange_streams(selector, process, exchange)
            return _exchange_until_complete(
                selector,
                exchange,
                read,
                deadline,
                output_read_limit_bytes,
                stdout_line_channel,
            )
    except OSError as error:
        return _CliOutput(
            exchange.stdout,
            exchange.stderr,
            complete=False,
            reason=CliRunReason.IO_ERROR,
            io_error=error,
        )


def _register_exchange_streams(
    selector: selectors.BaseSelector,
    process: subprocess.Popen[bytes],
    exchange: _CliExchange,
) -> None:
    stdin = process.stdin
    if stdin is not None and not exchange.pending_stdin:
        _close_stdin(process)
    _register_output_streams(selector, process)
    if stdin is not None and exchange.pending_stdin:
        os.set_blocking(stdin.fileno(), False)
        selector.register(stdin, selectors.EVENT_WRITE, "stdin")


def _register_output_streams(
    selector: selectors.BaseSelector,
    process: subprocess.Popen[bytes],
) -> None:
    for stream, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
        if stream is not None:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)


def _exchange_until_complete(
    selector: selectors.BaseSelector,
    exchange: _CliExchange,
    read: Literal["all", "first_line"],
    deadline: float,
    output_read_limit_bytes: int,
    stdout_line_channel: CliLineChannel | None,
) -> _CliOutput:
    while selector.get_map():
        terminal_output = _exchange_terminal_output(exchange, stdout_line_channel, deadline)
        if terminal_output is not None:
            return terminal_output
        events = selector.select(timeout=min(deadline - time.monotonic(), 0.05))
        if not events:
            if time.monotonic() >= deadline:
                return _deadline_output(exchange.stdout, exchange.stderr, exchange.pending_stdin)
            continue
        for key, _ in events:
            event_output = _exchange_event(
                selector,
                key,
                exchange,
                read,
                output_read_limit_bytes,
                stdout_line_channel,
            )
            if event_output is not None:
                return event_output
    return _CliOutput(
        exchange.stdout,
        exchange.stderr,
        complete=True,
        reason=CliRunReason.COMPLETE,
    )


def _exchange_terminal_output(
    exchange: _CliExchange,
    stdout_line_channel: CliLineChannel | None,
    deadline: float,
) -> _CliOutput | None:
    if stdout_line_channel is not None and stdout_line_channel.abort_requested():
        return _CliOutput(
            exchange.stdout,
            exchange.stderr,
            complete=False,
            reason=CliRunReason.CANCELLED,
        )
    if deadline - time.monotonic() <= 0:
        return _deadline_output(exchange.stdout, exchange.stderr, exchange.pending_stdin)
    return None


def _exchange_event(
    selector: selectors.BaseSelector,
    key: selectors.SelectorKey,
    exchange: _CliExchange,
    read: Literal["all", "first_line"],
    output_read_limit_bytes: int,
    stdout_line_channel: CliLineChannel | None,
) -> _CliOutput | None:
    if key.data == "stdin":
        return _write_pending_stdin(selector, key, exchange)
    return _read_cli_output(
        selector,
        key,
        exchange,
        read,
        output_read_limit_bytes,
        stdout_line_channel,
    )


def _write_pending_stdin(
    selector: selectors.BaseSelector,
    key: selectors.SelectorKey,
    exchange: _CliExchange,
) -> _CliOutput | None:
    written = os.write(key.fileobj.fileno(), exchange.pending_stdin)
    if written <= 0:
        return _CliOutput(
            exchange.stdout,
            exchange.stderr,
            complete=False,
            reason=CliRunReason.IO_ERROR,
        )
    exchange.pending_stdin = exchange.pending_stdin[written:]
    if exchange.pending_stdin:
        return None
    selector.unregister(key.fileobj)
    key.fileobj.close()
    return None


def _read_cli_output(
    selector: selectors.BaseSelector,
    key: selectors.SelectorKey,
    exchange: _CliExchange,
    read: Literal["all", "first_line"],
    output_read_limit_bytes: int,
    stdout_line_channel: CliLineChannel | None,
) -> _CliOutput | None:
    room = output_read_limit_bytes - len(exchange.stdout) - len(exchange.stderr)
    if room <= 0:
        return _output_limit_reached(exchange)
    chunk = os.read(key.fileobj.fileno(), room)
    if not chunk:
        return _finish_output_stream(selector, key, exchange, read, stdout_line_channel)
    if read == "first_line" and key.data == "stdout":
        first_line_output = _first_line_output(exchange.stdout, exchange.stderr, chunk)
        if first_line_output is not None:
            return first_line_output
    return _collect_output_chunk(
        key.data,
        exchange,
        chunk,
        output_read_limit_bytes,
        stdout_line_channel,
    )


def _finish_output_stream(
    selector: selectors.BaseSelector,
    key: selectors.SelectorKey,
    exchange: _CliExchange,
    read: Literal["all", "first_line"],
    stdout_line_channel: CliLineChannel | None,
) -> _CliOutput | None:
    selector.unregister(key.fileobj)
    if key.data == "stdout" and stdout_line_channel is not None:
        channel_output = _flush_stdout_line_remainder(exchange, stdout_line_channel)
        if channel_output is not None:
            return channel_output
    if read == "first_line" and key.data == "stdout":
        return _CliOutput(
            exchange.stdout,
            exchange.stderr,
            complete=True,
            reason=CliRunReason.COMPLETE,
        )
    return None


def _first_line_output(
    stdout: bytearray,
    stderr: bytearray,
    chunk: bytes,
) -> _CliOutput | None:
    newline = chunk.find(b"\n")
    if newline < 0:
        return None
    stdout.extend(chunk[: newline + 1])
    return _CliOutput(stdout, stderr, complete=True, reason=CliRunReason.COMPLETE)


def _collect_output_chunk(
    stream_name: str,
    exchange: _CliExchange,
    chunk: bytes,
    output_read_limit_bytes: int,
    stdout_line_channel: CliLineChannel | None,
) -> _CliOutput | None:
    collected = exchange.stdout if stream_name == "stdout" else exchange.stderr
    collected.extend(chunk)
    if stream_name == "stdout" and stdout_line_channel is not None:
        channel_output = _send_complete_stdout_lines(exchange, stdout_line_channel, chunk)
        if channel_output is not None:
            return channel_output
    if len(exchange.stdout) + len(exchange.stderr) >= output_read_limit_bytes:
        return _output_limit_reached(exchange)
    return None


def _send_complete_stdout_lines(
    exchange: _CliExchange,
    stdout_line_channel: CliLineChannel,
    chunk: bytes,
) -> _CliOutput | None:
    exchange.stdout_line_remainder.extend(chunk)
    while b"\n" in exchange.stdout_line_remainder:
        newline = exchange.stdout_line_remainder.index(b"\n") + 1
        line = bytes(exchange.stdout_line_remainder[:newline])
        del exchange.stdout_line_remainder[:newline]
        if not stdout_line_channel._send(line):
            return _stdout_channel_delivery_failure(exchange, stdout_line_channel)
    return None


def _flush_stdout_line_remainder(
    exchange: _CliExchange,
    stdout_line_channel: CliLineChannel,
) -> _CliOutput | None:
    if not exchange.stdout_line_remainder:
        return None
    line = bytes(exchange.stdout_line_remainder)
    exchange.stdout_line_remainder.clear()
    if stdout_line_channel._send(line):
        return None
    return _stdout_channel_delivery_failure(exchange, stdout_line_channel)


def _stdout_channel_delivery_failure(
    exchange: _CliExchange,
    stdout_line_channel: CliLineChannel,
) -> _CliOutput:
    if stdout_line_channel.abort_requested():
        reason = CliRunReason.CANCELLED
    else:
        reason = CliRunReason.OUTPUT_CHANNEL_FULL
    return _CliOutput(exchange.stdout, exchange.stderr, complete=False, reason=reason)


def _output_limit_reached(exchange: _CliExchange) -> _CliOutput:
    return _CliOutput(
        exchange.stdout,
        exchange.stderr,
        complete=False,
        reason=CliRunReason.OUTPUT_LIMIT_REACHED,
    )


def _close_stdin(process: subprocess.Popen[bytes]) -> None:
    if process.stdin is not None:
        process.stdin.close()


def _deadline_output(
    stdout: bytearray,
    stderr: bytearray,
    pending_stdin: memoryview,
) -> _CliOutput:
    reason = (
        CliRunReason.DEADLINE_WHILE_WRITING
        if pending_stdin
        else CliRunReason.DEADLINE_WHILE_READING
    )
    return _CliOutput(stdout, stderr, complete=False, reason=reason)


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


def _decode(collected: bytearray) -> str:
    return collected.decode(errors="replace")


def _reap_process_group(process: subprocess.Popen[bytes]) -> bool:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()
    _signal_process_group(process.pid, signal.SIGTERM)
    _bounded_wait(process, CLI_TERMINATION_GRACE_SECONDS)
    if _process_group_exists(process.pid):
        _signal_process_group(process.pid, signal.SIGKILL)
        if not _wait_for_process_group_exit(process, CLI_TERMINATION_GRACE_SECONDS):
            log.warning("agent CLI process group %s survived its SIGKILL grace period", process.pid)
            return True
    return False


def _reap_in_background(
    process: subprocess.Popen[bytes],
    on_reaped: Callable[[int, bool], None] | None,
) -> None:
    try:
        while _process_group_exists(process.pid):
            process.poll()
            time.sleep(_BACKGROUND_REAP_POLL_SECONDS)
    except OSError:
        log.exception("background reap of agent CLI process group %s failed", process.pid)
    finally:
        _notify_reaped(on_reaped, process.pid, became_zombie=True)


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


def grok_cli_token_is_present() -> bool:
    """Whether the Grok CLI credential mirror contains a non-empty access token."""
    try:
        raw_auth = Path(GROK_CLI_AUTH_FILE).read_text()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise AgentCliUnavailableError("could not read Grok CLI credentials") from exc
    try:
        document = json.loads(raw_auth)
    except json.JSONDecodeError as exc:
        raise AgentCliUnavailableError(GROK_CLI_CREDENTIALS_INVALID_DETAIL) from exc
    if not isinstance(document, dict):
        raise AgentCliUnavailableError(GROK_CLI_CREDENTIALS_INVALID_DETAIL)
    for realm in document.values():
        if not isinstance(realm, dict):
            raise AgentCliUnavailableError(GROK_CLI_CREDENTIALS_INVALID_DETAIL)
        key = realm.get("key")
        if key is None:
            continue
        if not isinstance(key, str):
            raise AgentCliUnavailableError(GROK_CLI_CREDENTIALS_INVALID_DETAIL)
        if key:
            return True
    return False


def codex_cli_access_token_is_present() -> bool:
    """Whether the Codex CLI credential mirror contains a non-empty access token."""
    try:
        raw_auth = Path(CODEX_CLI_AUTH_FILE).read_text()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise AgentCliUnavailableError("could not read Codex CLI credentials") from exc
    try:
        document = json.loads(raw_auth)
    except json.JSONDecodeError as exc:
        raise AgentCliUnavailableError(CODEX_CLI_CREDENTIALS_INVALID_DETAIL) from exc
    if not isinstance(document, dict):
        raise AgentCliUnavailableError(CODEX_CLI_CREDENTIALS_INVALID_DETAIL)
    if "tokens" not in document:
        return False
    tokens = document["tokens"]
    if not isinstance(tokens, dict):
        raise AgentCliUnavailableError(CODEX_CLI_CREDENTIALS_INVALID_DETAIL)
    if "access_token" not in tokens:
        return False
    access_token = tokens["access_token"]
    if not isinstance(access_token, str):
        raise AgentCliUnavailableError(CODEX_CLI_CREDENTIALS_INVALID_DETAIL)
    return bool(access_token)


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
        names = tuple(_grok_model_names_under(lines[index + 1 :]))
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
