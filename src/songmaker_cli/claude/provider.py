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
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

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


def clear_client_cache() -> None:
    with _client_lock:
        _sync_clients.clear()
        _async_clients.clear()


class UnavailableError(Exception):
    """Raised when no Claude backend is available."""


@dataclass
class ClaudeResponse:
    text: str


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
    timeout_seconds: int = 300,
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
    cmd = _build_mcp_cli_cmd(binary, flat_prompt, system, model, user_id)
    env = _scrub_env()
    log.info("Claude: MCP+CLI backend (model=%s, user=%s)", model, user_id)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise UnavailableError(
                f"Claude CLI timed out after {timeout_seconds}s",
            )
    except FileNotFoundError:
        raise UnavailableError("Claude CLI binary not found")

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


def _build_mcp_cli_cmd(
    binary: str, prompt: str, system: str | None, model: str, user_id: str,
) -> list[str]:
    cmd = [
        binary, "-p", prompt,
        "--model", model,
        "--output-format", "json",
        "--disallowedTools", _DISALLOWED_TOOLS,
        "--allowedTools", MCP_ALLOWED_TOOLS,
        "--mcp-config", _build_mcp_config(user_id),
        "--strict-mcp-config",
        "--permission-mode", "bypassPermissions",
    ]
    if system:
        cmd.extend(["--system-prompt", system])
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
