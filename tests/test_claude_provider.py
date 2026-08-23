"""Tests for the Claude provider — API + CLI backends."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from songmaker_cli.claude.provider import (
    ClaudeResponse,
    UnavailableError,
    _acall_cli,
    _call_api,
    _call_cli,
    _find_claude_binary,
    acall_claude,
    call_claude,
    clear_client_cache,
    is_available,
    parse_json_response,
)
from songmaker_cli.constants import SECRET_ENV_KEYS


@pytest.fixture(autouse=True)
def _clear_claude_clients():
    clear_client_cache()
    yield
    clear_client_cache()


def _leaked_secret_env_values() -> dict[str, str]:
    """A value per SECRET_ENV_KEYS entry, shaped so DSN-parsing settings
    modules imported by other fixtures during teardown don't choke on it."""
    values = dict.fromkeys(SECRET_ENV_KEYS, "leaked-value")
    values["DATABASE_URL"] = "postgresql://leaked:leaked@leaked-host/leaked"
    values["REDIS_URL"] = "redis://leaked-host:6379/0"
    return values

# ── call_claude routing ─────────────────────────────────────────────


def test_call_claude_routes_to_api_with_key() -> None:
    resp = ClaudeResponse(text="hi")
    with patch("songmaker_cli.claude.provider._call_api", return_value=resp) as mock:
        result = call_claude("hello", api_key="sk-test")
    mock.assert_called_once()
    assert result.text == "hi"


def test_call_claude_routes_to_cli_without_key() -> None:
    resp = ClaudeResponse(text="yo")
    with patch("songmaker_cli.claude.provider._call_cli", return_value=resp) as mock:
        result = call_claude("hello")
    mock.assert_called_once()
    assert result.text == "yo"


# ── acall_claude routing ──────────────────────────────────────────


def test_acall_claude_routes_to_api_with_key() -> None:
    import asyncio
    from unittest.mock import AsyncMock

    resp = ClaudeResponse(text="async hi")
    mock = AsyncMock(return_value=resp)
    with patch("songmaker_cli.claude.provider._acall_api", mock):
        result = asyncio.run(acall_claude("hello", api_key="sk-test"))
    mock.assert_called_once()
    assert result.text == "async hi"


def test_acall_claude_routes_to_cli_without_key() -> None:
    import asyncio
    from unittest.mock import AsyncMock

    resp = ClaudeResponse(text="async yo")
    mock = AsyncMock(return_value=resp)
    with patch("songmaker_cli.claude.provider._acall_cli", mock):
        result = asyncio.run(acall_claude("hello"))
    mock.assert_called_once()
    assert result.text == "async yo"


# ── is_available ────────────────────────────────────────────────────


def test_is_available_with_api_key() -> None:
    assert is_available(api_key="sk-test") is True


def test_is_available_with_cli_binary() -> None:
    with patch("songmaker_cli.claude.provider._find_claude_binary", return_value="/usr/bin/claude"):
        assert is_available(api_key=None) is True


def test_is_available_neither() -> None:
    with patch("songmaker_cli.claude.provider._find_claude_binary", return_value=None):
        assert is_available(api_key=None) is False


# ── _call_api ───────────────────────────────────────────────────────


def test_call_api_success() -> None:
    mock_client = MagicMock()
    mock_content = MagicMock()
    mock_content.text = "response text"
    mock_client.messages.create.return_value = MagicMock(content=[mock_content])

    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        result = _call_api("hello", "sk-test", None, "claude-sonnet-4-20250514", 1024)

    assert result.text == "response text"


def test_call_api_with_system_prompt() -> None:
    mock_client = MagicMock()
    mock_content = MagicMock()
    mock_content.text = "ok"
    mock_client.messages.create.return_value = MagicMock(content=[mock_content])

    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        _call_api("hello", "sk-test", "be helpful", "claude-sonnet-4-20250514", 1024)

    kwargs = mock_client.messages.create.call_args[1]
    assert kwargs["system"] == [
        {"type": "text", "text": "be helpful", "cache_control": {"type": "ephemeral"}},
    ]


def test_call_api_empty_response() -> None:
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(content=[])

    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        result = _call_api("hello", "sk-test", None, "claude-sonnet-4-20250514", 1024)

    assert result.text == ""


def test_call_api_no_anthropic_package() -> None:
    with patch.dict("sys.modules", {"anthropic": None}):
        with pytest.raises(UnavailableError, match="anthropic package not installed"):
            _call_api("hello", "sk-test", None, "claude-sonnet-4-20250514", 1024)


# ── _call_cli ───────────────────────────────────────────────────────


def test_call_cli_success() -> None:
    json_output = json.dumps({"result": "cli response"})
    mock_proc = MagicMock(returncode=0, stdout=json_output, stderr="")

    with (
        patch("songmaker_cli.claude.provider._find_claude_binary", return_value="/usr/bin/claude"),
        patch("subprocess.run", return_value=mock_proc),
    ):
        result = _call_cli("hello")

    assert result.text == "cli response"


def test_call_cli_strips_secrets_from_child_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _leaked_secret_env_values().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("PATH", "/usr/bin")
    mock_proc = MagicMock(returncode=0, stdout='{"result": "ok"}', stderr="")

    with (
        patch("songmaker_cli.claude.provider._find_claude_binary", return_value="/usr/bin/claude"),
        patch("subprocess.run", return_value=mock_proc) as mock_run,
    ):
        _call_cli("hello")

    child_env = mock_run.call_args.kwargs["env"]
    for key in SECRET_ENV_KEYS:
        assert key not in child_env
    assert child_env["PATH"] == "/usr/bin"


def test_call_cli_with_system_prompt() -> None:
    mock_proc = MagicMock(returncode=0, stdout='{"result": "ok"}', stderr="")

    with (
        patch("songmaker_cli.claude.provider._find_claude_binary", return_value="/usr/bin/claude"),
        patch("subprocess.run", return_value=mock_proc) as mock_run,
    ):
        _call_cli("hello", system="be helpful")

    cmd = mock_run.call_args[0][0]
    assert "--system-prompt" not in cmd
    assert "be helpful" not in cmd
    assert "hello" not in cmd
    assert mock_run.call_args.kwargs["input"] == "be helpful\n\nhello"


def test_acall_cli_keeps_prompt_and_system_out_of_argv() -> None:
    proc = MagicMock(returncode=0)
    proc.communicate = AsyncMock(return_value=(b'{"result":"ok"}', b""))
    create = AsyncMock(return_value=proc)

    with (
        patch(
            "songmaker_cli.claude.provider._find_claude_binary",
            return_value="/usr/bin/claude",
        ),
        patch("asyncio.create_subprocess_exec", create),
    ):
        result = asyncio.run(_acall_cli("secret prompt", system="secret system"))

    assert result.text == "ok"
    command = create.call_args.args
    assert "secret prompt" not in command
    assert "secret system" not in command
    proc.communicate.assert_awaited_once_with(b"secret system\n\nsecret prompt")


def test_acall_cli_strips_secrets_from_child_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _leaked_secret_env_values().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("PATH", "/usr/bin")
    proc = MagicMock(returncode=0)
    proc.communicate = AsyncMock(return_value=(b'{"result":"ok"}', b""))
    create = AsyncMock(return_value=proc)

    with (
        patch(
            "songmaker_cli.claude.provider._find_claude_binary",
            return_value="/usr/bin/claude",
        ),
        patch("asyncio.create_subprocess_exec", create),
    ):
        asyncio.run(_acall_cli("hello"))

    child_env = create.call_args.kwargs["env"]
    for key in SECRET_ENV_KEYS:
        assert key not in child_env
    assert child_env["PATH"] == "/usr/bin"


def test_call_cli_passes_model() -> None:
    mock_proc = MagicMock(returncode=0, stdout='{"result": "ok"}', stderr="")

    with (
        patch("songmaker_cli.claude.provider._find_claude_binary", return_value="/usr/bin/claude"),
        patch("subprocess.run", return_value=mock_proc) as mock_run,
    ):
        _call_cli("hello", model="claude-haiku-4-5-20251001")

    cmd = mock_run.call_args[0][0]
    assert "--model" in cmd
    model_idx = cmd.index("--model")
    assert cmd[model_idx + 1] == "claude-haiku-4-5-20251001"


def test_call_cli_plain_text_output() -> None:
    mock_proc = MagicMock(returncode=0, stdout="plain text response", stderr="")

    with (
        patch("songmaker_cli.claude.provider._find_claude_binary", return_value="/usr/bin/claude"),
        patch("subprocess.run", return_value=mock_proc),
    ):
        result = _call_cli("hello")

    assert result.text == "plain text response"


def test_call_cli_no_binary() -> None:
    with patch("songmaker_cli.claude.provider._find_claude_binary", return_value=None):
        with pytest.raises(UnavailableError, match="Claude CLI not found"):
            _call_cli("hello")


def test_call_cli_error() -> None:
    mock_proc = MagicMock(returncode=1, stdout="", stderr="error message")

    with (
        patch("songmaker_cli.claude.provider._find_claude_binary", return_value="/usr/bin/claude"),
        patch("subprocess.run", return_value=mock_proc),
    ):
        with pytest.raises(UnavailableError, match="Claude CLI is unavailable"):
            _call_cli("hello")


def test_call_cli_timeout() -> None:
    import subprocess

    with (
        patch("songmaker_cli.claude.provider._find_claude_binary", return_value="/usr/bin/claude"),
        patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=120)),
    ):
        with pytest.raises(UnavailableError, match="timed out"):
            _call_cli("hello")


# ── _find_claude_binary ─────────────────────────────────────────────


def test_find_binary_on_path() -> None:
    with patch("shutil.which", return_value="/usr/bin/claude"):
        assert _find_claude_binary() == "/usr/bin/claude"


def test_find_binary_in_vscode(tmp_path: Path) -> None:
    ext_dir = tmp_path / ".vscode" / "extensions" / "anthropic.claude-code-1.0.0"
    binary = ext_dir / "resources" / "native-binary" / "claude"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh")

    with (
        patch("shutil.which", return_value=None),
        patch("pathlib.Path.home", return_value=tmp_path),
    ):
        result = _find_claude_binary()

    assert result is not None
    assert "claude" in result


def test_find_binary_not_found() -> None:
    with (
        patch("shutil.which", return_value=None),
        patch("pathlib.Path.home", return_value=Path("/nonexistent")),
    ):
        assert _find_claude_binary() is None


# ── parse_json_response ─────────────────────────────────────────────


def test_parse_json_response_plain() -> None:
    result = parse_json_response('{"score": 8, "summary": "good"}')
    assert result["score"] == 8


def test_parse_json_response_markdown_wrapped() -> None:
    text = '```json\n{"score": 9}\n```'
    result = parse_json_response(text)
    assert result["score"] == 9


def test_parse_json_response_markdown_no_lang() -> None:
    text = '```\n{"score": 7}\n```'
    result = parse_json_response(text)
    assert result["score"] == 7
