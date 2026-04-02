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
from dataclasses import dataclass
from pathlib import Path

from songmaker_cli.constants import CLAUDE_CHAT_MODEL

log = logging.getLogger(__name__)


class UnavailableError(Exception):
    """Raised when no Claude backend is available."""


@dataclass
class ClaudeResponse:
    text: str


def call_claude(
    prompt: str,
    api_key: str | None = None,
    system: str | None = None,
    model: str = CLAUDE_CHAT_MODEL,
    max_tokens: int = 1024,
) -> ClaudeResponse:
    """Call Claude using the best available backend.

    Args:
        prompt: The user message to send.
        api_key: Anthropic API key (from env). If provided, uses API.
        system: Optional system prompt.
        model: Model ID for API calls.
        max_tokens: Max response tokens for API calls.

    Returns:
        ClaudeResponse with the text response.
    """
    if api_key:
        log.info("Claude: using API backend (model=%s)", model)
        return _call_api(prompt, api_key, system, model, max_tokens)
    log.info("Claude: using CLI backend (model=%s)", model)
    return _call_cli(prompt, system, model)


def is_available(api_key: str | None = None) -> bool:
    """Check if any Claude backend is available."""
    if api_key:
        return True
    return _find_claude_binary() is not None


def _call_api(
    prompt: str,
    api_key: str,
    system: str | None,
    model: str,
    max_tokens: int,
) -> ClaudeResponse:
    """Call Claude via the Anthropic Python SDK."""
    try:
        import anthropic
    except ImportError:
        raise UnavailableError(
            "anthropic package not installed. Run: pip install anthropic"
        )

    client = anthropic.Anthropic(api_key=api_key)

    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    response = client.messages.create(**kwargs)
    text = response.content[0].text if response.content else ""
    log.debug("Claude API response: %d chars", len(text))
    return ClaudeResponse(text=text)


_DISALLOWED_TOOLS = (
    "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,"
    "Agent,NotebookEdit,TodoWrite,EnterPlanMode,"
    "CronCreate,CronDelete,CronList,RemoteTrigger,"
    "EnterWorktree,ExitWorktree,ExitPlanMode,Skill,"
    "TaskOutput,TaskStop,SendMessage,AskUserQuestion,"
    "ToolSearch"
)


def _call_cli(
    prompt: str, system: str | None = None, model: str = CLAUDE_CHAT_MODEL,
) -> ClaudeResponse:
    """Call Claude via the Claude Code CLI (uses Max subscription).

    All known tools are denied via --disallowedTools. This is a denylist
    (not ideal), but --tools "" and --allowedTools "" don't actually block
    tool use in current Claude CLI versions. The list should be updated
    when new tools are added to Claude Code.
    """
    binary = _find_claude_binary()
    if not binary:
        raise UnavailableError(
            "Claude CLI not found. Install Claude Code or provide an API key."
        )

    cmd = [
        binary, "-p", prompt,
        "--model", model,
        "--output-format", "json",
        "--disallowedTools", _DISALLOWED_TOOLS,
    ]
    if system:
        cmd.extend(["--system-prompt", system])

    env = os.environ.copy()
    for secret_key in ("ANTHROPIC_API_KEY", "SESSION_SECRET", "DATABASE_URL", "REDIS_URL"):
        env.pop(secret_key, None)

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, env=env,
        )
    except subprocess.TimeoutExpired:
        raise UnavailableError("Claude CLI timed out after 120s")

    if proc.returncode != 0:
        log.warning("Claude CLI failed (rc=%d): %s", proc.returncode, proc.stderr[:500])
        raise UnavailableError("Claude CLI is unavailable. Check server logs for details.")

    try:
        outer = json.loads(proc.stdout)
        text = outer.get("result", proc.stdout)
    except json.JSONDecodeError:
        text = proc.stdout

    log.debug("Claude CLI response: %d chars", len(text))
    return ClaudeResponse(text=text.strip())


async def acall_claude(
    prompt: str,
    api_key: str | None = None,
    system: str | None = None,
    model: str = CLAUDE_CHAT_MODEL,
    max_tokens: int = 1024,
    messages: list[dict[str, str]] | None = None,
) -> ClaudeResponse:
    if api_key:
        log.info("Claude: using async API backend (model=%s)", model)
        return await _acall_api(prompt, api_key, system, model, max_tokens, messages)
    log.info("Claude: using async CLI backend (model=%s)", model)
    return await _acall_cli(prompt, system, model, messages)


async def _acall_api(
    prompt: str,
    api_key: str,
    system: str | None,
    model: str,
    max_tokens: int,
    messages: list[dict[str, str]] | None = None,
) -> ClaudeResponse:
    try:
        import anthropic
    except ImportError:
        raise UnavailableError(
            "anthropic package not installed. Run: pip install anthropic"
        )

    client = anthropic.AsyncAnthropic(api_key=api_key)

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

    response = await client.messages.create(**kwargs)
    text = response.content[0].text if response.content else ""
    log.debug("Claude async API response: %d chars", len(text))
    return ClaudeResponse(text=text)


async def _acall_cli(
    prompt: str, system: str | None = None, model: str = CLAUDE_CHAT_MODEL,
    messages: list[dict[str, str]] | None = None,
) -> ClaudeResponse:
    binary = _find_claude_binary()
    if not binary:
        raise UnavailableError(
            "Claude CLI not found. Install Claude Code or provide an API key."
        )

    if messages is not None:
        parts = []
        for msg in messages:
            prefix = "User" if msg["role"] == "user" else "Assistant"
            parts.append(f"{prefix}: {msg['content']}")
        prompt = "\n\n".join(parts)

    cmd = [
        binary, "-p", prompt,
        "--model", model,
        "--output-format", "json",
        "--disallowedTools", _DISALLOWED_TOOLS,
    ]
    if system:
        cmd.extend(["--system-prompt", system])

    env = os.environ.copy()
    for secret_key in ("ANTHROPIC_API_KEY", "SESSION_SECRET", "DATABASE_URL", "REDIS_URL"):
        env.pop(secret_key, None)

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

    try:
        outer = json.loads(stdout)
        text = outer.get("result", stdout)
    except json.JSONDecodeError:
        text = stdout

    log.debug("Claude async CLI response: %d chars", len(text))
    return ClaudeResponse(text=text.strip())


def _find_claude_binary() -> str | None:
    """Find the Claude CLI binary on PATH or in VS Code extensions."""
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
