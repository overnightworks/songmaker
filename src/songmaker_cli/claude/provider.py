"""Claude provider — unified interface for CLI and API backends.

Both the lyrical_coherence scorer and the chat co-writing endpoint
use this module. The backend is selected based on available credentials:

1. API key provided (BYOK or env var) → ApiProvider
2. Claude CLI on PATH or in VS Code → CliProvider
3. Neither → raises UnavailableError
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

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
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 1024,
) -> ClaudeResponse:
    """Call Claude using the best available backend.

    Args:
        prompt: The user message to send.
        api_key: Anthropic API key (BYOK). If provided, uses API.
        system: Optional system prompt.
        model: Model ID for API calls.
        max_tokens: Max response tokens for API calls.

    Returns:
        ClaudeResponse with the text response.
    """
    if api_key:
        log.info("Claude: using API backend (model=%s)", model)
        return _call_api(prompt, api_key, system, model, max_tokens)
    log.info("Claude: using CLI backend")
    return _call_cli(prompt, system)


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
        kwargs["system"] = system

    response = client.messages.create(**kwargs)
    text = response.content[0].text if response.content else ""
    log.debug("Claude API response: %d chars", len(text))
    return ClaudeResponse(text=text)


def _call_cli(prompt: str, system: str | None = None) -> ClaudeResponse:
    """Call Claude via the Claude Code CLI (uses Max subscription)."""
    binary = _find_claude_binary()
    if not binary:
        raise UnavailableError(
            "Claude CLI not found. Install Claude Code or provide an API key."
        )

    cmd = [binary, "-p", prompt, "--output-format", "json"]
    if system:
        cmd.extend(["--system-prompt", system])

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise UnavailableError("Claude CLI timed out after 120s")

    if proc.returncode != 0:
        raise UnavailableError(f"Claude CLI error: {proc.stderr[:300]}")

    try:
        outer = json.loads(proc.stdout)
        text = outer.get("result", proc.stdout)
    except json.JSONDecodeError:
        text = proc.stdout

    log.debug("Claude CLI response: %d chars", len(text))
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
