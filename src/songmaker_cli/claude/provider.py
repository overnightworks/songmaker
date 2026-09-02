"""Claude provider — unified interface for CLI and API backends.

Both the lyrical_coherence scorer and the chat co-writing endpoint
use this module. The backend is selected based on available credentials:

1. API key provided (env var) → ApiProvider
2. Claude CLI on PATH or in VS Code → CliProvider
3. Neither → raises UnavailableError
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, Field

from songmaker_cli.constants import (
    CLAUDE_CLI_LOGIN_STATUS_CACHE_SECONDS,
    CLAUDE_CLI_NO_TOOL_SURFACE_TIMEOUT_SECONDS,
    CLAUDE_CLI_TOOL_SURFACE_FAILURE_CACHE_SECONDS,
    CLAUDE_CLI_TOOL_SURFACE_TIMEOUT_SECONDS,
    CLAUDE_CLI_ZOMBIE_REAP_TIMEOUT_SECONDS,
    COWRITER_CLAUDE_CLI_MODEL_LIST_MARKER,
    COWRITER_MODELS_TIMEOUT_SECONDS,
    SECRET_ENV_KEYS,
)
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

_sync_clients: dict[str, object] = {}
_async_clients: dict[str, object] = {}
_client_lock = threading.Lock()

_cli_login_status_cache: CliLoginStatus | None = None
_cli_login_status_cache_at: float = 0.0
_cli_login_status_lock = threading.Lock()

MCP_SERVER_NAME: Final = "songmaker"
COWRITER_TOOL_PREFIX: Final = f"mcp__{MCP_SERVER_NAME}__"
MCP_ALLOWED_TOOLS: Final = f"{COWRITER_TOOL_PREFIX}*"

_NO_BUILTIN_TOOLS: Final = ""
_NO_SETTING_SOURCES: Final = ""

# The CLI is a bind-mounted, self-updating binary reading a prompt that carries
# untrusted content (lyrics, @-mentions, tool results). These flags make its
# reachable tool surface a property of this command line alone: `--tools ""`
# removes the whole built-in set, so a tool shipped by a future version cannot
# be called even though nobody here has heard of it; `--setting-sources ""`
# drops the mounted settings file, whose `permissions.allow` and `defaultMode`
# would otherwise decide what a co-writer session may do; `--strict-mcp-config`
# ignores MCP servers configured anywhere but in our own `--mcp-config`;
# `--disable-slash-commands` closes the one channel `--tools ""` does not
# touch — the CLI still resolves its own slash commands and skills from a
# prompt that begins with `/`, so this flag removes that surface rather than
# relying on our own prompt always starting with trusted system text.
_TOOL_ISOLATION_FLAGS: Final = (
    "--tools", _NO_BUILTIN_TOOLS,
    "--setting-sources", _NO_SETTING_SOURCES,
    "--strict-mcp-config",
    "--disable-slash-commands",
)

# The exact tool names `mcp_server/server.py` registers. Kept as a literal
# tuple rather than imported from that module: importing it would pull in
# `mcp` and `sqlalchemy`, and this module must stay importable in the
# scoring-worker container, which does not install the `mcp` extra (see
# CLAUDE.md's packaging-boundary note). `tests/test_mcp_server.py` pins the
# server's own registration; a dedicated drift test compares the two sets so
# this list cannot go stale without a test failing.
_EXPECTED_MCP_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    f"{COWRITER_TOOL_PREFIX}{name}" for name in (
        "list_albums", "list_songs", "search_songs", "get_song",
        "get_version", "get_generation", "create_song",
        "update_song_lyrics", "update_song_prompt", "update_song_style",
        "rename_song",
    )
)
_NO_TOOLS_EXPECTED: Final[frozenset[str]] = frozenset()

# Never a real user: the probe only lists the MCP server's advertised tools,
# it never invokes one, so no request in its name ever touches a user's data.
_TOOL_SURFACE_PROBE_USER_ID: Final = "tool-surface-probe"

_CLI_INIT_EVENT_TYPE: Final = "system"
_CLI_INIT_EVENT_SUBTYPE: Final = "init"
_TOOL_SURFACE_PROBE_PROMPT: Final = "."

_STREAM_BUFFER_LIMIT = 4 * 1024 * 1024


def clear_client_cache() -> None:
    with _client_lock:
        _sync_clients.clear()
        _async_clients.clear()


def clear_cli_tool_surface_cache() -> None:
    with _tool_surface_lock:
        _tool_surface_verdicts.clear()
        _tool_surface_failures.clear()
        _tool_surface_sync_locks.clear()
        _tool_surface_async_locks.clear()


def clear_cli_login_status_cache() -> None:
    global _cli_login_status_cache, _cli_login_status_cache_at
    with _cli_login_status_lock:
        _cli_login_status_cache = None
        _cli_login_status_cache_at = 0.0


class UnavailableError(Exception):
    """Raised when no Claude backend is available."""


class CliToolSurfaceError(UnavailableError):
    """Raised when the mounted CLI's announced tool surface does not match
    what a given call line expects — extra tools, missing ones, or a
    still-reachable slash command (see ``verify_cli_tool_surface()`` and
    ``verify_no_builtin_cli_tools()``).

    Deliberately an ``UnavailableError``: a CLI whose tool surface we cannot
    vouch for is not a CLI we run untrusted song content through, so every
    caller that already handles "no backend" refuses the turn.
    """


@dataclass
class ClaudeResponse:
    text: str


# ── Stream event models ────────────────────────────────────────────


class StreamEvent(BaseModel):
    """Base class for all streamed Claude events."""
    type: str


class AssistantTextEvent(StreamEvent):
    type: Literal["assistant_text"] = "assistant_text"
    text: str


class ToolCallEvent(StreamEvent):
    type: Literal["tool_call"] = "tool_call"
    tool_use_id: str
    name: str
    input: dict = Field(default_factory=dict)


class ToolResultEvent(StreamEvent):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False


class FinalEvent(StreamEvent):
    type: Literal["final"] = "final"
    text: str


class ErrorEvent(StreamEvent):
    type: Literal["error"] = "error"
    message: str


# ── Public interface ───────────────────────────────────────────────


def call_claude(
    prompt: str,
    api_key: str | None = None,
    system: str | None = None,
    model: str | None = None,
    max_tokens: int = 1024,
    messages: list[dict[str, str]] | None = None,
) -> ClaudeResponse:
    if model is None:
        model = get_settings().claude_chat_model
    if api_key:
        log.info("Claude: using API backend (model=%s)", model)
        return _call_api(prompt, api_key, system, model, max_tokens, messages)
    log.info("Claude: using CLI backend (model=%s)", model)
    return _call_cli(prompt, system, model, messages)


async def acall_claude(
    prompt: str,
    api_key: str | None = None,
    system: str | None = None,
    model: str | None = None,
    max_tokens: int = 1024,
    messages: list[dict[str, str]] | None = None,
) -> ClaudeResponse:
    if model is None:
        model = get_settings().claude_chat_model
    if api_key:
        log.info("Claude: using async API backend (model=%s)", model)
        return await _acall_api(prompt, api_key, system, model, max_tokens, messages)
    log.info("Claude: using async CLI backend (model=%s)", model)
    return await _acall_cli(prompt, system, model, messages)


async def acall_claude_with_mcp(
    prompt: str,
    *,
    user_id: str,
    system: str | None = None,
    model: str | None = None,
    messages: list[dict[str, str]] | None = None,
    timeout_seconds: int = 600,
) -> ClaudeResponse:
    """Call the Claude CLI with the songmaker MCP server attached.

    Spawns the CLI which in turn spawns the MCP server subprocess with
    ``SONGMAKER_MCP_USER_ID`` set. Claude's built-in tools are removed from
    the session; only ``mcp__songmaker__*`` is reachable. This path exists
    exclusively for the co-writer chat flow and requires the CLI backend
    (the Anthropic SDK does not expose MCP servers).
    """
    if model is None:
        model = get_settings().claude_chat_model
    binary = await verify_cli_tool_surface()
    flat_prompt = _flatten_messages(prompt, messages)
    stdin_body = _stdin_prompt(system, flat_prompt)
    config_path = _write_mcp_config(user_id)
    cmd = _build_mcp_cli_cmd(binary, model, config_path, stream=False)
    env = _scrub_env()
    log.info("Claude: MCP+CLI backend (model=%s, user=%s)", model, user_id)

    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                start_new_session=True,
            )
        except FileNotFoundError:
            raise UnavailableError("Claude CLI binary not found")
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(stdin_body.encode()), timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            await _reap_process_group(proc)
            raise UnavailableError(
                f"Claude CLI timed out after {timeout_seconds}s",
            )
        except BaseException:
            await _reap_process_group(proc)
            raise
    finally:
        _unlink_quiet(config_path)

    stdout = stdout_bytes.decode()
    if proc.returncode != 0:
        log.warning(
            "Claude MCP CLI failed (rc=%d, stderr_bytes=%d)",
            proc.returncode,
            len(stderr_bytes),
        )
        raise UnavailableError(
            "Claude CLI is unavailable. Check server logs for details.",
        )

    text = _parse_cli_output(stdout)
    log.debug("Claude MCP CLI response: %d chars", len(text))
    return ClaudeResponse(text=text.strip())


async def acall_claude_with_mcp_stream(
    prompt: str,
    *,
    user_id: str,
    system: str | None = None,
    model: str | None = None,
    messages: list[dict[str, str]] | None = None,
    timeout_seconds: int = 600,
) -> AsyncIterator[StreamEvent]:
    """Stream Claude CLI output as parsed events.

    Spawns the Claude CLI with ``--output-format stream-json`` and yields
    typed ``StreamEvent`` instances as the subprocess emits newline-delimited
    JSON lines. The final yielded event is always a ``FinalEvent`` (on
    success) or an ``ErrorEvent`` (on CLI failure). Malformed JSON lines
    are logged and skipped rather than raising.
    """
    if model is None:
        model = get_settings().claude_chat_model
    binary = await verify_cli_tool_surface()
    flat_prompt = _flatten_messages(prompt, messages)
    stdin_body = _stdin_prompt(system, flat_prompt)
    config_path = _write_mcp_config(user_id)
    cmd = _build_mcp_cli_cmd(binary, model, config_path, stream=True)
    env = _scrub_env()
    log.info("Claude: streaming MCP+CLI (model=%s, user=%s)", model, user_id)

    try:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                start_new_session=True,
                limit=_STREAM_BUFFER_LIMIT,
            )
        except FileNotFoundError:
            raise UnavailableError("Claude CLI binary not found")
        if proc.stdin is not None:
            proc.stdin.write(stdin_body.encode())
            await proc.stdin.drain()
            proc.stdin.close()
        try:
            async for event in _consume_stream(proc, timeout_seconds):
                yield event
        finally:
            await _reap_process_group(proc)
    finally:
        _unlink_quiet(config_path)


async def _consume_stream(
    proc: asyncio.subprocess.Process, timeout_seconds: int,
) -> AsyncIterator[StreamEvent]:
    text_chunks: list[str] = []
    final_text: str | None = None
    stderr_task = asyncio.create_task(_drain_stream(proc.stderr))
    try:
        try:
            async for raw_line in _iter_lines(proc.stdout, timeout_seconds):
                parsed = _safe_json_loads(raw_line)
                if parsed is None:
                    continue
                event = _parse_stream_event(parsed, text_chunks)
                if event is None:
                    continue
                if isinstance(event, FinalEvent):
                    final_text = event.text
                    continue
                yield event
        except asyncio.TimeoutError:
            await _reap_process_group(proc)
            raise UnavailableError(
                f"Claude CLI timed out after {timeout_seconds}s",
            )
        except BaseException:
            await _reap_process_group(proc)
            raise

        await proc.wait()
        stderr_size = await stderr_task
        if proc.returncode != 0:
            log.warning(
                "Claude MCP stream failed (rc=%d, stderr_bytes=%d)",
                proc.returncode,
                stderr_size,
            )
            raise UnavailableError(
                "Claude CLI is unavailable. Check server logs for details.",
            )

        assembled = final_text if final_text is not None else "".join(text_chunks)
        yield FinalEvent(text=assembled.strip())
    finally:
        if not stderr_task.done():
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)


async def _iter_lines(
    stdout: asyncio.StreamReader | None, timeout_seconds: int,
) -> AsyncIterator[bytes]:
    if stdout is None:
        return
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        try:
            line = await asyncio.wait_for(stdout.readline(), timeout=remaining)
        except asyncio.TimeoutError:
            raise
        if not line:
            return
        yield line


async def _drain_stream(stream: asyncio.StreamReader | None) -> int:
    """Drain a subprocess pipe without retaining its potentially sensitive body."""
    if stream is None:
        return 0
    total = 0
    while True:
        chunk = await stream.read(64 * 1024)
        if not chunk:
            return total
        total += len(chunk)


def _safe_json_loads(raw_line: bytes) -> dict | None:
    line = raw_line.strip()
    if not line:
        return None
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        log.warning("Claude stream: skipping malformed JSON line (%d bytes)", len(line))
        return None
    if not isinstance(parsed, dict):
        log.warning("Claude stream: skipping non-object event")
        return None
    return parsed


def _parse_stream_event(
    payload: dict, text_chunks: list[str],
) -> StreamEvent | None:
    kind = payload.get("type")
    if kind == "assistant":
        return _parse_assistant_event(payload, text_chunks)
    if kind == "user":
        return _parse_user_event(payload)
    if kind == "result":
        text = payload.get("result")
        if isinstance(text, str):
            return FinalEvent(text=text)
        return None
    return None


def _parse_assistant_event(
    payload: dict, text_chunks: list[str],
) -> StreamEvent | None:
    message = payload.get("message") or {}
    blocks = message.get("content") or []
    for block in blocks:
        btype = block.get("type")
        if btype == "text":
            text = block.get("text") or ""
            text_chunks.append(text)
            return AssistantTextEvent(text=text)
        if btype == "tool_use":
            return ToolCallEvent(
                tool_use_id=block.get("id") or "",
                name=block.get("name") or "",
                input=block.get("input") or {},
            )
    return None


def _parse_user_event(payload: dict) -> StreamEvent | None:
    message = payload.get("message") or {}
    blocks = message.get("content") or []
    for block in blocks:
        if block.get("type") == "tool_result":
            content = block.get("content")
            if isinstance(content, list):
                texts = [
                    c.get("text", "") for c in content if isinstance(c, dict)
                ]
                content_str = "".join(texts)
            elif isinstance(content, str):
                content_str = content
            else:
                content_str = ""
            return ToolResultEvent(
                tool_use_id=block.get("tool_use_id") or "",
                content=content_str,
                is_error=bool(block.get("is_error", False)),
            )
    return None


def is_available(api_key: str | None = None) -> bool:
    if api_key:
        return True
    return _find_claude_binary() is not None


@dataclass(frozen=True)
class CliLoginStatus:
    """What `claude auth status` reports, not just whether the binary exists."""

    logged_in: bool
    auth_method: str | None


def cli_login_status() -> CliLoginStatus:
    """Ask the CLI itself whether it is logged in, and with what auth method.

    Any failure to get a clean answer (binary missing, non-zero exit, a
    timeout, or output that doesn't parse as the expected JSON) is reported
    as logged out — a discovery probe degrades to "unavailable" rather than
    raising, since the caller iterates every co-writer provider and one
    provider's probe must not abort the others.

    The result is cached for ``CLAUDE_CLI_LOGIN_STATUS_CACHE_SECONDS``: a
    single Models-tab page load calls this once per settings section
    (providers, co-writer, judge), and each would otherwise spawn its own
    ``claude auth status`` subprocess.
    """
    global _cli_login_status_cache, _cli_login_status_cache_at
    now = time.monotonic()
    with _cli_login_status_lock:
        cached = _cli_login_status_cache
        if (
            cached is not None
            and now - _cli_login_status_cache_at < CLAUDE_CLI_LOGIN_STATUS_CACHE_SECONDS
        ):
            return cached
    status = _probe_cli_login_status()
    with _cli_login_status_lock:
        _cli_login_status_cache = status
        _cli_login_status_cache_at = now
    return status


def _probe_cli_login_status() -> CliLoginStatus:
    binary = _find_claude_binary()
    if binary is None:
        return CliLoginStatus(logged_in=False, auth_method=None)
    try:
        result = subprocess.run(
            [binary, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=COWRITER_MODELS_TIMEOUT_SECONDS,
            env=_scrub_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return CliLoginStatus(logged_in=False, auth_method=None)
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        return CliLoginStatus(logged_in=False, auth_method=None)
    if not isinstance(payload, dict) or not isinstance(payload.get("loggedIn"), bool):
        return CliLoginStatus(logged_in=False, auth_method=None)
    auth_method = payload.get("authMethod")
    return CliLoginStatus(
        logged_in=payload["loggedIn"],
        auth_method=auth_method if isinstance(auth_method, str) else None,
    )


def list_cli_model_aliases() -> list[str]:
    """Model names the CLI's `--model` flag accepts, read from `/model`.

    The CLI's own text is the only source for this list — there is no
    machine-readable catalog endpoint for a CLI-only login. Raises
    UnavailableError, never returns an empty list, if that text doesn't
    contain the expected `Available: a, b, c.` fragment.
    """
    binary = _require_claude_binary()
    try:
        result = subprocess.run(
            [binary, "-p", "/model"],
            capture_output=True,
            text=True,
            timeout=COWRITER_MODELS_TIMEOUT_SECONDS,
            env=_scrub_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise UnavailableError(
            f"Claude CLI /model timed out after {COWRITER_MODELS_TIMEOUT_SECONDS}s",
        ) from exc
    except OSError as exc:
        raise UnavailableError(f"Claude CLI /model failed to run: {exc}") from exc
    if result.returncode != 0:
        raise UnavailableError(
            f"Claude CLI /model exited {result.returncode}: {result.stderr.strip()}",
        )
    return _parse_cli_model_aliases(result.stdout)


def _parse_cli_model_aliases(stdout: str) -> list[str]:
    for line in stdout.splitlines():
        if COWRITER_CLAUDE_CLI_MODEL_LIST_MARKER not in line:
            continue
        after_marker = line.split(COWRITER_CLAUDE_CLI_MODEL_LIST_MARKER, 1)[1]
        aliases = [
            token.strip()
            for token in after_marker.rstrip(".").split(", ")
            if token.strip() and " " not in token.strip()
        ]
        if aliases:
            return aliases
    raise UnavailableError(
        "Claude CLI /model output did not contain a parseable model list",
    )


# ── Shared helpers ─────────────────────────────────────────────────


def _build_api_kwargs(
    prompt: str, system: str | None, model: str, max_tokens: int,
    messages: list[dict[str, str]] | None,
) -> dict:
    if messages is not None:
        api_messages = messages
    else:
        api_messages = [{"role": "user", "content": prompt}]

    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": api_messages,
    }
    if system:
        kwargs["system"] = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    return kwargs


def _flatten_messages(prompt: str, messages: list[dict[str, str]] | None) -> str:
    if messages is None:
        return prompt
    parts = []
    for msg in messages:
        prefix = "User" if msg["role"] == "user" else "Assistant"
        parts.append(f"{prefix}: {msg['content']}")
    return "\n\n".join(parts)


def _build_cli_cmd(
    binary: str, model: str,
) -> list[str]:
    """Command for a single-turn completion that needs no tools at all."""
    return [
        binary, "-p",
        "--model", model,
        "--output-format", "json",
        *_TOOL_ISOLATION_FLAGS,
    ]


_MCP_SUBPROCESS_PLACEHOLDER = "unused-in-mcp-subprocess"


def _build_mcp_config(user_id: str) -> str:
    """Serialize the temporary --mcp-config payload for our stdio server.

    The JSON is written to a mode-0600 file so database credentials never appear
    in ``/proc/<pid>/cmdline`` or process listings. Only DATABASE_URL and
    SONGMAKER_MCP_USER_ID are consumed by the subprocess; placeholder values
    satisfy settings validation for the other required fields.
    """
    settings = get_settings()
    config = {
        "mcpServers": {
            MCP_SERVER_NAME: {
                "command": sys.executable,
                "args": ["-m", "songmaker_cli.mcp_server"],
                "env": {
                    "DATABASE_URL": settings.database_url,
                    "REDIS_URL": _MCP_SUBPROCESS_PLACEHOLDER,
                    "SESSION_SECRET": _MCP_SUBPROCESS_PLACEHOLDER,
                    "SONGMAKER_INTERNAL_TOKEN": _MCP_SUBPROCESS_PLACEHOLDER,
                    "SONGMAKER_MCP_USER_ID": user_id,
                },
            },
        },
    }
    return json.dumps(config)


def _stdin_prompt(system: str | None, prompt: str) -> str:
    if system:
        return f"{system}\n\n{prompt}"
    return prompt


def _write_mcp_config(user_id: str) -> str:
    handle, path = tempfile.mkstemp(prefix="songmaker-mcp-", suffix=".json")
    with os.fdopen(handle, "w", encoding="utf-8") as fh:
        fh.write(_build_mcp_config(user_id))
    os.chmod(path, 0o600)
    return path


def _unlink_quiet(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return


async def _reap_process_group(proc: asyncio.subprocess.Process) -> None:
    """Terminate ``proc``'s whole process group and wait for it to exit.

    SIGKILL cannot be ignored, so the final wait below is bounded on the
    assumption it will return almost immediately — but "almost immediately"
    is not "immediately", and this function runs inside a single-flight
    probe's lock (``_verify_tool_surface_async``): an unbounded wait here
    would hold that lock forever if the process ever got stuck in an
    uninterruptible kernel sleep, locking out every later caller for the
    same key rather than just the one hung probe. On that (pathological,
    not normal-exit) timeout, the wait is handed to a background task
    instead of abandoned outright, so the process is still reaped — never
    left a zombie — once it does exit; the caller here gets its answer back
    within budget either way.
    """
    if proc.returncode is not None:
        await proc.wait()
        return
    if proc.pid is None:
        await proc.wait()
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        await proc.wait()
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=1)
        return
    except asyncio.TimeoutError:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=CLAUDE_CLI_ZOMBIE_REAP_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        log.error(
            "Claude CLI process group %d did not exit within %ds of SIGKILL; "
            "continuing to reap it in the background instead of blocking on it",
            proc.pid, CLAUDE_CLI_ZOMBIE_REAP_TIMEOUT_SECONDS,
        )
        asyncio.create_task(_reap_in_background(proc))


async def _reap_in_background(proc: asyncio.subprocess.Process) -> None:
    """Finish waiting for a process ``_reap_process_group`` gave up waiting
    on, off any caller's critical path, so it is reaped once it does exit
    rather than left a zombie for the rest of the container's life."""
    try:
        await proc.wait()
    except Exception:
        log.exception("Background reap of Claude CLI process group %s failed", proc.pid)
    else:
        log.info("Claude CLI process group %s reaped in the background", proc.pid)


def _build_mcp_cli_cmd(
    binary: str, model: str, config_path: str,
    *,
    stream: bool = False,
) -> list[str]:
    """Command for a co-writer turn: our MCP tools and nothing else.

    ``--allowedTools`` pre-approves the songmaker MCP tools so the session
    never needs a permission answer nobody is there to give. Everything else
    is either absent (``--tools ""``) or falls through to the CLI's default
    permission mode, which in ``--print`` mode can only refuse.
    """
    output_format = "stream-json" if stream else "json"
    cmd = [
        binary, "-p",
        "--model", model,
        "--output-format", output_format,
        *_TOOL_ISOLATION_FLAGS,
        "--allowedTools", MCP_ALLOWED_TOOLS,
        "--mcp-config", config_path,
    ]
    if stream:
        cmd.append("--verbose")
    return cmd


# ── Tool-surface verification ──────────────────────────────────────
#
# Two gates share the machinery below, one per invocation shape:
#
# - ``verify_cli_tool_surface()`` guards the co-writer's MCP-attached turn
#   (``acall_claude_with_mcp*``): the CLI must announce exactly the eleven
#   ``mcp__songmaker__*`` tools, nothing more and nothing less.
# - ``verify_no_builtin_cli_tools()`` / ``averify_no_builtin_cli_tools()``
#   guard every tool-free turn (``_call_cli`` / ``_acall_cli`` — the legacy
#   chat endpoint and the lyrical-coherence judge both funnel through these):
#   the CLI must announce no tools at all.
#
# Both single-flight concurrent cold-cache callers per (binary build,
# expectation) key, and both cache a genuine verdict forever per build but
# a probe *failure* — including, for the MCP-attached probe, a connection
# that never established — only briefly; see ``_verify_tool_surface_async``/
# ``_sync`` and ``_cached_tool_surface_verdict`` below for why the two must
# not be the same cache.
#
# Deliberately two checks, not one reused check: the MCP-attached probe
# spawns the songmaker MCP server subprocess, which needs the ``mcp``
# extra — registering and listing its tools touches no database, only a
# tool *call* does, so that is not the reason for the split. The scoring-
# worker container does not install ``mcp`` (see CLAUDE.md's packaging-
# boundary note), so this probe would always fail there — verified live
# against the real CLI that a missing MCP connection reports zero tools,
# not the eleven expected (see docs/security.md). The no-MCP probe never
# attaches ``--mcp-config`` at all, so it needs neither and is the one
# safe to run from every container.
#
# The no-MCP check does not need the MCP-attached one's stronger guarantee:
# the command line ``_build_cli_cmd`` actually runs has no ``--mcp-config``
# and no ``--allowedTools`` at all, a strict subset of what the MCP-attached
# probe puts on its own command line. So "no tool announced" is the correct,
# and cheapest, thing to verify for that shape — there is nothing beyond the
# built-ins for a wider check to find.


@dataclass(frozen=True)
class BinaryBuild:
    """Identity of the CLI build behind the ``claude`` path, mount and all."""

    path: str
    mtime_ns: int
    size: int


@dataclass(frozen=True)
class _AnnouncedSurface:
    """What the CLI's own ``system`` init event says it can reach.

    ``mcp_connected`` is ``None`` when no ``--mcp-config`` was attached (the
    no-builtin-tools probe never attaches one, so the question does not
    apply); ``True``/``False`` otherwise, read from the init event's own
    ``mcp_servers`` status for our server rather than assumed from the tool
    list — a failed MCP connection reports the same empty ``tools`` a clean,
    intentionally tool-free CLI would, and the two must not be confused.
    """

    tools: tuple[str, ...]
    slash_commands: tuple[str, ...]
    mcp_connected: bool | None


@dataclass(frozen=True)
class _ToolSurfaceMismatch:
    """Everything the announced surface offers beyond, or fails to offer
    from, what was expected."""

    unexpected_tools: tuple[str, ...]
    missing_tools: tuple[str, ...]
    slash_commands: tuple[str, ...]

    def __bool__(self) -> bool:
        return bool(self.unexpected_tools or self.missing_tools or self.slash_commands)

    def describe(self) -> str:
        parts = []
        if self.unexpected_tools:
            parts.append(f"unexpected tools: {', '.join(self.unexpected_tools)}")
        if self.missing_tools:
            parts.append(f"missing tools: {', '.join(self.missing_tools)}")
        if self.slash_commands:
            parts.append(f"slash commands: {', '.join(self.slash_commands)}")
        return "; ".join(parts)


_ToolSurfaceKey = tuple[BinaryBuild, frozenset[str]]

# _tool_surface_lock guards the dicts below, including the lazy creation of
# the per-key probe locks — it is never held across a probe itself. The two
# per-key lock maps ARE held across a probe (single-flight: the first cold
# caller for a key probes, concurrent callers for the *same* key wait for
# its answer instead of each starting their own CLI process). Sync and
# async callers of the same key do not exclude each other — a threading.Lock
# cannot be awaited without blocking the whole event loop, and an
# asyncio.Lock cannot be waited on from a thread with no running loop — so a
# sync and an async cold-cache call landing on the same key at the same
# instant can still each spawn one probe. Accepted: within one process the
# only shared key is _NO_TOOLS_EXPECTED (_call_cli vs _acall_cli), and both
# still get single-flight against callers in their own domain.
_tool_surface_lock = threading.Lock()
_tool_surface_sync_locks: dict[_ToolSurfaceKey, threading.Lock] = {}
_tool_surface_async_locks: dict[_ToolSurfaceKey, asyncio.Lock] = {}
_tool_surface_verdicts: dict[_ToolSurfaceKey, _ToolSurfaceMismatch] = {}
_tool_surface_failures: dict[_ToolSurfaceKey, tuple[float, str]] = {}


async def verify_cli_tool_surface() -> str:
    """Raise unless the mounted CLI reaches nothing but our eleven MCP
    tools; return the resolved binary path to run the real turn with.

    Probes with the same ``--mcp-config`` a real co-writer turn attaches, so
    "clean" means the CLI is actually still connecting our MCP server and
    reporting exactly its tools — not merely reporting no built-ins with
    nothing attached to compare against. A connection that fails to
    establish is a probe *failure* (short-lived, retried on the next call),
    never a "the CLI offers zero of our eleven tools" verdict (permanent,
    per build) — the two look identical in the raw ``tools`` list alone, so
    ``mcp_connected`` is what tells them apart.
    """
    build, key = _tool_surface_key(_EXPECTED_MCP_TOOL_NAMES)

    async def probe() -> _AnnouncedSurface:
        config_path = _write_mcp_config(_TOOL_SURFACE_PROBE_USER_ID)
        try:
            surface = await _probe_cli_surface_async(
                build.path, mcp_config_path=config_path,
                timeout_seconds=CLAUDE_CLI_TOOL_SURFACE_TIMEOUT_SECONDS,
            )
        finally:
            _unlink_quiet(config_path)
        if surface.mcp_connected is False:
            raise UnavailableError(
                f"Claude CLI at {build.path} could not connect the songmaker "
                "MCP server — cannot verify its tool surface",
            )
        return surface

    return await _verify_tool_surface_async(build, key, probe)


async def averify_no_builtin_cli_tools() -> str:
    """Async twin of ``verify_no_builtin_cli_tools`` for ``_acall_cli``."""
    build, key = _tool_surface_key(_NO_TOOLS_EXPECTED)

    async def probe() -> _AnnouncedSurface:
        return await _probe_cli_surface_async(
            build.path, mcp_config_path=None,
            timeout_seconds=CLAUDE_CLI_NO_TOOL_SURFACE_TIMEOUT_SECONDS,
        )

    return await _verify_tool_surface_async(build, key, probe)


def verify_no_builtin_cli_tools() -> str:
    """Raise unless the mounted CLI reaches no tool at all under
    ``_TOOL_ISOLATION_FLAGS``; return the resolved binary path to run the
    real turn with. Sync twin for ``_call_cli``, which has no event loop to
    await one in — the scoring worker calls it from a plain synchronous
    child, not an async context.
    """
    build, key = _tool_surface_key(_NO_TOOLS_EXPECTED)

    def probe() -> _AnnouncedSurface:
        return _probe_cli_surface_sync(
            build.path, mcp_config_path=None,
            timeout_seconds=CLAUDE_CLI_NO_TOOL_SURFACE_TIMEOUT_SECONDS,
        )

    return _verify_tool_surface_sync(build, key, probe)


async def _verify_tool_surface_async(
    build: BinaryBuild, key: _ToolSurfaceKey,
    probe: Callable[[], Awaitable[_AnnouncedSurface]],
) -> str:
    """Single-flight, cache-checked probe: the first cold caller for ``key``
    probes while holding that key's lock; a concurrent caller for the same
    key waits on the same lock and then reuses the answer instead of
    starting its own CLI process."""
    cached = _cached_tool_surface_verdict(key)
    if cached is None:
        async with _async_probe_lock(key):
            cached = _cached_tool_surface_verdict(key)
            if cached is None:
                try:
                    surface = await probe()
                except UnavailableError as exc:
                    _record_tool_surface_failure(key, str(exc))
                    raise
                cached = _evaluate_tool_surface(key, surface)
    return _finish_tool_surface_check(build, cached)


def _verify_tool_surface_sync(
    build: BinaryBuild, key: _ToolSurfaceKey, probe: Callable[[], _AnnouncedSurface],
) -> str:
    """Sync twin of ``_verify_tool_surface_async`` — same single-flight
    shape, a ``threading.Lock`` instead of an ``asyncio.Lock``."""
    cached = _cached_tool_surface_verdict(key)
    if cached is None:
        with _sync_probe_lock(key):
            cached = _cached_tool_surface_verdict(key)
            if cached is None:
                try:
                    surface = probe()
                except UnavailableError as exc:
                    _record_tool_surface_failure(key, str(exc))
                    raise
                cached = _evaluate_tool_surface(key, surface)
    return _finish_tool_surface_check(build, cached)


def _tool_surface_key(expected_tools: frozenset[str]) -> tuple[BinaryBuild, _ToolSurfaceKey]:
    binary = _require_claude_binary()
    build = _binary_build(binary)
    return build, (build, expected_tools)


def _sync_probe_lock(key: _ToolSurfaceKey) -> threading.Lock:
    with _tool_surface_lock:
        lock = _tool_surface_sync_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _tool_surface_sync_locks[key] = lock
        return lock


def _async_probe_lock(key: _ToolSurfaceKey) -> asyncio.Lock:
    with _tool_surface_lock:
        lock = _tool_surface_async_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _tool_surface_async_locks[key] = lock
        return lock


def _cached_tool_surface_verdict(key: _ToolSurfaceKey) -> _ToolSurfaceMismatch | None:
    """The remembered verdict for this exact (binary build, expectation)
    pair, or ``None`` when it still needs a fresh probe.

    Raises the cached message directly when a probe already failed for this
    pair within ``CLAUDE_CLI_TOOL_SURFACE_FAILURE_CACHE_SECONDS`` — short on
    purpose, so a struggling CLI or MCP connection does not stay refused for
    as long as a genuine verdict would (the unbounded cache below): once
    that window passes, the next call re-probes rather than trusting a
    stale failure forever. Concurrent callers waiting out that same window
    together is the *single-flight* lock's job in the caller, not this
    function's — this only decides whether a fresh probe is needed at all.
    """
    with _tool_surface_lock:
        verdict = _tool_surface_verdicts.get(key)
        if verdict is not None:
            return verdict
        failure = _tool_surface_failures.get(key)
    if failure is None:
        return None
    recorded_at, message = failure
    if time.monotonic() - recorded_at >= CLAUDE_CLI_TOOL_SURFACE_FAILURE_CACHE_SECONDS:
        return None
    raise UnavailableError(message)


def _record_tool_surface_failure(key: _ToolSurfaceKey, message: str) -> None:
    with _tool_surface_lock:
        _tool_surface_failures[key] = (time.monotonic(), message)


def _evaluate_tool_surface(
    key: _ToolSurfaceKey, surface: _AnnouncedSurface,
) -> _ToolSurfaceMismatch:
    """Remembered per (binary build, expectation), not per process: the CLI
    is a bind-mounted install that updates itself under a running container,
    and an update is exactly the event this check exists for."""
    advertised = frozenset(surface.tools)
    expected_tools = key[1]
    mismatch = _ToolSurfaceMismatch(
        unexpected_tools=tuple(sorted(advertised - expected_tools)),
        missing_tools=tuple(sorted(expected_tools - advertised)),
        slash_commands=surface.slash_commands,
    )
    with _tool_surface_lock:
        _tool_surface_verdicts[key] = mismatch
        _tool_surface_failures.pop(key, None)
    return mismatch


def _finish_tool_surface_check(build: BinaryBuild, mismatch: _ToolSurfaceMismatch) -> str:
    if mismatch:
        raise CliToolSurfaceError(
            f"Claude CLI at {build.path} does not match its expected tool "
            f"surface — {mismatch.describe()}",
        )
    return build.path


def _binary_build(binary: str) -> BinaryBuild:
    resolved = Path(binary).resolve()
    try:
        stat = resolved.stat()
    except OSError as exc:
        raise UnavailableError(f"Claude CLI at {resolved} cannot be read: {exc}") from exc
    return BinaryBuild(str(resolved), stat.st_mtime_ns, stat.st_size)


def _tool_surface_probe_cmd(binary: str, *, mcp_config_path: str | None) -> list[str]:
    cmd = [
        binary, "-p",
        "--output-format", "stream-json", "--verbose",
        "--no-session-persistence",
        *_TOOL_ISOLATION_FLAGS,
    ]
    if mcp_config_path is not None:
        cmd += ["--allowedTools", MCP_ALLOWED_TOOLS, "--mcp-config", mcp_config_path]
    return cmd


async def _probe_cli_surface_async(
    binary: str, *, mcp_config_path: str | None, timeout_seconds: int,
) -> _AnnouncedSurface:
    """What a session built like ``cmd`` announces it can reach.

    The CLI emits its ``system`` init event, tool list included, before it
    contacts the model, so the probe reads that one line and kills the
    session rather than paying for a turn. This bounds but does not
    eliminate the API call's cost: the full probe prompt is already on the
    wire by the time we read that line, so a request already in flight is
    not excluded — the CLI's own ``--max-budget-usd`` was checked live and
    only aborts a session *after* a call completes, not before one starts,
    so it does not close that gap either.
    """
    cmd = _tool_surface_probe_cmd(binary, mcp_config_path=mcp_config_path)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=_scrub_env(),
            start_new_session=True,
        )
    except FileNotFoundError:
        raise UnavailableError("Claude CLI binary not found")
    if proc.stdin is None or proc.stdout is None:
        await _reap_process_group(proc)
        raise UnavailableError("Claude CLI probe could not open its pipes")
    try:
        proc.stdin.write(_TOOL_SURFACE_PROBE_PROMPT.encode())
        await proc.stdin.drain()
        proc.stdin.close()
        first_line = await asyncio.wait_for(
            proc.stdout.readline(),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        raise UnavailableError(
            f"Claude CLI did not announce its tools within {timeout_seconds}s",
        )
    finally:
        await _reap_process_group(proc)
    return _parse_announced_surface(first_line, mcp_attached=mcp_config_path is not None)


def _probe_cli_surface_sync(
    binary: str, *, mcp_config_path: str | None, timeout_seconds: int,
) -> _AnnouncedSurface:
    """Sync twin of ``_probe_cli_surface_async`` for callers with no event
    loop — same cost caveat applies.

    Cannot use ``subprocess.run``: it blocks until the child's stdout hits
    EOF, i.e. until the whole turn finishes, not until the one init line we
    actually want has arrived — confirmed the hard way against the real CLI,
    where that turned a 5s budget into a guaranteed timeout. Reads the first
    line off a background thread instead, exactly so the *read* is what is
    bounded by ``timeout_seconds``, not the child's total lifetime; the
    child is then killed in ``finally`` the same way the async probe kills
    its session rather than paying for a full turn.
    """
    cmd = _tool_surface_probe_cmd(binary, mcp_config_path=mcp_config_path)
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_scrub_env(),
            start_new_session=True,
        )
    except OSError:
        raise UnavailableError("Claude CLI binary not found")
    try:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(_TOOL_SURFACE_PROBE_PROMPT.encode())
        proc.stdin.close()
        first_line = _read_line_with_timeout(proc.stdout, timeout_seconds)
    finally:
        _reap_process_group_sync(proc)
    return _parse_announced_surface(first_line, mcp_attached=mcp_config_path is not None)


def _read_line_with_timeout(stream, timeout_seconds: float) -> bytes:
    """Read one line off a blocking stream, bounded by ``timeout_seconds``.

    A plain file object has no read-with-timeout of its own, so the actual
    read runs on a daemon thread; a timed-out read is abandoned rather than
    cancelled (Python cannot interrupt a blocking read), but the caller
    kills the child process right after this raises, which unblocks it via
    EOF and lets the thread exit on its own.
    """
    result: queue.Queue[bytes] = queue.Queue(maxsize=1)

    def _read() -> None:
        try:
            result.put(stream.readline())
        except OSError:
            result.put(b"")

    threading.Thread(target=_read, daemon=True).start()
    try:
        return result.get(timeout=timeout_seconds)
    except queue.Empty:
        raise UnavailableError(
            f"Claude CLI did not announce its tools within {timeout_seconds}s",
        )


def _reap_process_group_sync(proc: subprocess.Popen) -> None:
    """Sync twin of ``_reap_process_group`` — same bounded-final-wait shape,
    a daemon thread instead of a background task for the pathological
    post-SIGKILL hang, since this runs where ``_call_cli``'s single-flight
    lock is a plain ``threading.Lock`` with no event loop to hand work off
    to."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=1)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=CLAUDE_CLI_ZOMBIE_REAP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        log.error(
            "Claude CLI process group %d did not exit within %ds of SIGKILL; "
            "continuing to reap it in the background instead of blocking on it",
            proc.pid, CLAUDE_CLI_ZOMBIE_REAP_TIMEOUT_SECONDS,
        )
        threading.Thread(target=_reap_in_background_sync, args=(proc,), daemon=True).start()


def _reap_in_background_sync(proc: subprocess.Popen) -> None:
    try:
        proc.wait()
    except OSError:
        log.exception("Background reap of Claude CLI process group %s failed", proc.pid)
    else:
        log.info("Claude CLI process group %s reaped in the background", proc.pid)


def _parse_announced_surface(raw_line: bytes, *, mcp_attached: bool) -> _AnnouncedSurface:
    payload = _safe_json_loads(raw_line)
    if (
        payload is None
        or payload.get("type") != _CLI_INIT_EVENT_TYPE
        or payload.get("subtype") != _CLI_INIT_EVENT_SUBTYPE
    ):
        raise UnavailableError(
            "Claude CLI did not open with the expected session init event",
        )
    tools = payload.get("tools")
    if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
        raise UnavailableError("Claude CLI announced an unreadable tool list")
    commands = payload.get("slash_commands")
    if not isinstance(commands, list) or not all(isinstance(c, str) for c in commands):
        raise UnavailableError("Claude CLI announced an unreadable slash-command list")
    return _AnnouncedSurface(
        tools=tuple(tools),
        slash_commands=tuple(commands),
        mcp_connected=_mcp_connected(payload) if mcp_attached else None,
    )


def _mcp_connected(payload: dict) -> bool:
    """Whether the init event's own ``mcp_servers`` list reports our server
    connected — read instead of assumed, because a failed connection
    reports the same empty ``tools`` a clean tool-free CLI would."""
    servers = payload.get("mcp_servers")
    if not isinstance(servers, list):
        return False
    return any(
        isinstance(server, dict)
        and server.get("name") == MCP_SERVER_NAME
        and server.get("status") == "connected"
        for server in servers
    )


def _scrub_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in SECRET_ENV_KEYS:
        env.pop(key, None)
    return env


def _parse_cli_output(stdout: str) -> str:
    try:
        outer = json.loads(stdout)
        return outer.get("result", stdout)
    except json.JSONDecodeError:
        return stdout


def _require_claude_binary() -> str:
    binary = _find_claude_binary()
    if not binary:
        raise UnavailableError(
            "Claude CLI not found. Install Claude Code or provide an API key."
        )
    return binary


def _require_anthropic():
    try:
        import anthropic
        return anthropic
    except ImportError:
        raise UnavailableError(
            "anthropic package not installed. Run: pip install anthropic"
        )


# ── API backends ───────────────────────────────────────────────────


def _call_api(
    prompt: str, api_key: str, system: str | None,
    model: str, max_tokens: int,
    messages: list[dict[str, str]] | None = None,
) -> ClaudeResponse:
    anthropic = _require_anthropic()
    with _client_lock:
        if api_key not in _sync_clients:
            _sync_clients[api_key] = anthropic.Anthropic(api_key=api_key)
        client = _sync_clients[api_key]

    kwargs = _build_api_kwargs(prompt, system, model, max_tokens, messages)
    response = client.messages.create(**kwargs)
    text = response.content[0].text if response.content else ""
    log.debug("Claude API response: %d chars", len(text))
    return ClaudeResponse(text=text)


async def _acall_api(
    prompt: str, api_key: str, system: str | None,
    model: str, max_tokens: int,
    messages: list[dict[str, str]] | None = None,
) -> ClaudeResponse:
    anthropic = _require_anthropic()
    with _client_lock:
        if api_key not in _async_clients:
            _async_clients[api_key] = anthropic.AsyncAnthropic(api_key=api_key)
        client = _async_clients[api_key]

    kwargs = _build_api_kwargs(prompt, system, model, max_tokens, messages)
    response = await client.messages.create(**kwargs)
    text = response.content[0].text if response.content else ""
    log.debug("Claude async API response: %d chars", len(text))
    return ClaudeResponse(text=text)


# ── CLI backends ───────────────────────────────────────────────────


def _call_cli(
    prompt: str, system: str | None = None, model: str | None = None,
    messages: list[dict[str, str]] | None = None,
) -> ClaudeResponse:
    """The tool-free CLI backend behind both ``call_claude()`` and the
    lyrical-coherence judge (``claude_adapter.call_claude_once``).

    Every caller of this function carries content we did not write —
    lyrics, chat history, a Whisper transcript — into the CLI, so the
    verified-tool-surface gate lives here rather than in each caller: a
    future caller of ``call_claude()`` inherits it automatically instead of
    having to remember it.
    """
    if model is None:
        model = get_settings().claude_chat_model
    binary = verify_no_builtin_cli_tools()
    flat_prompt = _flatten_messages(prompt, messages)
    stdin_body = _stdin_prompt(system, flat_prompt)
    cmd = _build_cli_cmd(binary, model)
    env = _scrub_env()

    try:
        proc = subprocess.run(
            cmd, input=stdin_body, capture_output=True, text=True, timeout=120, env=env,
        )
    except subprocess.TimeoutExpired:
        raise UnavailableError("Claude CLI timed out after 120s")

    if proc.returncode != 0:
        log.warning(
            "Claude CLI failed (rc=%d, stderr_chars=%d)",
            proc.returncode,
            len(proc.stderr),
        )
        raise UnavailableError("Claude CLI is unavailable. Check server logs for details.")

    text = _parse_cli_output(proc.stdout)
    log.debug("Claude CLI response: %d chars", len(text))
    return ClaudeResponse(text=text.strip())


async def _acall_cli(
    prompt: str, system: str | None = None, model: str | None = None,
    messages: list[dict[str, str]] | None = None,
) -> ClaudeResponse:
    """Async twin of ``_call_cli`` — the tool-free CLI backend behind
    ``acall_claude()``, whose only current caller is the legacy
    ``POST /songs/{id}/chat`` endpoint (``chat_api.py``).

    Gated the same way and for the same reason as ``_call_cli``: the gate
    sits in the call path both share, not in ``chat_api.py`` itself.
    """
    if model is None:
        model = get_settings().claude_chat_model
    binary = await averify_no_builtin_cli_tools()
    flat_prompt = _flatten_messages(prompt, messages)
    stdin_body = _stdin_prompt(system, flat_prompt)
    cmd = _build_cli_cmd(binary, model)
    env = _scrub_env()

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(stdin_body.encode()), timeout=120,
            )
        except asyncio.TimeoutError:
            await _reap_process_group(proc)
            raise UnavailableError("Claude CLI timed out after 120s")
        except BaseException:
            await _reap_process_group(proc)
            raise
    except FileNotFoundError:
        raise UnavailableError("Claude CLI binary not found")

    stdout = stdout_bytes.decode()
    if proc.returncode != 0:
        log.warning(
            "Claude CLI failed (rc=%d, stderr_bytes=%d)",
            proc.returncode,
            len(stderr_bytes),
        )
        raise UnavailableError("Claude CLI is unavailable. Check server logs for details.")

    text = _parse_cli_output(stdout)
    log.debug("Claude async CLI response: %d chars", len(text))
    return ClaudeResponse(text=text.strip())


# ── Binary discovery ───────────────────────────────────────────────


def _find_claude_binary() -> str | None:
    found = shutil.which("claude")
    if found:
        log.debug("Found claude binary on PATH: %s", found)
        return found

    ext_dir = Path.home() / ".vscode" / "extensions"
    if ext_dir.is_dir():
        for ext in sorted(ext_dir.glob("anthropic.claude-code-*"), reverse=True):
            candidate = ext / "resources" / "native-binary" / "claude"
            if candidate.is_file():
                return str(candidate)

    return None


def parse_json_response(text: str) -> dict:
    """Extract and parse JSON from a Claude response that may have markdown wrapping."""
    json_str = text.strip()
    if "```" in json_str:
        json_str = json_str.split("```")[1]
        if json_str.startswith("json"):
            json_str = json_str[4:]
        json_str = json_str.strip()

    return json.loads(json_str)
