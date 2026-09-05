"""Claude provider — unified interface for CLI and API backends.

Both the lyrical_coherence scorer and the chat co-writing endpoint
use this module. The backend is selected based on available credentials:

1. API key provided (env var) → ApiProvider
2. Claude CLI on PATH or in VS Code → CliProvider
3. Neither → raises UnavailableError
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
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

from songmaker_cli import agent_cli
from songmaker_cli.agent_cli import (
    CliLogin,
    claude_cli_login,
    clear_claude_cli_login_cache,
)
from songmaker_cli.constants import (
    CLAUDE_CLI_BINARY,
    CLAUDE_CLI_COMPLETION_TIMEOUT_SECONDS,
    CLAUDE_CLI_MAX_CONCURRENT_PROCESSES,
    CLAUDE_CLI_NO_TOOL_SURFACE_TIMEOUT_SECONDS,
    CLAUDE_CLI_SIGTERM_GRACE_SECONDS,
    CLAUDE_CLI_TOOL_SURFACE_FAILURE_CACHE_SECONDS,
    CLAUDE_CLI_TOOL_SURFACE_TIMEOUT_SECONDS,
    CLAUDE_CLI_ZOMBIE_FAILURE_CACHE_SECONDS,
    CLAUDE_CLI_ZOMBIE_REAP_TIMEOUT_SECONDS,
    CLI_OUTPUT_READ_LIMIT_BYTES,
    COWRITER_CLAUDE_CLI_MODEL_LIST_MARKER,
    COWRITER_MODELS_TIMEOUT_SECONDS,
    JUDGE_FAILURE_TIMEOUT,
    SECRET_ENV_KEYS,
)
from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

_sync_clients: dict[str, object] = {}
_async_clients: dict[str, object] = {}
_client_lock = threading.Lock()

MCP_SERVER_NAME: Final = "songmaker"
COWRITER_TOOL_PREFIX: Final = f"mcp__{MCP_SERVER_NAME}__"
MCP_ALLOWED_TOOLS: Final = f"{COWRITER_TOOL_PREFIX}*"

_NO_BUILTIN_TOOLS: Final = ""
_NO_SETTING_SOURCES: Final = ""
CLAUDE_CLI_MODEL_CATALOG_ERROR: Final = "Claude CLI could not list models."
CLAUDE_CLI_BINARY_NOT_FOUND_DETAIL: Final = "Claude CLI binary not found"
CLAUDE_CLI_UNAVAILABLE_DETAIL: Final = "Claude CLI is unavailable. Check server logs for details."

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
    "--tools",
    _NO_BUILTIN_TOOLS,
    "--setting-sources",
    _NO_SETTING_SOURCES,
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
    f"{COWRITER_TOOL_PREFIX}{name}"
    for name in (
        "list_albums",
        "list_songs",
        "search_songs",
        "get_song",
        "get_version",
        "get_generation",
        "create_song",
        "update_song_lyrics",
        "update_song_prompt",
        "update_song_style",
        "rename_song",
        "suggest_album_cover",
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


def clear_cli_login_status_cache() -> None:
    clear_claude_cli_login_cache()


class UnavailableError(Exception):
    """Raised when no Claude backend is available."""


class CliBinaryUnavailableError(UnavailableError):
    """Raised when the Claude CLI executable cannot be found or started."""


class CliToolSurfaceError(UnavailableError):
    """Raised when the mounted CLI's announced tool surface does not match
    what a given call line expects — extra tools, missing ones, or a
    still-reachable slash command (see ``verify_cli_tool_surface()`` and
    ``verify_no_builtin_cli_tools()``).

    Deliberately an ``UnavailableError``: a CLI whose tool surface we cannot
    vouch for is not a CLI we run untrusted song content through, so every
    caller that already handles "no backend" refuses the turn.
    """


class _ZombieProbeError(UnavailableError):
    """Raised when a tool-surface probe's own CLI process outlived
    SIGKILL. Not a plain ``UnavailableError``: it tells
    ``_record_tool_surface_failure`` to use the much longer
    ``CLAUDE_CLI_ZOMBIE_FAILURE_CACHE_SECONDS`` TTL instead of the ordinary
    one — a process stuck past SIGKILL will not become healthy in ten
    seconds, and probing again on that schedule only spawns another zombie.
    """


class _JudgeTimeoutExhausted(UnavailableError):
    """The judge's caller-owned deadline elapsed without probing the CLI."""


class _ClaudeCliProcessPoolSaturated(UnavailableError):
    """A CLI process was refused before it could create another child process."""


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
    timeout_seconds: float | None = None,
) -> ClaudeResponse:
    if model is None:
        model = get_settings().claude_chat_model
    deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    if api_key:
        log.info("Claude: using API backend (model=%s)", model)
        return _call_api(prompt, api_key, system, model, max_tokens, messages, deadline=deadline)
    log.info("Claude: using CLI backend (model=%s)", model)
    return _call_cli(prompt, system, model, messages, deadline=deadline)


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
            proc = await _spawn_reserved_async_cli_process(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                start_new_session=True,
            )
        except FileNotFoundError:
            raise CliBinaryUnavailableError(CLAUDE_CLI_BINARY_NOT_FOUND_DETAIL)
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(stdin_body.encode()),
                timeout=timeout_seconds,
            )
            _release_zombie_reservation(proc.pid)
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
            CLAUDE_CLI_UNAVAILABLE_DETAIL,
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
            proc = await _spawn_reserved_async_cli_process(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                start_new_session=True,
                limit=_STREAM_BUFFER_LIMIT,
            )
        except FileNotFoundError:
            raise CliBinaryUnavailableError(CLAUDE_CLI_BINARY_NOT_FOUND_DETAIL)
        try:
            if proc.stdin is not None:
                proc.stdin.write(stdin_body.encode())
                await proc.stdin.drain()
                proc.stdin.close()
            async for event in _consume_stream(proc, timeout_seconds):
                yield event
        finally:
            await _reap_stream_process_after_cancellation(proc)
    finally:
        _unlink_quiet(config_path)


async def _consume_stream(
    proc: asyncio.subprocess.Process,
    timeout_seconds: int,
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
            raise UnavailableError(
                f"Claude CLI timed out after {timeout_seconds}s",
            )
        await proc.wait()
        stderr_size = await stderr_task
        if proc.returncode != 0:
            log.warning(
                "Claude MCP stream failed (rc=%d, stderr_bytes=%d)",
                proc.returncode,
                stderr_size,
            )
            raise UnavailableError(
                CLAUDE_CLI_UNAVAILABLE_DETAIL,
            )

        assembled = final_text if final_text is not None else "".join(text_chunks)
        yield FinalEvent(text=assembled.strip())
    finally:
        if not stderr_task.done():
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)


async def _iter_lines(
    stdout: asyncio.StreamReader | None,
    timeout_seconds: int,
) -> AsyncIterator[bytes]:
    if stdout is None:
        return
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        line = await asyncio.wait_for(stdout.readline(), timeout=remaining)
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
    payload: dict,
    text_chunks: list[str],
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
    payload: dict,
    text_chunks: list[str],
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
                texts = [c.get("text", "") for c in content if isinstance(c, dict)]
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


def cli_login_status() -> CliLogin:
    """Return the mounted Claude CLI's cached login probe."""
    return claude_cli_login(_find_claude_binary())


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
        log.warning(
            "Claude CLI model catalog failed (rc=%d, stderr_chars=%d)",
            result.returncode,
            len(result.stderr),
        )
        raise UnavailableError(
            CLAUDE_CLI_MODEL_CATALOG_ERROR,
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
    prompt: str,
    system: str | None,
    model: str,
    max_tokens: int,
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
    binary: str,
    model: str,
) -> list[str]:
    """Command for a single-turn completion that needs no tools at all."""
    return [
        binary,
        "-p",
        "--model",
        model,
        "--output-format",
        "json",
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


def _build_mcp_cli_cmd(
    binary: str,
    model: str,
    config_path: str,
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
        binary,
        "-p",
        "--model",
        model,
        "--output-format",
        output_format,
        *_TOOL_ISOLATION_FLAGS,
        "--allowedTools",
        MCP_ALLOWED_TOOLS,
        "--mcp-config",
        config_path,
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
# Round 5 changed the *shape* of single-flight, not another detail of it.
# Rounds 3 and 4 held a per-key mutex across the whole probe and then spent
# two rounds finding a new unbounded wait inside that held lock. A lock
# held across external I/O always has another hole next to the one just
# patched, so this round removes the held lock entirely:
#
# - The dict lock (``_tool_surface_lock``) now only ever guards a dict
#   lookup/insert — never a probe, never an await. The first cold caller
#   for a key publishes a future/event under that lock and releases it
#   immediately, then probes with *no lock held at all*. Every other
#   caller finds the published future and awaits it, each with its own
#   timeout — see ``_verify_tool_surface_async``/``_sync``.
# - The probe itself runs under one overall deadline covering every step
#   (process start, stdin write, stdout read) — not a separate timeout per
#   step that can add up to an unknown total. Only the final cleanup (SIGTERM
#   grace, then the post-SIGKILL wait) has its own, separate, small bound —
#   cleanup must always be attempted regardless of how much of the answer
#   budget is left. See ``_probe_cli_surface_async``/``_sync``.
# - A process that survives SIGKILL is handed to a background reaper. One
#   reservation, bound to its PID at spawn, caps that work so a run of bad
#   probes cannot grow an unbounded pool of waiting
#   tasks/threads — and its failure is cached for
#   ``CLAUDE_CLI_ZOMBIE_FAILURE_CACHE_SECONDS`` (much longer than an
#   ordinary probe failure): ten more seconds will not make a process that
#   ignored SIGKILL healthy, and probing again on that schedule only
#   spawns another zombie.
#
# Deliberately two probe kinds, not one reused kind: the MCP-attached probe
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


@dataclass(frozen=True)
class _ToolSurfaceFailure:
    """A probe failure, remembered separately from a genuine verdict — see
    the module-level comment above for why the two must never share a
    cache. ``is_zombie`` picks the TTL: a process that outlived SIGKILL
    gets the much longer ``CLAUDE_CLI_ZOMBIE_FAILURE_CACHE_SECONDS``."""

    recorded_at: float
    message: str
    is_zombie: bool

    def ttl_seconds(self) -> float:
        return (
            CLAUDE_CLI_ZOMBIE_FAILURE_CACHE_SECONDS
            if self.is_zombie
            else CLAUDE_CLI_TOOL_SURFACE_FAILURE_CACHE_SECONDS
        )


_ToolSurfaceKey = tuple[BinaryBuild, frozenset[str]]

# Extra margin a follower waits beyond the leader's own worst case before
# giving up on its own — generous, since this only ever fires if the
# leader's own bound (probe deadline + SIGTERM grace + zombie-reap budget)
# somehow failed to hold; it is a defense-in-depth backstop, not the
# expected path.
_FOLLOWER_WAIT_MARGIN_SECONDS: Final = 2

# _tool_surface_lock guards only the dicts below — a plain lookup/insert,
# never held across a probe or an await. Single-flight is a *published
# future*, not a held mutex: the leader claims the in-flight slot under
# this lock, releases it immediately, and probes with nothing held at all.
_tool_surface_lock = threading.Lock()
_tool_surface_verdicts: dict[_ToolSurfaceKey, _ToolSurfaceMismatch] = {}
_tool_surface_failures: dict[_ToolSurfaceKey, _ToolSurfaceFailure] = {}
_tool_surface_inflight_async: dict[_ToolSurfaceKey, asyncio.Future[_ToolSurfaceMismatch]] = {}
_tool_surface_inflight_sync: dict[
    _ToolSurfaceKey, concurrent.futures.Future[_ToolSurfaceMismatch]
] = {}


@dataclass(eq=False)
class _ZombieReservation:
    """A pool slot before it is bound to the spawned process's PID."""

    pid: int | None = None


# The process-pool reservations are process-wide and shared by probes and real
# turns — their own lock, since probes touch them from plain threads as well
# as the event loop and must never be entangled with the tool-surface dicts'
# lock.
_zombie_registry_lock = threading.Lock()
_zombie_reap_reservations: set[_ZombieReservation] = set()
_zombie_reap_tasks: set[asyncio.Task] = set()
# The independent async tasks that actually run a probe (round 7,
# Finding 2) — tracked the same way, for the same two reasons: keep a
# reference so they cannot be garbage-collected while still running, and
# give shutdown something to cancel.
_tool_surface_probe_tasks: set[asyncio.Task] = set()
# The tool-surface gate's most recent verdict, for /health — not the
# boot-time snapshot ``app.state`` used to carry (round 6): every call to
# ``verify_cli_tool_surface()`` updates this, cache hit or fresh probe
# alike, so a later successful co-writer turn clears an earlier boot-time
# "unverified", and a later drifted build (after a self-update) replaces
# an earlier "ok" — /health always reads the gate's own current answer,
# never a value frozen at startup.
_tool_surface_health_lock = threading.Lock()
_tool_surface_health_state: Literal["ok", "drift", "unverified"] = "unverified"


def clear_cli_tool_surface_cache() -> None:
    global _tool_surface_health_state
    with _tool_surface_lock:
        _tool_surface_verdicts.clear()
        _tool_surface_failures.clear()
        _tool_surface_inflight_async.clear()
        _tool_surface_inflight_sync.clear()
    with _tool_surface_health_lock:
        _tool_surface_health_state = "unverified"


def claude_cli_tool_surface_health() -> Literal["ok", "drift", "unverified"]:
    """The tool-surface gate's most recent verdict — what ``/health``'s
    ``claude_cli_tool_surface`` field reports. See the module-level
    comment above ``_tool_surface_health_state`` for why this is a live
    value, not a boot-time snapshot."""
    with _tool_surface_health_lock:
        return _tool_surface_health_state


def _record_tool_surface_health(state: Literal["ok", "drift"]) -> None:
    global _tool_surface_health_state
    with _tool_surface_health_lock:
        _tool_surface_health_state = state


def _discard_tool_surface_probe_task(task: asyncio.Task) -> None:
    with _tool_surface_lock:
        _tool_surface_probe_tasks.discard(task)


async def shutdown_tool_surface_background_tasks() -> None:
    """Cancel every outstanding background zombie reaper and probe-runner
    task — call from the app's own shutdown (``server.py``'s lifespan),
    the same way it already cancels its other background loops. Does not
    touch any process a zombie reaper was tracking (it is already past
    SIGKILL); it only stops this process from continuing to wait on
    background work once it is shutting down anyway.
    """
    with _zombie_registry_lock:
        tasks = list(_zombie_reap_tasks)
    with _tool_surface_lock:
        tasks.extend(_tool_surface_probe_tasks)
        _tool_surface_probe_tasks.clear()
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def verify_cli_tool_surface() -> str:
    """Raise unless the mounted CLI reaches nothing but our eleven MCP
    tools; return the resolved binary path to run the real turn with.

    Probes with the same ``--mcp-config`` a real co-writer turn attaches, so
    "clean" means the CLI is actually still connecting our MCP server and
    reporting exactly its tools — not merely reporting no built-ins with
    nothing attached to compare against. A connection that fails to
    establish, with nothing *else* wrong, is a probe *failure*
    (short-lived, retried on the next call), never a "the CLI offers zero
    of our eleven tools" verdict (permanent, per build) — the two look
    identical in the raw ``tools`` list alone, so ``mcp_connected`` is what
    tells them apart. But an unexpected tool or a slash command is a
    permanent mismatch regardless of ``mcp_connected`` — a CLI reporting
    ``tools=["Bash"]`` while its MCP connection also happens to be down is
    not "unverifiable", it is dangerous, and caching that for only ten
    seconds would let it look clean again far too soon. See
    ``_evaluate_tool_surface`` for where that split actually happens.

    Also records the outcome as the live ``/health`` state (round 7,
    Finding 4) — on every call, cache hit or fresh probe alike, so that
    state always reflects this gate's most recent answer rather than a
    value frozen at boot.
    """

    async def probe(deadline: float) -> _AnnouncedSurface:
        config_path = _write_mcp_config(_TOOL_SURFACE_PROBE_USER_ID)
        try:
            return await _probe_cli_surface_async(
                build.path,
                mcp_config_path=config_path,
                deadline=deadline,
            )
        finally:
            _unlink_quiet(config_path)

    try:
        build, key = _tool_surface_key(_EXPECTED_MCP_TOOL_NAMES)
        result = await _verify_tool_surface_async(
            build,
            key,
            probe,
            timeout_seconds=CLAUDE_CLI_TOOL_SURFACE_TIMEOUT_SECONDS,
        )
    except CliToolSurfaceError:
        _record_tool_surface_health("drift")
        raise
    except UnavailableError:
        _record_tool_surface_health("unverified")
        raise
    _record_tool_surface_health("ok")
    return result


async def averify_no_builtin_cli_tools() -> str:
    """Async twin of ``verify_no_builtin_cli_tools`` for ``_acall_cli``."""
    build, key = _tool_surface_key(_NO_TOOLS_EXPECTED)

    async def probe(deadline: float) -> _AnnouncedSurface:
        return await _probe_cli_surface_async(
            build.path,
            mcp_config_path=None,
            deadline=deadline,
        )

    return await _verify_tool_surface_async(
        build,
        key,
        probe,
        timeout_seconds=CLAUDE_CLI_NO_TOOL_SURFACE_TIMEOUT_SECONDS,
    )


def verify_no_builtin_cli_tools() -> str:
    """Raise unless the mounted CLI reaches no tool at all under
    ``_TOOL_ISOLATION_FLAGS``; return the resolved binary path to run the
    real turn with. Sync twin for ``_call_cli``, which has no event loop to
    await one in — the scoring worker calls it from a plain synchronous
    child, not an async context.
    """
    build, key = _tool_surface_key(_NO_TOOLS_EXPECTED)

    def probe(probe_deadline: float) -> _AnnouncedSurface:
        return _probe_cli_surface_sync(
            build.path,
            mcp_config_path=None,
            deadline=probe_deadline,
        )

    return _verify_tool_surface_sync(
        build,
        key,
        probe,
    )


# ── single-flight: async ────────────────────────────────────────────


async def _verify_tool_surface_async(
    build: BinaryBuild,
    key: _ToolSurfaceKey,
    probe: Callable[[float], Awaitable[_AnnouncedSurface]],
    *,
    timeout_seconds: float,
) -> str:
    """Single-flight through a published future, never a held lock.

    The dict lock is taken twice, briefly: once to check the cache, once
    to claim the in-flight slot (or find someone else already holds it).
    It is never held while probing.

    The caller that claims the slot does not probe inline in its own
    coroutine — round 7, Finding 2: an inline leader whose own task later
    gets cancelled (an aborted request, say) used to remove the in-flight
    entry and resolve the future right there, even though the real probe
    (running in a worker thread — Finding 1) kept going in the
    background. A third caller landing in that window found no cached
    verdict and no in-flight entry, and started a *second* probe while
    the first was still running. So the probe now runs as an independent
    task (``_run_probe_and_resolve_async``) that nothing directly awaits;
    every caller, including the one that triggered it, just waits on the
    shared future like everyone else. Cancelling any one caller's own
    wait cannot touch that task or the entry it will eventually resolve.
    """
    cached = _cached_tool_surface_verdict(key)
    if cached is not None:
        return _finish_tool_surface_check(build, cached)

    future, is_leader = _claim_or_join_inflight_async(key)
    if is_leader:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        task = asyncio.create_task(_run_probe_and_resolve_async(key, probe, deadline, future))
        with _tool_surface_lock:
            _tool_surface_probe_tasks.add(task)
        task.add_done_callback(_discard_tool_surface_probe_task)

    mismatch = await _await_follower_result_async(build, future, timeout_seconds)
    return _finish_tool_surface_check(build, mismatch)


async def _run_probe_and_resolve_async(
    key: _ToolSurfaceKey,
    probe: Callable[[float], Awaitable[_AnnouncedSurface]],
    deadline: float,
    future: asyncio.Future[_ToolSurfaceMismatch],
) -> None:
    """The actual probe, run as work independent of whoever triggered it.

    Nothing directly awaits this task, so a caller's own cancellation
    never reaches it — it always runs to completion (or its own
    deadline/reap-bounded failure) and is what resolves ``future``,
    regardless of whether the original triggering caller is still around
    to see the answer.
    """
    build = key[0]
    try:
        surface = await probe(deadline)
        mismatch = _evaluate_tool_surface(key, surface)
    except UnavailableError as exc:
        if not isinstance(exc, _ClaudeCliProcessPoolSaturated):
            _record_tool_surface_failure(
                key,
                str(exc),
                is_zombie=isinstance(exc, _ZombieProbeError),
            )
        _resolve_inflight_async(key, future, exception=exc)
        return
    except asyncio.CancelledError as exc:
        _resolve_inflight_async(key, future, exception=_follower_safe_exception(build, exc))
        raise
    except Exception as exc:
        _resolve_inflight_async(key, future, exception=_follower_safe_exception(build, exc))
        return
    _resolve_inflight_async(key, future, result=mismatch)


async def _await_follower_result_async(
    build: BinaryBuild,
    future: asyncio.Future[_ToolSurfaceMismatch],
    probe_timeout_seconds: float,
) -> _ToolSurfaceMismatch:
    follower_budget = _follower_wait_budget_seconds(probe_timeout_seconds)
    try:
        # shield: this follower's own wait_for must not cancel the shared
        # future out from under the leader (or every other follower) just
        # because *this* caller gave up waiting on it.
        return await asyncio.wait_for(asyncio.shield(future), timeout=follower_budget)
    except asyncio.TimeoutError:
        raise UnavailableError(
            f"Claude CLI at {build.path} did not answer within {follower_budget}s "
            "waiting on another caller's in-flight probe",
        )


def _claim_or_join_inflight_async(
    key: _ToolSurfaceKey,
) -> tuple[asyncio.Future[_ToolSurfaceMismatch], bool]:
    with _tool_surface_lock:
        future = _tool_surface_inflight_async.get(key)
        if future is not None:
            return future, False
        future = asyncio.get_running_loop().create_future()
        _tool_surface_inflight_async[key] = future
        return future, True


def _resolve_inflight_async(
    key: _ToolSurfaceKey,
    future: asyncio.Future[_ToolSurfaceMismatch],
    *,
    result: _ToolSurfaceMismatch | None = None,
    exception: BaseException | None = None,
) -> None:
    with _tool_surface_lock:
        _tool_surface_inflight_async.pop(key, None)
    if future.done():
        return
    if exception is not None:
        future.set_exception(exception)
        # This runs inside the independent probe task (round 7), which
        # never reads the future back itself — every caller, the one that
        # triggered the probe included, awaits it the same way through
        # _await_follower_result_async. But any of them may already have
        # given up on their own wait_for by the time we get here, leaving
        # nobody left to retrieve it the normal way; without this call,
        # asyncio logs "exception was never retrieved" once the future is
        # garbage-collected.
        future.exception()
    else:
        future.set_result(result)


# ── single-flight: sync ─────────────────────────────────────────────


def _verify_tool_surface_sync(
    build: BinaryBuild,
    key: _ToolSurfaceKey,
    probe: Callable[[float], _AnnouncedSurface],
) -> str:
    """Sync twin of ``_verify_tool_surface_async`` — a
    ``concurrent.futures.Future`` instead of an ``asyncio.Future``, since
    this runs where ``_call_cli`` has no event loop to publish one on."""
    cached = _cached_tool_surface_verdict(key)
    if cached is not None:
        return _finish_tool_surface_check(build, cached)

    future, is_leader = _claim_or_join_inflight_sync(key)
    if not is_leader:
        follower_budget = _follower_wait_budget_seconds(
            CLAUDE_CLI_NO_TOOL_SURFACE_TIMEOUT_SECONDS,
        )
        try:
            mismatch = future.result(timeout=follower_budget)
        except concurrent.futures.TimeoutError:
            raise UnavailableError(
                f"Claude CLI at {build.path} did not answer within {follower_budget}s "
                "waiting on another caller's in-flight probe",
            )
        return _finish_tool_surface_check(build, mismatch)

    probe_deadline = time.monotonic() + CLAUDE_CLI_NO_TOOL_SURFACE_TIMEOUT_SECONDS
    try:
        surface = probe(probe_deadline)
        mismatch = _evaluate_tool_surface(key, surface)
    except UnavailableError as exc:
        is_zombie = isinstance(exc, _ZombieProbeError)
        if is_zombie:
            _record_tool_surface_failure(key, str(exc), is_zombie=True)
        if not is_zombie and not isinstance(exc, _ClaudeCliProcessPoolSaturated):
            _record_tool_surface_failure(
                key,
                str(exc),
                is_zombie=False,
            )
        _resolve_inflight_sync(key, future, exception=exc)
        raise exc
    except BaseException as exc:
        _resolve_inflight_sync(key, future, exception=_follower_safe_exception(build, exc))
        raise
    _resolve_inflight_sync(key, future, result=mismatch)
    return _finish_tool_surface_check(build, mismatch)


def _claim_or_join_inflight_sync(
    key: _ToolSurfaceKey,
) -> tuple[concurrent.futures.Future[_ToolSurfaceMismatch], bool]:
    with _tool_surface_lock:
        future = _tool_surface_inflight_sync.get(key)
        if future is not None:
            return future, False
        future = concurrent.futures.Future()
        _tool_surface_inflight_sync[key] = future
        return future, True


def _resolve_inflight_sync(
    key: _ToolSurfaceKey,
    future: concurrent.futures.Future[_ToolSurfaceMismatch],
    *,
    result: _ToolSurfaceMismatch | None = None,
    exception: BaseException | None = None,
) -> None:
    with _tool_surface_lock:
        _tool_surface_inflight_sync.pop(key, None)
    if future.done():
        return
    if exception is not None:
        future.set_exception(exception)
    else:
        future.set_result(result)


def _follower_safe_exception(build: BinaryBuild, exc: BaseException) -> BaseException:
    """What a *follower* sees when the leader's own probe ends in
    something other than ``UnavailableError`` — a cancelled leader task,
    an unexpected bug, anything.

    The leader's own ``raise`` still carries the real exception, unfiltered
    — that is what shows up in its own logs/stack trace. But a follower is
    an unrelated caller that never asked to be cancelled or to inherit a
    stranger's bug: handing it the leader's literal ``CancelledError``
    would make its own task look cancelled too, confusing whatever is
    awaiting *it* (a request handler, a test). A follower always gets a
    normal, catchable ``UnavailableError`` instead.
    """
    if isinstance(exc, UnavailableError):
        return exc
    return UnavailableError(
        f"Claude CLI probe for {build.path} was aborted before it could answer: {exc}",
    )


def _follower_wait_budget_seconds(probe_timeout_seconds: float) -> float:
    return probe_timeout_seconds + _cleanup_margin_seconds()


def _cleanup_margin_seconds() -> float:
    return (
        CLAUDE_CLI_SIGTERM_GRACE_SECONDS
        + CLAUDE_CLI_ZOMBIE_REAP_TIMEOUT_SECONDS
        + _FOLLOWER_WAIT_MARGIN_SECONDS
    )


# ── cache lookups shared by both domains ────────────────────────────


def _tool_surface_key(expected_tools: frozenset[str]) -> tuple[BinaryBuild, _ToolSurfaceKey]:
    binary = _require_claude_binary()
    build = _binary_build(binary)
    return build, (build, expected_tools)


def _cached_tool_surface_verdict(key: _ToolSurfaceKey) -> _ToolSurfaceMismatch | None:
    """The remembered verdict for this exact (binary build, expectation)
    pair, or ``None`` when it still needs a fresh probe.

    Raises the cached message directly when a probe already failed for this
    pair within its failure's own TTL (ordinary or, for a zombie, the much
    longer one) — short on purpose for the ordinary case, so a struggling
    CLI or MCP connection does not stay refused for as long as a genuine
    verdict would (the unbounded cache below): once that window passes, the
    next call re-probes rather than trusting a stale failure forever.
    """
    with _tool_surface_lock:
        verdict = _tool_surface_verdicts.get(key)
        if verdict is not None:
            return verdict
        failure = _tool_surface_failures.get(key)
    if failure is None:
        return None
    if time.monotonic() - failure.recorded_at >= failure.ttl_seconds():
        return None
    raise UnavailableError(failure.message)


def _record_tool_surface_failure(key: _ToolSurfaceKey, message: str, *, is_zombie: bool) -> None:
    with _tool_surface_lock:
        _tool_surface_failures[key] = _ToolSurfaceFailure(time.monotonic(), message, is_zombie)


def _evaluate_tool_surface(
    key: _ToolSurfaceKey,
    surface: _AnnouncedSurface,
) -> _ToolSurfaceMismatch:
    """Remembered per (binary build, expectation), not per process: the CLI
    is a bind-mounted install that updates itself under a running container,
    and an update is exactly the event this check exists for.

    Raises ``UnavailableError`` instead of returning, for a probe *failure*
    the caller must cache only briefly (see ``_verify_tool_surface_async``/
    ``_sync``), in exactly one case: the MCP connection never established
    and that is the *only* thing wrong — nothing unexpected was announced,
    no missing tool can be blamed on anything but the connection itself.
    An unexpected tool or a still-reachable slash command is always a
    permanent mismatch, MCP connected or not: a CLI that offers ``Bash``
    while its MCP connection also happens to be down is not "we could not
    verify it", it is a confirmed problem with this exact build, and must
    stay refused until the build changes, not for a mere ten seconds.
    """
    advertised = frozenset(surface.tools)
    expected_tools = key[1]
    unexpected_tools = tuple(sorted(advertised - expected_tools))
    missing_tools = tuple(sorted(expected_tools - advertised))
    slash_commands = surface.slash_commands

    if surface.mcp_connected is False and not unexpected_tools and not slash_commands:
        raise UnavailableError(
            "Claude CLI could not connect the songmaker MCP server — "
            "cannot verify its tool surface",
        )

    mismatch = _ToolSurfaceMismatch(
        unexpected_tools=unexpected_tools,
        missing_tools=missing_tools,
        slash_commands=slash_commands,
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
        binary,
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        *_TOOL_ISOLATION_FLAGS,
    ]
    if mcp_config_path is not None:
        cmd += ["--allowedTools", MCP_ALLOWED_TOOLS, "--mcp-config", mcp_config_path]
    return cmd


# ── the probe itself: one overall deadline, async ───────────────────


async def _probe_cli_surface_async(
    binary: str,
    *,
    mcp_config_path: str | None,
    deadline: float,
) -> _AnnouncedSurface:
    """What a session built like ``cmd`` announces it can reach.

    Delegates to the sync gate on a worker thread, rather than spawning
    through ``asyncio.create_subprocess_exec`` directly. That keeps a stuck
    spawn away from the event loop; the sync gate delegates process handling
    to ``agent_cli.run_cli_bounded``.

    Reading the ``system`` init event and then killing the session bounds
    but does not eliminate the API call's cost: the full probe prompt is
    already on the wire by the time we read that line, so a request already
    in flight is not excluded — the CLI's own ``--max-budget-usd`` was
    checked live and only aborts a session *after* a call completes, not
    before one starts, so it does not close that gap either.

    The outer wait also covers executor queueing, while the runner keeps
    responsibility for eventually reaping a late spawn.
    """
    remaining = max(deadline - asyncio.get_running_loop().time(), 0)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                _probe_cli_surface_sync,
                binary,
                mcp_config_path=mcp_config_path,
                deadline=deadline,
            ),
            timeout=remaining + _cleanup_margin_seconds(),
        )
    except asyncio.TimeoutError:
        raise UnavailableError("Claude CLI probe cleanup did not finish within its budget")


# ── the probe itself: one overall deadline, sync ────────────────────


def _probe_cli_surface_sync(
    binary: str,
    *,
    mcp_config_path: str | None,
    deadline: float,
) -> _AnnouncedSurface:
    """Run one tool-surface probe through the shared bounded CLI runner."""
    if deadline <= time.monotonic():
        raise UnavailableError("Claude CLI probe preflight budget was already exhausted")
    reservation = _reserve_zombie_admission()
    if reservation is None:
        raise _ClaudeCliProcessPoolSaturated(_claude_cli_process_pool_limit_message())

    released = False

    def on_spawned(process_id: int) -> None:
        _bind_zombie_reservation(reservation, process_id)

    def on_reaped(_process_id: int, _became_zombie: bool) -> None:
        nonlocal released
        _release_zombie_reservation(reservation)
        released = True

    try:
        outcome = agent_cli.run_cli_bounded(
            _tool_surface_probe_cmd(binary, mcp_config_path=mcp_config_path),
            stdin_payload=_TOOL_SURFACE_PROBE_PROMPT.encode(),
            read="first_line",
            deadline=deadline,
            stderr="devnull",
            output_read_limit_bytes=CLI_OUTPUT_READ_LIMIT_BYTES,
            cleanup_margin_seconds=_cleanup_margin_seconds(),
            on_spawned=on_spawned,
            on_reaped=on_reaped,
        )
    except BaseException:
        if not released:
            _release_zombie_reservation(reservation)
        raise
    if outcome.reason is agent_cli.CliRunReason.SPAWN_FAILED:
        if not released:
            _release_zombie_reservation(reservation)
        raise UnavailableError(f"Claude CLI probe failed to run: {outcome.spawn_error}")
    if outcome.reason is agent_cli.CliRunReason.DEADLINE_BEFORE_SPAWN:
        raise UnavailableError("Claude CLI probe did not start within its budget")
    if outcome.reason is agent_cli.CliRunReason.CLEANUP_OVERRAN:
        raise UnavailableError("Claude CLI probe cleanup did not finish within its budget")
    if outcome.became_zombie:
        raise _ZombieProbeError("Claude CLI probe process outlived SIGKILL")
    if outcome.reason is agent_cli.CliRunReason.IO_ERROR:
        raise UnavailableError(f"Claude CLI probe failed to run: {outcome.io_error}")
    if outcome.reason in {
        agent_cli.CliRunReason.DEADLINE_WHILE_WRITING,
        agent_cli.CliRunReason.DEADLINE_WHILE_READING,
    }:
        raise UnavailableError("Claude CLI probe did not answer within its budget")
    if outcome.reason is agent_cli.CliRunReason.OUTPUT_LIMIT_REACHED:
        raise UnavailableError("Claude CLI probe output exceeded its read limit")
    if outcome.reason is not agent_cli.CliRunReason.COMPLETE:
        raise RuntimeError(f"Unexpected Claude CLI probe outcome: {outcome.reason}")
    return _parse_announced_surface(
        outcome.stdout.encode(),
        mcp_attached=mcp_config_path is not None,
    )


# ── reap: async ──────────────────────────────────────────────────────


async def _reap_stream_process_after_cancellation(
    proc: asyncio.subprocess.Process,
) -> None:
    """Finish a streaming CLI reap even if its consumer was cancelled.

    ASGI 2.3 cancels the response-stream task when it receives a client
    disconnect.  That cancellation closes this async generator, but a second
    cancellation can otherwise interrupt the first await in its ``finally``
    block.  Run the bounded reap in its own task and shield that task until it
    completes; the caller still receives its cancellation once cleanup is
    complete.
    """
    # The non-streaming provider is also used by the scoring-worker image,
    # which intentionally does not install the server's ASGI dependencies.
    # This helper is exclusive to the streaming co-writer endpoint, where
    # FastAPI provides AnyIO.
    import anyio

    reap_task = asyncio.create_task(_reap_process_group(proc))
    try:
        # Starlette uses AnyIO's level cancellation: after its cancel scope
        # fires, every await outside a shield raises again.  asyncio.shield()
        # only protects the child task, so retrying it in a loop spins without
        # ever letting the reaper run.  An AnyIO shield protects this wait from
        # the active ASGI cancel scope instead.
        with anyio.CancelScope(shield=True):
            await asyncio.shield(reap_task)
    except asyncio.CancelledError:
        # Direct asyncio Task.cancel() is not governed by an AnyIO scope.  It
        # may interrupt the first wait, so finish cleanup behind the same
        # shield before re-delivering that cancellation to the caller.
        with anyio.CancelScope(shield=True):
            await asyncio.shield(reap_task)
        raise

    # Re-deliver an ASGI cancellation that was deferred by the shield only
    # after the process has been reaped.
    await anyio.lowlevel.checkpoint_if_cancelled()


async def _reap_process_group(proc: asyncio.subprocess.Process) -> bool:
    """Terminate ``proc``'s whole process group and confirm it exited.

    Every wait below is bounded — a process the OS has already confirmed
    dead (``proc.returncode`` set, or SIGTERM raising ``ProcessLookupError``)
    is expected to report its exit almost instantly, but "expected" is not
    "guaranteed", and an unbounded wait anywhere in this function used to
    be able to block whoever was waiting on it (rounds 3 and 4) forever.

    Returns ``True`` when the process outlived SIGKILL and was handed to
    a background reaper instead of being confirmed dead here — a zombie,
    not a normal exit.
    """
    if proc.returncode is not None or proc.pid is None:
        return await _confirm_exit_or_track_zombie(proc)

    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return await _confirm_exit_or_track_zombie(proc)

    if await _wait_for_sigterm_exit(proc):
        _release_zombie_reservation(proc.pid)
        return False

    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return await _confirm_exit_or_track_zombie(proc)

    return await _confirm_exit_or_track_zombie(proc)


async def _wait_for_sigterm_exit(proc: asyncio.subprocess.Process) -> bool:
    try:
        async with asyncio.timeout(CLAUDE_CLI_SIGTERM_GRACE_SECONDS):
            await proc.wait()
        return True
    except TimeoutError:
        return False


async def _wait_for_zombie_reap(proc: asyncio.subprocess.Process) -> bool:
    try:
        async with asyncio.timeout(CLAUDE_CLI_ZOMBIE_REAP_TIMEOUT_SECONDS):
            await proc.wait()
        return True
    except TimeoutError:
        return False


async def _confirm_exit_or_track_zombie(proc: asyncio.subprocess.Process) -> bool:
    if await _wait_for_zombie_reap(proc):
        _release_zombie_reservation(proc.pid)
        return False
    return _track_zombie_reap_async(proc)


def _track_zombie_reap_async(proc: asyncio.subprocess.Process) -> bool:
    log.error(
        "Claude CLI process group %d did not exit within %ds of SIGKILL",
        proc.pid,
        CLAUDE_CLI_ZOMBIE_REAP_TIMEOUT_SECONDS,
    )
    task = asyncio.create_task(_reap_in_background(proc))
    with _zombie_registry_lock:
        _zombie_reap_tasks.add(task)
    task.add_done_callback(_zombie_reap_tasks.discard)
    return True


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
    finally:
        _release_zombie_reservation(proc.pid)


# ── zombie-reaper reservations, shared by both domains ───────────────


def _claude_cli_process_pool_limit_message() -> str:
    return (
        "Claude CLI process pool is at its concurrency limit "
        f"({CLAUDE_CLI_MAX_CONCURRENT_PROCESSES}); refusing to start another"
    )


def _reserve_zombie_admission() -> _ZombieReservation | None:
    """Reserve one shared CLI-process slot before spawning."""
    reservation = _ZombieReservation()
    with _zombie_registry_lock:
        if len(_zombie_reap_reservations) >= CLAUDE_CLI_MAX_CONCURRENT_PROCESSES:
            log.error(_claude_cli_process_pool_limit_message())
            return None
        _zombie_reap_reservations.add(reservation)
        return reservation


def _bind_zombie_reservation(reservation: _ZombieReservation, pid: int | None) -> None:
    if pid is None:
        raise ValueError("Cannot bind a Claude CLI process reservation without a PID")
    with _zombie_registry_lock:
        reservation.pid = pid
        _zombie_reap_reservations.add(reservation)


def _release_zombie_reservation(reservation: _ZombieReservation | int | None) -> None:
    if reservation is None:
        raise ValueError("Cannot release a Claude CLI process reservation without a PID")
    with _zombie_registry_lock:
        if isinstance(reservation, _ZombieReservation):
            _zombie_reap_reservations.discard(reservation)
            return
        handle = next(
            (candidate for candidate in _zombie_reap_reservations if candidate.pid == reservation),
            None,
        )
        if handle is not None:
            _zombie_reap_reservations.discard(handle)


async def _spawn_reserved_async_cli_process(
    *cmd: str,
    **kwargs: object,
) -> asyncio.subprocess.Process:
    reservation = _reserve_zombie_admission()
    if reservation is None:
        raise _ClaudeCliProcessPoolSaturated(_claude_cli_process_pool_limit_message())
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, **kwargs)
    except BaseException:
        _release_zombie_reservation(reservation)
        raise
    _bind_zombie_reservation(reservation, proc.pid)
    return proc


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
        raise CliBinaryUnavailableError(
            "Claude CLI not found. Install Claude Code or provide an API key."
        )
    return binary


def _require_anthropic():
    try:
        import anthropic

        return anthropic
    except ImportError:
        raise UnavailableError("anthropic package not installed. Run: pip install anthropic")


# ── API backends ───────────────────────────────────────────────────


def _call_api(
    prompt: str,
    api_key: str,
    system: str | None,
    model: str,
    max_tokens: int,
    messages: list[dict[str, str]] | None = None,
    *,
    deadline: float | None = None,
) -> ClaudeResponse:
    anthropic = _require_anthropic()
    with _client_lock:
        if api_key not in _sync_clients:
            _sync_clients[api_key] = anthropic.Anthropic(api_key=api_key)
        client = _sync_clients[api_key]

    kwargs = _build_api_kwargs(prompt, system, model, max_tokens, messages)
    request_client = (
        client.with_options(
            timeout=_remaining_judge_timeout(deadline),
            max_retries=0,
        )
        if deadline is not None
        else client
    )
    try:
        response = request_client.messages.create(**kwargs)
    except anthropic.APITimeoutError as exc:
        if deadline is not None:
            raise UnavailableError(JUDGE_FAILURE_TIMEOUT) from exc
        raise
    text = response.content[0].text if response.content else ""
    log.debug("Claude API response: %d chars", len(text))
    return ClaudeResponse(text=text)


def _remaining_judge_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _JudgeTimeoutExhausted(JUDGE_FAILURE_TIMEOUT)
    return remaining


async def _acall_api(
    prompt: str,
    api_key: str,
    system: str | None,
    model: str,
    max_tokens: int,
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
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    messages: list[dict[str, str]] | None = None,
    *,
    deadline: float | None = None,
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

    reservation = _reserve_zombie_admission()
    if reservation is None:
        raise _ClaudeCliProcessPoolSaturated(_claude_cli_process_pool_limit_message())
    try:
        try:
            proc = subprocess.run(
                cmd,
                input=stdin_body,
                capture_output=True,
                text=True,
                timeout=(
                    _remaining_judge_timeout(deadline)
                    if deadline is not None
                    else CLAUDE_CLI_COMPLETION_TIMEOUT_SECONDS
                ),
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            if deadline is not None:
                raise UnavailableError(JUDGE_FAILURE_TIMEOUT) from exc
            raise UnavailableError(
                f"Claude CLI timed out after {CLAUDE_CLI_COMPLETION_TIMEOUT_SECONDS}s",
            ) from exc

        if proc.returncode != 0:
            log.warning(
                "Claude CLI failed (rc=%d, stderr_chars=%d)",
                proc.returncode,
                len(proc.stderr),
            )
            raise UnavailableError(CLAUDE_CLI_UNAVAILABLE_DETAIL)

        text = _parse_cli_output(proc.stdout)
        log.debug("Claude CLI response: %d chars", len(text))
        return ClaudeResponse(text=text.strip())
    finally:
        # subprocess.run() returns only after its child has exited, including
        # after its own timeout cleanup, so this opaque handle is safe to free.
        _release_zombie_reservation(reservation)


async def _acall_cli(
    prompt: str,
    system: str | None = None,
    model: str | None = None,
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
        proc = await _spawn_reserved_async_cli_process(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(stdin_body.encode()),
                timeout=120,
            )
            _release_zombie_reservation(proc.pid)
        except asyncio.TimeoutError:
            await _reap_process_group(proc)
            raise UnavailableError("Claude CLI timed out after 120s")
        except BaseException:
            await _reap_process_group(proc)
            raise
    except FileNotFoundError:
        raise UnavailableError(CLAUDE_CLI_BINARY_NOT_FOUND_DETAIL)

    stdout = stdout_bytes.decode()
    if proc.returncode != 0:
        log.warning(
            "Claude CLI failed (rc=%d, stderr_bytes=%d)",
            proc.returncode,
            len(stderr_bytes),
        )
        raise UnavailableError(CLAUDE_CLI_UNAVAILABLE_DETAIL)

    text = _parse_cli_output(stdout)
    log.debug("Claude async CLI response: %d chars", len(text))
    return ClaudeResponse(text=text.strip())


# ── Binary discovery ───────────────────────────────────────────────


def _find_claude_binary() -> str | None:
    found = shutil.which(CLAUDE_CLI_BINARY)
    if found:
        log.debug("Found claude binary on PATH: %s", found)
        return found

    ext_dir = Path.home() / ".vscode" / "extensions"
    if ext_dir.is_dir():
        for ext in sorted(ext_dir.glob("anthropic.claude-code-*"), reverse=True):
            candidate = ext / "resources" / "native-binary" / CLAUDE_CLI_BINARY
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
