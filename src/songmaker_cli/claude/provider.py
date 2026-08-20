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
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from songmaker_cli.settings import get_settings

log = logging.getLogger(__name__)

_sync_clients: dict[str, object] = {}
_async_clients: dict[str, object] = {}
_client_lock = threading.Lock()

_ENV_SECRETS = ("ANTHROPIC_API_KEY", "SESSION_SECRET", "DATABASE_URL", "REDIS_URL")

_DISALLOWED_TOOLS = (
    "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,"
    "Agent,NotebookEdit,TodoWrite,EnterPlanMode,"
    "CronCreate,CronDelete,CronList,RemoteTrigger,"
    "EnterWorktree,ExitWorktree,ExitPlanMode,Skill,"
    "TaskOutput,TaskStop,SendMessage,AskUserQuestion,"
    "ToolSearch"
)

_STREAM_BUFFER_LIMIT = 4 * 1024 * 1024


def clear_client_cache() -> None:
    with _client_lock:
        _sync_clients.clear()
        _async_clients.clear()


class UnavailableError(Exception):
    """Raised when no Claude backend is available."""


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
    ``SONGMAKER_MCP_USER_ID`` set. All of Claude's built-in tools remain
    denied; only ``mcp__songmaker__*`` is allowed. This path exists
    exclusively for the co-writer chat flow and requires the CLI backend
    (the Anthropic SDK does not expose MCP servers).
    """
    if model is None:
        model = get_settings().claude_chat_model
    binary = _require_claude_binary()
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
    finally:
        _unlink_quiet(config_path)

    stdout = stdout_bytes.decode()
    stderr = stderr_bytes.decode()

    if proc.returncode != 0:
        log.warning(
            "Claude MCP CLI failed (rc=%d): %s", proc.returncode, stderr[:500],
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
    binary = _require_claude_binary()
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
    if proc.returncode != 0:
        stderr_bytes = await proc.stderr.read() if proc.stderr else b""
        stderr = stderr_bytes.decode(errors="replace")
        log.warning(
            "Claude MCP stream failed (rc=%d): %s", proc.returncode, stderr[:500],
        )
        raise UnavailableError(
            "Claude CLI is unavailable. Check server logs for details.",
        )

    assembled = final_text if final_text is not None else "".join(text_chunks)
    yield FinalEvent(text=assembled.strip())


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


def _safe_json_loads(raw_line: bytes) -> dict | None:
    line = raw_line.strip()
    if not line:
        return None
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        log.warning("Claude stream: skipping malformed JSON line: %r", line[:200])
        return None
    if not isinstance(parsed, dict):
        log.warning("Claude stream: skipping non-object event: %r", parsed)
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
    binary: str, prompt: str, system: str | None, model: str,
) -> list[str]:
    cmd = [
        binary, "-p", prompt,
        "--model", model,
        "--output-format", "json",
        "--disallowedTools", _DISALLOWED_TOOLS,
    ]
    if system:
        cmd.extend(["--system-prompt", system])
    return cmd


MCP_SERVER_NAME = "songmaker"
MCP_ALLOWED_TOOLS = f"mcp__{MCP_SERVER_NAME}__*"


_MCP_SUBPROCESS_PLACEHOLDER = "unused-in-mcp-subprocess"


def _build_mcp_config(user_id: str) -> str:
    """Serialize the inline --mcp-config payload for our stdio server.

    The inline JSON is passed as a CLI argument, so anything in it is
    readable via ``/proc/<pid>/cmdline`` and ``ps auxww``. Only
    DATABASE_URL and SONGMAKER_MCP_USER_ID are actually consumed by the
    MCP subprocess — but ``Settings()`` validation requires every
    "required" field to be present. We supply placeholder values for
    REDIS_URL / SESSION_SECRET / SONGMAKER_INTERNAL_TOKEN so the real
    secrets never appear in argv of the MCP subprocess line.
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
    if proc.pid is None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
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
    await proc.wait()


def _build_mcp_cli_cmd(
    binary: str, model: str, config_path: str,
    *,
    stream: bool = False,
) -> list[str]:
    output_format = "stream-json" if stream else "json"
    cmd = [
        binary, "-p",
        "--model", model,
        "--output-format", output_format,
        "--disallowedTools", _DISALLOWED_TOOLS,
        "--allowedTools", MCP_ALLOWED_TOOLS,
        "--mcp-config", config_path,
        "--strict-mcp-config",
        "--permission-mode", "bypassPermissions",
    ]
    if stream:
        cmd.append("--verbose")
    return cmd


def _scrub_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in _ENV_SECRETS:
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
#
# All known tools are denied via --disallowedTools. This is a denylist
# (not ideal), but --tools "" and --allowedTools "" don't actually block
# tool use in current Claude CLI versions. The list should be updated
# when new tools are added to Claude Code.


def _call_cli(
    prompt: str, system: str | None = None, model: str | None = None,
    messages: list[dict[str, str]] | None = None,
) -> ClaudeResponse:
    if model is None:
        model = get_settings().claude_chat_model
    binary = _require_claude_binary()
    flat_prompt = _flatten_messages(prompt, messages)
    cmd = _build_cli_cmd(binary, flat_prompt, system, model)
    env = _scrub_env()

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, env=env,
        )
    except subprocess.TimeoutExpired:
        raise UnavailableError("Claude CLI timed out after 120s")

    if proc.returncode != 0:
        log.warning("Claude CLI failed (rc=%d): %s", proc.returncode, proc.stderr[:500])
        raise UnavailableError("Claude CLI is unavailable. Check server logs for details.")

    text = _parse_cli_output(proc.stdout)
    log.debug("Claude CLI response: %d chars", len(text))
    return ClaudeResponse(text=text.strip())


async def _acall_cli(
    prompt: str, system: str | None = None, model: str | None = None,
    messages: list[dict[str, str]] | None = None,
) -> ClaudeResponse:
    if model is None:
        model = get_settings().claude_chat_model
    binary = _require_claude_binary()
    flat_prompt = _flatten_messages(prompt, messages)
    cmd = _build_cli_cmd(binary, flat_prompt, system, model)
    env = _scrub_env()

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=120,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise UnavailableError("Claude CLI timed out after 120s")
    except FileNotFoundError:
        raise UnavailableError("Claude CLI binary not found")

    stdout = stdout_bytes.decode()
    stderr = stderr_bytes.decode()

    if proc.returncode != 0:
        log.warning("Claude CLI failed (rc=%d): %s", proc.returncode, stderr[:500])
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
