"""Tests for the Claude provider — API + CLI backends."""

from __future__ import annotations

import asyncio
import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from songmaker_cli.claude import provider
from songmaker_cli.claude.provider import (
    MCP_ALLOWED_TOOLS,
    ClaudeResponse,
    CliToolSurfaceError,
    UnavailableError,
    _acall_cli,
    _build_cli_cmd,
    _build_mcp_cli_cmd,
    _call_api,
    _call_cli,
    _find_claude_binary,
    acall_claude,
    acall_claude_with_mcp_stream,
    averify_no_builtin_cli_tools,
    call_claude,
    clear_cli_login_status_cache,
    clear_cli_tool_surface_cache,
    clear_client_cache,
    cli_login_status,
    is_available,
    list_cli_model_aliases,
    parse_json_response,
    verify_cli_tool_surface,
    verify_no_builtin_cli_tools,
)
from songmaker_cli.constants import SECRET_ENV_KEYS


@pytest.fixture(autouse=True)
def _clear_claude_clients():
    clear_client_cache()
    clear_cli_login_status_cache()
    clear_cli_tool_surface_cache()
    yield
    clear_client_cache()
    clear_cli_login_status_cache()
    clear_cli_tool_surface_cache()


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


# ── cli_login_status ───────────────────────────────────────────────


def _auth_status_result(stdout: str, returncode: int = 0) -> MagicMock:
    return MagicMock(stdout=stdout, stderr="", returncode=returncode)


def test_cli_login_status_reads_logged_in_json() -> None:
    payload = json.dumps({"loggedIn": True, "authMethod": "claude.ai"})
    with (
        patch(
            "songmaker_cli.claude.provider._find_claude_binary",
            return_value="/usr/bin/claude",
        ),
        patch(
            "songmaker_cli.claude.provider.subprocess.run",
            return_value=_auth_status_result(payload),
        ),
    ):
        status = cli_login_status()

    assert status.logged_in is True
    assert status.auth_method == "claude.ai"


def test_cli_login_status_no_binary_is_logged_out() -> None:
    with patch("songmaker_cli.claude.provider._find_claude_binary", return_value=None):
        status = cli_login_status()

    assert status.logged_in is False
    assert status.auth_method is None


def test_cli_login_status_not_logged_in() -> None:
    payload = json.dumps({"loggedIn": False})
    with (
        patch(
            "songmaker_cli.claude.provider._find_claude_binary",
            return_value="/usr/bin/claude",
        ),
        patch(
            "songmaker_cli.claude.provider.subprocess.run",
            return_value=_auth_status_result(payload),
        ),
    ):
        status = cli_login_status()

    assert status.logged_in is False
    assert status.auth_method is None


def test_cli_login_status_malformed_json_is_logged_out() -> None:
    with (
        patch(
            "songmaker_cli.claude.provider._find_claude_binary",
            return_value="/usr/bin/claude",
        ),
        patch(
            "songmaker_cli.claude.provider.subprocess.run",
            return_value=_auth_status_result("not json"),
        ),
    ):
        status = cli_login_status()

    assert status.logged_in is False


def test_cli_login_status_timeout_is_logged_out() -> None:
    with (
        patch(
            "songmaker_cli.claude.provider._find_claude_binary",
            return_value="/usr/bin/claude",
        ),
        patch(
            "songmaker_cli.claude.provider.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=15),
        ),
    ):
        status = cli_login_status()

    assert status.logged_in is False


def test_cli_login_status_reuses_a_recent_probe_instead_of_spawning_again() -> None:
    payload = json.dumps({"loggedIn": True, "authMethod": "claude.ai"})
    with (
        patch(
            "songmaker_cli.claude.provider._find_claude_binary",
            return_value="/usr/bin/claude",
        ),
        patch(
            "songmaker_cli.claude.provider.subprocess.run",
            return_value=_auth_status_result(payload),
        ) as run,
    ):
        first = cli_login_status()
        second = cli_login_status()

    assert first == second
    run.assert_called_once()


def test_cli_login_status_probes_again_once_the_cache_is_cleared() -> None:
    payload = json.dumps({"loggedIn": True, "authMethod": "claude.ai"})
    with (
        patch(
            "songmaker_cli.claude.provider._find_claude_binary",
            return_value="/usr/bin/claude",
        ),
        patch(
            "songmaker_cli.claude.provider.subprocess.run",
            return_value=_auth_status_result(payload),
        ) as run,
    ):
        cli_login_status()
        clear_cli_login_status_cache()
        cli_login_status()

    assert run.call_count == 2


# ── list_cli_model_aliases ───────────────────────────────────────────


def _model_command_result(stdout: str, returncode: int = 0) -> MagicMock:
    return MagicMock(stdout=stdout, stderr="", returncode=returncode)


def test_list_cli_model_aliases_parses_available_line() -> None:
    stdout = (
        "Current model: `Opus 5 (1M context)` (effort: high)\n"
        "Usage: /model <name>. Available: sonnet, opus, haiku, fable, best, "
        "sonnet[1m], opus[1m], fable[1m], opusplan, default, or a full model ID.\n"
    )
    with (
        patch(
            "songmaker_cli.claude.provider._find_claude_binary",
            return_value="/usr/bin/claude",
        ),
        patch(
            "songmaker_cli.claude.provider.subprocess.run",
            return_value=_model_command_result(stdout),
        ),
    ):
        aliases = list_cli_model_aliases()

    assert aliases == [
        "sonnet", "opus", "haiku", "fable", "best",
        "sonnet[1m]", "opus[1m]", "fable[1m]", "opusplan", "default",
    ]


def test_list_cli_model_aliases_unexpected_output_raises_named_error() -> None:
    with (
        patch(
            "songmaker_cli.claude.provider._find_claude_binary",
            return_value="/usr/bin/claude",
        ),
        patch(
            "songmaker_cli.claude.provider.subprocess.run",
            return_value=_model_command_result("no usable output here\n"),
        ),
    ):
        with pytest.raises(UnavailableError, match="did not contain a parseable"):
            list_cli_model_aliases()


def test_list_cli_model_aliases_no_binary_raises_named_error() -> None:
    with patch("songmaker_cli.claude.provider._find_claude_binary", return_value=None):
        with pytest.raises(UnavailableError, match="Claude CLI not found"):
            list_cli_model_aliases()


def test_list_cli_model_aliases_timeout_raises_named_error() -> None:
    with (
        patch(
            "songmaker_cli.claude.provider._find_claude_binary",
            return_value="/usr/bin/claude",
        ),
        patch(
            "songmaker_cli.claude.provider.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=15),
        ),
    ):
        with pytest.raises(UnavailableError, match="timed out"):
            list_cli_model_aliases()


def test_list_cli_model_aliases_nonzero_exit_raises_named_error() -> None:
    with (
        patch(
            "songmaker_cli.claude.provider._find_claude_binary",
            return_value="/usr/bin/claude",
        ),
        patch(
            "songmaker_cli.claude.provider.subprocess.run",
            return_value=_model_command_result("", returncode=1),
        ),
    ):
        with pytest.raises(UnavailableError, match="exited 1"):
            list_cli_model_aliases()


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


# ── _call_cli / _acall_cli ──────────────────────────────────────────
#
# Both are gated by verify_no_builtin_cli_tools() / averify_no_builtin_
# cli_tools() before they build a command or spawn anything (Finding 1 of
# the #351 review — this is the one funnel every non-MCP CLI call shares,
# so chat_api.py's legacy endpoint and the lyrical-coherence judge inherit
# the gate without either having to call it themselves). The tests below
# that exercise _call_cli's/_acall_cli's OWN behavior (command shape,
# secret scrubbing, error handling) bypass the gate via the fixture below;
# the gate's own wiring and behavior get their own tests further down.


@pytest.fixture
def _no_tool_gate_open(monkeypatch: pytest.MonkeyPatch):
    """Stand in for a CLI that already passed the tool-surface gate,
    resolved to ``/usr/bin/claude`` — so tests here can focus on what
    ``_call_cli``/``_acall_cli`` do with that verified binary."""
    monkeypatch.setattr(provider, "verify_no_builtin_cli_tools", lambda: "/usr/bin/claude")
    monkeypatch.setattr(
        provider, "averify_no_builtin_cli_tools", AsyncMock(return_value="/usr/bin/claude"),
    )


def test_call_cli_success(_no_tool_gate_open) -> None:
    json_output = json.dumps({"result": "cli response"})
    mock_proc = MagicMock(returncode=0, stdout=json_output, stderr="")

    with patch("subprocess.run", return_value=mock_proc):
        result = _call_cli("hello")

    assert result.text == "cli response"


def test_call_cli_strips_secrets_from_child_env(
    _no_tool_gate_open, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in _leaked_secret_env_values().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("PATH", "/usr/bin")
    mock_proc = MagicMock(returncode=0, stdout='{"result": "ok"}', stderr="")

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        _call_cli("hello")

    child_env = mock_run.call_args.kwargs["env"]
    for key in SECRET_ENV_KEYS:
        assert key not in child_env
    assert child_env["PATH"] == "/usr/bin"


def test_call_cli_with_system_prompt(_no_tool_gate_open) -> None:
    mock_proc = MagicMock(returncode=0, stdout='{"result": "ok"}', stderr="")

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        _call_cli("hello", system="be helpful")

    cmd = mock_run.call_args[0][0]
    assert "--system-prompt" not in cmd
    assert "be helpful" not in cmd
    assert "hello" not in cmd
    assert mock_run.call_args.kwargs["input"] == "be helpful\n\nhello"


def test_acall_cli_keeps_prompt_and_system_out_of_argv(_no_tool_gate_open) -> None:
    proc = MagicMock(returncode=0)
    proc.communicate = AsyncMock(return_value=(b'{"result":"ok"}', b""))
    create = AsyncMock(return_value=proc)

    with patch("asyncio.create_subprocess_exec", create):
        result = asyncio.run(_acall_cli("secret prompt", system="secret system"))

    assert result.text == "ok"
    command = create.call_args.args
    assert "secret prompt" not in command
    assert "secret system" not in command
    proc.communicate.assert_awaited_once_with(b"secret system\n\nsecret prompt")


def test_acall_cli_strips_secrets_from_child_env(
    _no_tool_gate_open, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key, value in _leaked_secret_env_values().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("PATH", "/usr/bin")
    proc = MagicMock(returncode=0)
    proc.communicate = AsyncMock(return_value=(b'{"result":"ok"}', b""))
    create = AsyncMock(return_value=proc)

    with patch("asyncio.create_subprocess_exec", create):
        asyncio.run(_acall_cli("hello"))

    child_env = create.call_args.kwargs["env"]
    for key in SECRET_ENV_KEYS:
        assert key not in child_env
    assert child_env["PATH"] == "/usr/bin"


def test_call_cli_passes_model(_no_tool_gate_open) -> None:
    mock_proc = MagicMock(returncode=0, stdout='{"result": "ok"}', stderr="")

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        _call_cli("hello", model="claude-haiku-4-5-20251001")

    cmd = mock_run.call_args[0][0]
    assert "--model" in cmd
    model_idx = cmd.index("--model")
    assert cmd[model_idx + 1] == "claude-haiku-4-5-20251001"


def test_call_cli_plain_text_output(_no_tool_gate_open) -> None:
    mock_proc = MagicMock(returncode=0, stdout="plain text response", stderr="")

    with patch("subprocess.run", return_value=mock_proc):
        result = _call_cli("hello")

    assert result.text == "plain text response"


def test_call_cli_no_binary(monkeypatch) -> None:
    # The autouse conftest fixture stubs the gate out for every other test's
    # safety; undo that here so this test proves the real gate — not a
    # stand-in for it — is what surfaces "no binary" through _call_cli.
    monkeypatch.setattr(provider, "verify_no_builtin_cli_tools", verify_no_builtin_cli_tools)
    with patch("songmaker_cli.claude.provider._find_claude_binary", return_value=None):
        with pytest.raises(UnavailableError, match="Claude CLI not found"):
            _call_cli("hello")


def test_call_cli_error(_no_tool_gate_open) -> None:
    mock_proc = MagicMock(returncode=1, stdout="", stderr="error message")

    with patch("subprocess.run", return_value=mock_proc):
        with pytest.raises(UnavailableError, match="Claude CLI is unavailable"):
            _call_cli("hello")


def test_call_cli_timeout(_no_tool_gate_open) -> None:
    import subprocess

    with patch(
        "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=120),
    ):
        with pytest.raises(UnavailableError, match="timed out"):
            _call_cli("hello")


def test_call_cli_refuses_a_cli_the_gate_rejects(_no_tool_gate_open, monkeypatch) -> None:
    monkeypatch.setattr(
        provider, "verify_no_builtin_cli_tools",
        MagicMock(side_effect=CliToolSurfaceError("Bash")),
    )
    with patch("subprocess.run") as mock_run:
        with pytest.raises(CliToolSurfaceError):
            _call_cli("hello")
    mock_run.assert_not_called()


def test_acall_cli_refuses_a_cli_the_gate_rejects(_no_tool_gate_open, monkeypatch) -> None:
    monkeypatch.setattr(
        provider, "averify_no_builtin_cli_tools",
        AsyncMock(side_effect=CliToolSurfaceError("Bash")),
    )
    create = AsyncMock()
    with patch("asyncio.create_subprocess_exec", create):
        with pytest.raises(CliToolSurfaceError):
            asyncio.run(_acall_cli("hello"))
    create.assert_not_called()


def test_call_cli_executes_the_binary_the_gate_verified(monkeypatch) -> None:
    """The gate resolves the CLI's symlink to its literal build path
    (#351 Finding 4); ``_call_cli`` must run that same path, not whatever
    ``_find_claude_binary`` alone would return."""
    monkeypatch.setattr(
        provider, "verify_no_builtin_cli_tools", lambda: "/opt/claude/versions/2.1.257",
    )
    monkeypatch.setattr(
        provider, "_find_claude_binary", lambda: "/usr/local/bin/claude",
    )
    mock_proc = MagicMock(returncode=0, stdout='{"result": "ok"}', stderr="")

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        _call_cli("hello")

    assert mock_run.call_args[0][0][0] == "/opt/claude/versions/2.1.257"


def test_acall_cli_executes_the_binary_the_gate_verified(monkeypatch) -> None:
    monkeypatch.setattr(
        provider, "averify_no_builtin_cli_tools",
        AsyncMock(return_value="/opt/claude/versions/2.1.257"),
    )
    monkeypatch.setattr(
        provider, "_find_claude_binary", lambda: "/usr/local/bin/claude",
    )
    proc = MagicMock(returncode=0)
    proc.communicate = AsyncMock(return_value=(b'{"result":"ok"}', b""))
    create = AsyncMock(return_value=proc)

    with patch("asyncio.create_subprocess_exec", create):
        asyncio.run(_acall_cli("hello"))

    assert create.call_args.args[0] == "/opt/claude/versions/2.1.257"


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


# ── tool allowlist ──────────────────────────────────────────────────


def _flag_value(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


def test_cowriter_command_offers_no_builtin_tool() -> None:
    cmd = _build_mcp_cli_cmd("claude", "opus", "/tmp/mcp.json")

    assert _flag_value(cmd, "--tools") == ""
    assert _flag_value(cmd, "--allowedTools") == MCP_ALLOWED_TOOLS
    assert "--disallowedTools" not in cmd
    assert "bypassPermissions" not in cmd


def test_cowriter_command_ignores_the_mounted_settings_file() -> None:
    cmd = _build_mcp_cli_cmd("claude", "opus", "/tmp/mcp.json")

    assert _flag_value(cmd, "--setting-sources") == ""
    assert "--strict-mcp-config" in cmd


def test_cowriter_command_disables_slash_commands() -> None:
    cmd = _build_mcp_cli_cmd("claude", "opus", "/tmp/mcp.json")

    assert "--disable-slash-commands" in cmd


def test_tool_free_command_offers_no_tool_at_all() -> None:
    cmd = _build_cli_cmd("claude", "opus")

    assert _flag_value(cmd, "--tools") == ""
    assert "--allowedTools" not in cmd
    assert "--disable-slash-commands" in cmd


# ── tool-surface verification ───────────────────────────────────────
#
# Two gates share one probe mechanism (see the block comment above
# ``verify_cli_tool_surface`` in provider.py): the MCP-attached one used by
# the co-writer, expecting exactly the eleven songmaker tools, and the
# no-builtin-tools one used by ``_call_cli``/``_acall_cli``, expecting none
# at all. Both are exercised below.


def _init_line(
    tools: list[str],
    *,
    slash_commands: list[str] | None = None,
    mcp_connected: bool = True,
) -> bytes:
    """A ``system``/``init`` line. ``mcp_connected`` only matters to the
    MCP-attached probe (the no-MCP probe never reads ``mcp_servers`` at
    all) — defaults to a connected songmaker server so every existing
    MCP-attached test keeps proving what it always proved."""
    return json.dumps({
        "type": "system",
        "subtype": "init",
        "tools": tools,
        "slash_commands": slash_commands or [],
        "mcp_servers": [
            {"name": "songmaker", "status": "connected" if mcp_connected else "failed"},
        ],
    }).encode() + b"\n"


def _fake_cli(first_line: bytes, *, still_running: bool = False) -> MagicMock:
    proc = MagicMock()
    proc.pid = 4242
    proc.returncode = None if still_running else 0
    proc.stdin = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.stdout = MagicMock()
    proc.stdout.readline = AsyncMock(return_value=first_line)
    proc.wait = AsyncMock(return_value=None)
    return proc


@pytest.fixture
def claude_binary(tmp_path: Path):
    """A stand-in binary file, so its build identity can be stat()ed."""
    binary = tmp_path / "claude"
    binary.write_bytes(b"cli-build-one")
    with patch(
        "songmaker_cli.claude.provider._require_claude_binary",
        return_value=str(binary),
    ):
        yield binary


def _answer_with(monkeypatch, *lines: bytes) -> list[tuple[str, ...]]:
    """Let the next probes read ``lines`` in turn; collect the commands used."""
    commands: list[tuple[str, ...]] = []
    queued = list(lines)

    async def fake_exec(*cmd, **_kw):
        commands.append(cmd)
        return _fake_cli(queued.pop(0))

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    return commands


_ALL_SONGMAKER_TOOLS = sorted(provider._EXPECTED_MCP_TOOL_NAMES)


def test_tool_surface_accepts_a_cli_offering_exactly_the_eleven_songmaker_tools(
    claude_binary, monkeypatch,
) -> None:
    _answer_with(monkeypatch, _init_line(_ALL_SONGMAKER_TOOLS))

    binary = asyncio.run(verify_cli_tool_surface())

    assert binary == str(claude_binary)


def test_tool_surface_rejects_a_cli_offering_an_unlisted_tool(
    claude_binary, monkeypatch,
) -> None:
    _answer_with(monkeypatch, _init_line([*_ALL_SONGMAKER_TOOLS, "Bash"]))

    with pytest.raises(CliToolSurfaceError) as exc:
        asyncio.run(verify_cli_tool_surface())
    assert "Bash" in str(exc.value)


def test_tool_surface_rejects_a_cli_offering_fewer_than_the_eleven_tools(
    claude_binary, monkeypatch,
) -> None:
    """A drift check that only flags additions would miss the songmaker
    server silently losing a registration too — #351 Finding 2 wants the
    reported set compared exactly, not just checked for extras."""
    _answer_with(monkeypatch, _init_line(_ALL_SONGMAKER_TOOLS[:-1]))

    with pytest.raises(CliToolSurfaceError) as exc:
        asyncio.run(verify_cli_tool_surface())
    assert "missing tools" in str(exc.value)
    assert _ALL_SONGMAKER_TOOLS[-1] in str(exc.value)


def test_tool_surface_rejects_a_cli_that_still_advertises_slash_commands(
    claude_binary, monkeypatch,
) -> None:
    _answer_with(
        monkeypatch,
        _init_line(_ALL_SONGMAKER_TOOLS, slash_commands=["/compact"]),
    )

    with pytest.raises(CliToolSurfaceError) as exc:
        asyncio.run(verify_cli_tool_surface())
    assert "/compact" in str(exc.value)


def test_tool_surface_is_probed_with_the_cowriter_restrictions(
    claude_binary, monkeypatch,
) -> None:
    commands = _answer_with(monkeypatch, _init_line(_ALL_SONGMAKER_TOOLS))

    asyncio.run(verify_cli_tool_surface())

    probe = list(commands[0])
    assert _flag_value(probe, "--tools") == ""
    assert _flag_value(probe, "--setting-sources") == ""
    assert "--strict-mcp-config" in probe
    assert "--disable-slash-commands" in probe
    assert _flag_value(probe, "--allowedTools") == MCP_ALLOWED_TOOLS
    assert "--mcp-config" in probe


def test_tool_surface_probe_stops_the_session_it_started(
    claude_binary, monkeypatch,
) -> None:
    killed: list[int] = []

    async def fake_exec(*_cmd, **_kw):
        return _fake_cli(_init_line(_ALL_SONGMAKER_TOOLS), still_running=True)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
    monkeypatch.setattr(provider.os, "killpg", lambda pid, _sig: killed.append(pid))

    asyncio.run(verify_cli_tool_surface())

    assert killed == [4242]


# ── reap after SIGKILL is bounded (#351 rounds 4-5) ───────────────────
#
# Round 3 added single-flight; round 4 bounded the post-SIGKILL wait but
# left it inside the same held lock, so a stuck reap could still block
# every later caller of that key. Round 5 removed the held lock entirely
# (see the single-flight section below) and added a capped, deduplicated
# registry for the background reapers a stuck process gets handed to —
# without a cap, a run of bad probes could grow an unbounded pool of
# waiting tasks/threads (the review's own math: ~225/hour at one per
# immediately-invalid probe).
#
# _bounded_wait / _bounded_wait_sync are the one seam where these tests
# genuinely need real (tiny) timing — that is their actual job. Everything
# built on top of them (zombie tracking, the registry cap, dedup) is
# tested by stubbing that seam instead: deterministic, no clock involved.


def test_bounded_wait_respects_its_timeout() -> None:
    async def _hang() -> None:
        await asyncio.sleep(999)

    proc = MagicMock()
    proc.wait = AsyncMock(side_effect=_hang)

    completed = asyncio.run(asyncio.wait_for(provider._bounded_wait(proc, 0.02), timeout=2))

    assert completed is False


def test_bounded_wait_sync_respects_its_timeout() -> None:
    def _hang(timeout=None):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout)

    proc = MagicMock()
    proc.wait.side_effect = _hang

    assert provider._bounded_wait_sync(proc, 0.02) is False


def test_reap_process_group_tracks_a_zombie_when_the_wait_never_confirms_exit(
    monkeypatch, caplog,
) -> None:
    """No real waiting anywhere: _bounded_wait is stubbed to always report
    'not yet', so the zombie path is exercised deterministically rather
    than resting on a real (even if tiny) wall-clock budget."""
    caplog.set_level("ERROR")
    signals: list[int] = []
    monkeypatch.setattr(provider.os, "killpg", lambda _pid, sig: signals.append(sig))
    monkeypatch.setattr(provider, "_bounded_wait", AsyncMock(return_value=False))
    tracked: list[int] = []
    monkeypatch.setattr(
        provider, "_track_zombie_reap_async",
        lambda proc: tracked.append(proc.pid) or True,
    )

    proc = MagicMock()
    proc.pid = 9999
    proc.returncode = None

    became_zombie = asyncio.run(provider._reap_process_group(proc))

    assert became_zombie is True
    assert tracked == [9999]
    assert signals == [provider.signal.SIGTERM, provider.signal.SIGKILL]


def test_reap_process_group_sync_tracks_a_zombie_when_the_wait_never_confirms_exit(
    monkeypatch,
) -> None:
    signals: list[int] = []
    monkeypatch.setattr(provider.os, "killpg", lambda _pid, sig: signals.append(sig))
    monkeypatch.setattr(provider, "_bounded_wait_sync", lambda _proc, _timeout: False)
    tracked: list[int] = []
    monkeypatch.setattr(
        provider, "_track_zombie_reap_sync",
        lambda proc: tracked.append(proc.pid) or True,
    )

    proc = MagicMock()
    proc.pid = 7777
    proc.poll.return_value = None

    became_zombie = provider._reap_process_group_sync(proc)

    assert became_zombie is True
    assert tracked == [7777]
    assert signals == [provider.signal.SIGTERM, provider.signal.SIGKILL]


def test_reap_process_group_confirms_a_normal_exit_without_signaling_a_zombie(
    monkeypatch,
) -> None:
    signals: list[int] = []
    monkeypatch.setattr(provider.os, "killpg", lambda _pid, sig: signals.append(sig))
    monkeypatch.setattr(provider, "_bounded_wait", AsyncMock(return_value=True))
    tracked: list[int] = []
    monkeypatch.setattr(provider, "_track_zombie_reap_async", lambda proc: tracked.append(proc.pid))

    proc = MagicMock()
    proc.pid = 4321
    proc.returncode = None

    became_zombie = asyncio.run(provider._reap_process_group(proc))

    assert became_zombie is False
    assert tracked == []


def test_track_zombie_reap_logs_and_starts_a_background_reaper(monkeypatch, caplog) -> None:
    caplog.set_level("ERROR")
    scheduled: list[int] = []
    monkeypatch.setattr(
        provider, "_claim_zombie_reap_slot", lambda pid: scheduled.append(pid) or True,
    )
    monkeypatch.setattr(provider, "_reap_in_background", AsyncMock())

    async def _run() -> bool:
        proc = MagicMock()
        proc.pid = 5150
        return provider._track_zombie_reap_async(proc)

    became_zombie = asyncio.run(_run())

    assert became_zombie is True
    assert scheduled == [5150]
    assert any("did not exit" in r.message for r in caplog.records)


def test_track_zombie_reap_does_not_start_a_reaper_when_the_slot_is_denied(monkeypatch) -> None:
    """Dedup and the pool cap both express themselves the same way to the
    caller: the process is still reported a zombie (it is one), but no
    reaper is started for it."""
    monkeypatch.setattr(provider, "_claim_zombie_reap_slot", lambda pid: False)
    created: list[object] = []
    monkeypatch.setattr("asyncio.create_task", lambda coro: created.append(coro))

    proc = MagicMock()
    proc.pid = 5150
    became_zombie = provider._track_zombie_reap_async(proc)

    assert became_zombie is True
    assert created == []


def test_zombie_reap_slot_is_deduplicated_by_pid() -> None:
    assert provider._claim_zombie_reap_slot(101) is True
    assert provider._claim_zombie_reap_slot(101) is False

    provider._release_zombie_reap_slot(101)
    assert provider._claim_zombie_reap_slot(101) is True
    provider._release_zombie_reap_slot(101)


def test_zombie_reap_slot_pool_has_a_hard_cap(monkeypatch, caplog) -> None:
    caplog.set_level("ERROR")
    monkeypatch.setattr(provider, "CLAUDE_CLI_MAX_CONCURRENT_ZOMBIE_REAPERS", 2)

    assert provider._claim_zombie_reap_slot(1) is True
    assert provider._claim_zombie_reap_slot(2) is True
    assert provider._claim_zombie_reap_slot(3) is False
    assert any("at its cap" in r.message for r in caplog.records)

    provider._release_zombie_reap_slot(1)
    provider._release_zombie_reap_slot(2)


def test_reap_in_background_eventually_reaps_logs_and_releases_its_slot(caplog) -> None:
    """The zombie case is not silent: once the process this function was
    handed to actually does exit, that is logged too, and its registry
    slot is freed for a later zombie to use — this is where a stuck
    reap's process ultimately gets cleaned up."""
    caplog.set_level("INFO")
    provider._claim_zombie_reap_slot(8888)
    proc = MagicMock()
    proc.pid = 8888
    proc.wait = AsyncMock(return_value=0)

    asyncio.run(provider._reap_in_background(proc))

    assert any("reaped in the background" in r.message for r in caplog.records)
    assert provider._claim_zombie_reap_slot(8888) is True  # released, so claimable again
    provider._release_zombie_reap_slot(8888)


def test_reap_in_background_sync_eventually_reaps_logs_and_releases_its_slot(caplog) -> None:
    caplog.set_level("INFO")
    provider._claim_zombie_reap_slot(6666)
    proc = MagicMock()
    proc.pid = 6666
    proc.wait.return_value = 0

    provider._reap_in_background_sync(proc)

    assert any("reaped in the background" in r.message for r in caplog.records)
    assert provider._claim_zombie_reap_slot(6666) is True
    provider._release_zombie_reap_slot(6666)


def test_shutdown_zombie_reapers_cancels_every_tracked_task() -> None:
    async def _hang() -> None:
        await asyncio.sleep(999)

    async def _run() -> bool:
        task = asyncio.create_task(_hang())
        with provider._zombie_registry_lock:
            provider._zombie_reap_tasks.add(task)
        await provider.shutdown_zombie_reapers()
        return task.cancelled()

    cancelled = asyncio.run(asyncio.wait_for(_run(), timeout=2))

    assert cancelled is True





def test_tool_surface_is_probed_again_after_the_cli_updates_itself(
    claude_binary, monkeypatch,
) -> None:
    _answer_with(
        monkeypatch,
        _init_line(_ALL_SONGMAKER_TOOLS),
        _init_line([*_ALL_SONGMAKER_TOOLS, "FutureTool"]),
    )

    asyncio.run(verify_cli_tool_surface())
    claude_binary.write_bytes(b"cli-build-two-is-a-different-size")

    with pytest.raises(CliToolSurfaceError) as exc:
        asyncio.run(verify_cli_tool_surface())
    assert "FutureTool" in str(exc.value)


def test_tool_surface_is_probed_once_per_cli_build(
    claude_binary, monkeypatch,
) -> None:
    """Proves the cache across two *sequential* calls — not concurrency;
    see test_tool_surface_single_flight_serializes_concurrent_probes below
    for that (#351 round 3, Finding 2: a sequential-only stampede test
    proves nothing about two callers racing for a cold cache)."""
    commands = _answer_with(monkeypatch, _init_line(_ALL_SONGMAKER_TOOLS))

    asyncio.run(verify_cli_tool_surface())
    asyncio.run(verify_cli_tool_surface())

    assert len(commands) == 1


def test_tool_surface_single_flight_shares_one_successful_probe(
    claude_binary, monkeypatch,
) -> None:
    """#351 round 3, Finding 2: two callers racing for the same cold key
    must share one probe. Genuine concurrency via asyncio.gather — each
    fake exec sleeps first, so both coroutines are genuinely in flight
    together before either can finish, the way a sequential test cannot
    prove. Covers the success path only — see the fail-closed test below
    for the mutations this one alone cannot catch."""
    calls = 0

    async def fake_exec(*_cmd, **_kw):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return _fake_cli(_init_line(_ALL_SONGMAKER_TOOLS))

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    async def _race() -> tuple[str, str]:
        return await asyncio.gather(verify_cli_tool_surface(), verify_cli_tool_surface())

    first, second = asyncio.run(_race())

    assert calls == 1
    assert first == second == str(claude_binary)


def test_tool_surface_single_flight_waits_for_the_real_result_not_a_placeholder(
    claude_binary, monkeypatch,
) -> None:
    """#351 rounds 4-5, Finding 2: two mutations a bare ``calls == 1`` check
    on a *successful* probe cannot catch, both deterministically red here:

    1. A follower that sees the key "in flight" and returns some default
       immediately instead of waiting for the real answer.
    2. A follower that, on discovering the leader's probe *failed*, starts
       its own second probe instead of accepting the shared failure —
       invisible to a success-only test, since ``calls`` would still read 1
       there. The probe here fails outright (malformed output), not just a
       tool mismatch, specifically to exercise that path.

    No sleep loop stands in for "the follower has reached its wait": an
    explicit event, set from inside ``_await_follower_result_async`` right
    before it actually waits, is what the test awaits. The 5s wrapper is a
    deadlock guard only — everything above resolves in well under 100ms.
    """
    calls = 0
    probe_started = asyncio.Event()
    release_probe = asyncio.Event()
    follower_waiting = asyncio.Event()

    async def fake_exec(*_cmd, **_kw):
        nonlocal calls
        calls += 1
        probe_started.set()
        await release_probe.wait()
        return _fake_cli(b"not valid json\n")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    real_await_follower = provider._await_follower_result_async

    async def _instrumented_await_follower(build, future, timeout_seconds):
        follower_waiting.set()
        return await real_await_follower(build, future, timeout_seconds)

    monkeypatch.setattr(
        provider, "_await_follower_result_async", _instrumented_await_follower,
    )

    async def _race() -> list[BaseException]:
        first = asyncio.create_task(verify_cli_tool_surface())
        second = asyncio.create_task(verify_cli_tool_surface())
        await probe_started.wait()
        await follower_waiting.wait()
        assert not second.done(), (
            "second caller returned before the in-flight probe resolved — "
            "it must wait for the real answer, not assume success"
        )
        release_probe.set()
        return await asyncio.gather(first, second, return_exceptions=True)

    results = asyncio.run(asyncio.wait_for(_race(), timeout=5))

    assert calls == 1, "a follower must not start its own second probe on failure"
    assert all(isinstance(r, UnavailableError) for r in results)
    assert not any(isinstance(r, CliToolSurfaceError) for r in results)


def test_tool_surface_single_flight_shares_a_zombie_failure_across_concurrent_callers(
    monkeypatch,
) -> None:
    """A process that outlives SIGKILL turns into a _ZombieProbeError, not
    a hang: single-flight must still resolve *both* concurrent callers to
    that one refusal. The probe itself is stubbed to fail instantly — no
    real timing anywhere, deliberately, since the reap bound is already
    proven at the unit level above; this is only about single-flight
    correctly propagating a zombie failure to every waiter.
    """
    calls = 0

    async def fake_probe(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise provider._ZombieProbeError(
            "Claude CLI process group 6161 did not exit within its budget",
        )

    monkeypatch.setattr(provider, "_probe_cli_surface_async", fake_probe)

    async def _race() -> list[BaseException]:
        return await asyncio.gather(
            averify_no_builtin_cli_tools(), averify_no_builtin_cli_tools(),
            return_exceptions=True,
        )

    results = asyncio.run(asyncio.wait_for(_race(), timeout=2))

    assert calls == 1
    assert all(isinstance(r, UnavailableError) for r in results)




def test_tool_surface_reports_a_cli_that_vanished_mid_update(
    claude_binary, monkeypatch,
) -> None:
    claude_binary.unlink()

    with pytest.raises(UnavailableError):
        asyncio.run(verify_cli_tool_surface())


def test_tool_surface_rejects_a_cli_that_announces_nothing(
    claude_binary, monkeypatch,
) -> None:
    _answer_with(monkeypatch, b'{"type": "assistant"}\n')

    with pytest.raises(UnavailableError):
        asyncio.run(verify_cli_tool_surface())


def test_tool_surface_rejects_an_init_event_with_the_wrong_subtype(
    claude_binary, monkeypatch,
) -> None:
    line = json.dumps({
        "type": "system", "subtype": "not_init", "tools": [], "slash_commands": [],
    }).encode() + b"\n"
    _answer_with(monkeypatch, line)

    with pytest.raises(UnavailableError):
        asyncio.run(verify_cli_tool_surface())


def test_tool_surface_failure_is_cached_across_sequential_calls(
    claude_binary, monkeypatch,
) -> None:
    """Sequential calls only — see
    test_tool_surface_single_flight_serializes_concurrent_probes for the
    genuine-concurrency case a "stampede" claim actually needs (#351 round
    3, Finding 2)."""
    commands = _answer_with(monkeypatch, b"not json\n")

    with pytest.raises(UnavailableError):
        asyncio.run(verify_cli_tool_surface())
    with pytest.raises(UnavailableError):
        asyncio.run(verify_cli_tool_surface())

    assert len(commands) == 1


def test_tool_surface_failure_cache_expires_so_a_repair_takes_effect(
    claude_binary, monkeypatch,
) -> None:
    commands = _answer_with(monkeypatch, b"not json\n", _init_line(_ALL_SONGMAKER_TOOLS))
    clock = {"now": 0.0}
    monkeypatch.setattr(provider, "time", SimpleNamespace(monotonic=lambda: clock["now"]))

    with pytest.raises(UnavailableError):
        asyncio.run(verify_cli_tool_surface())

    clock["now"] += provider.CLAUDE_CLI_TOOL_SURFACE_FAILURE_CACHE_SECONDS + 1
    asyncio.run(verify_cli_tool_surface())

    assert len(commands) == 2


def test_tool_surface_treats_a_failed_mcp_connection_as_a_failure_not_a_permanent_verdict(
    claude_binary, monkeypatch,
) -> None:
    """#351 round 3, Finding 1: a failed MCP connection reports a valid
    init event with tools=[] — the same shape "all eleven genuinely
    missing" has. Confusing the two used to cache the failure forever in
    the success cache, which no repair — not even a later clean probe —
    could ever override. It must instead be a short-lived failure: a
    second call, once that TTL passes, reaches its own, real probe."""
    commands = _answer_with(
        monkeypatch,
        _init_line([], mcp_connected=False),
        _init_line(_ALL_SONGMAKER_TOOLS),
    )
    clock = {"now": 0.0}
    monkeypatch.setattr(provider, "time", SimpleNamespace(monotonic=lambda: clock["now"]))

    with pytest.raises(UnavailableError) as exc:
        asyncio.run(verify_cli_tool_surface())
    assert not isinstance(exc.value, CliToolSurfaceError)

    clock["now"] += provider.CLAUDE_CLI_TOOL_SURFACE_FAILURE_CACHE_SECONDS + 1
    binary = asyncio.run(verify_cli_tool_surface())

    assert binary == str(claude_binary)
    assert len(commands) == 2


def test_cowriter_turn_refuses_a_cli_with_an_unverified_tool_surface(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        provider, "verify_cli_tool_surface",
        AsyncMock(side_effect=CliToolSurfaceError("FutureTool")),
    )
    spawned: list[tuple[str, ...]] = []

    async def fake_exec(*cmd, **_kw):
        spawned.append(cmd)
        raise AssertionError("the co-writer must not spawn an unverified CLI")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    async def _turn() -> None:
        async for _ in acall_claude_with_mcp_stream(prompt="hi", user_id="u-1"):
            pass

    with pytest.raises(CliToolSurfaceError):
        asyncio.run(_turn())
    assert spawned == []


# ── no-builtin-tools gate (_call_cli / _acall_cli) ────────────────────


def test_no_builtin_gate_accepts_a_cli_offering_nothing(
    claude_binary, monkeypatch,
) -> None:
    commands = _answer_with(monkeypatch, _init_line([]))

    binary = asyncio.run(averify_no_builtin_cli_tools())

    assert binary == str(claude_binary)
    assert "--mcp-config" not in commands[0]
    assert "--allowedTools" not in commands[0]


def test_no_builtin_gate_rejects_a_cli_offering_any_tool(
    claude_binary, monkeypatch,
) -> None:
    _answer_with(monkeypatch, _init_line(["Bash"]))

    with pytest.raises(CliToolSurfaceError) as exc:
        asyncio.run(averify_no_builtin_cli_tools())
    assert "Bash" in str(exc.value)


def test_no_builtin_gate_rejects_a_cli_still_advertising_slash_commands(
    claude_binary, monkeypatch,
) -> None:
    _answer_with(monkeypatch, _init_line([], slash_commands=["/help"]))

    with pytest.raises(CliToolSurfaceError) as exc:
        asyncio.run(averify_no_builtin_cli_tools())
    assert "/help" in str(exc.value)


def test_no_builtin_gate_and_mcp_gate_cache_independently(
    claude_binary, monkeypatch,
) -> None:
    """Same binary build, different expectation — a co-writer turn passing
    verify_cli_tool_surface() must not let _call_cli skip its own probe,
    and vice versa; they check different command shapes."""
    commands = _answer_with(
        monkeypatch, _init_line(_ALL_SONGMAKER_TOOLS), _init_line([]),
    )

    asyncio.run(verify_cli_tool_surface())
    asyncio.run(averify_no_builtin_cli_tools())

    assert len(commands) == 2


def _fake_sync_cli(first_line: bytes, *, still_running: bool = False) -> MagicMock:
    proc = MagicMock()
    proc.pid = 4343
    proc.poll.return_value = None if still_running else 0
    proc.stdin = MagicMock()
    proc.stdout = MagicMock()
    proc.stdout.readline.return_value = first_line
    proc.wait.return_value = None
    return proc


def _answer_sync_with(monkeypatch, *lines: bytes) -> list[tuple[str, ...]]:
    commands: list[tuple[str, ...]] = []
    queued = list(lines)

    def fake_popen(cmd, **_kw):
        commands.append(tuple(cmd))
        return _fake_sync_cli(queued.pop(0))

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)
    return commands


def test_no_builtin_gate_sync_twin_accepts_a_cli_offering_nothing(
    claude_binary, monkeypatch,
) -> None:
    _answer_sync_with(monkeypatch, _init_line([]))

    binary = verify_no_builtin_cli_tools()

    assert binary == str(claude_binary)


def test_no_builtin_gate_sync_twin_rejects_a_cli_offering_any_tool(
    claude_binary, monkeypatch,
) -> None:
    _answer_sync_with(monkeypatch, _init_line(["Bash"]))

    with pytest.raises(CliToolSurfaceError) as exc:
        verify_no_builtin_cli_tools()
    assert "Bash" in str(exc.value)


def test_no_builtin_gate_sync_twin_kills_a_still_running_probe(
    claude_binary, monkeypatch,
) -> None:
    killed: list[int] = []

    def fake_popen(_cmd, **_kw):
        return _fake_sync_cli(_init_line([]), still_running=True)

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(provider.os, "killpg", lambda pid, _sig: killed.append(pid))

    verify_no_builtin_cli_tools()

    assert killed == [4343]


def test_no_builtin_gate_sync_single_flight_waits_for_the_real_result_not_a_placeholder(
    claude_binary, monkeypatch,
) -> None:
    """#351 rounds 4-5, Finding 2, sync side: the same two mutations the
    async test guards against (a placeholder-success follower; a follower
    that starts its own second probe on failure instead of accepting the
    shared one), and the same reason a bare ``calls == 1`` check on a
    *successful* probe cannot catch either. The probe fails outright
    (malformed output) specifically to exercise the second one.

    No timing assumption stands in for "the second caller reached the
    in-flight wait": a real ``threading.Event``, set from inside
    ``_claim_or_join_inflight_sync`` the moment it identifies the caller as
    a follower, is what the test waits on. The remaining timeouts are
    deadlock guards only (generous, never the expected path) — everything
    above resolves in well under 100ms.
    """
    calls = 0
    probe_started = threading.Event()
    release_probe = threading.Event()
    follower_joined = threading.Event()

    def fake_popen(_cmd, **_kw):
        nonlocal calls
        calls += 1
        probe_started.set()
        release_probe.wait()
        return _fake_sync_cli(b"not valid json\n")

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)

    real_claim = provider._claim_or_join_inflight_sync

    def _instrumented_claim(key):
        future, is_leader = real_claim(key)
        if not is_leader:
            follower_joined.set()
        return future, is_leader

    monkeypatch.setattr(provider, "_claim_or_join_inflight_sync", _instrumented_claim)

    results: list[object] = [None, None]

    def _call(index: int) -> None:
        try:
            results[index] = verify_no_builtin_cli_tools()
        except Exception as exc:  # noqa: BLE001 - captured, asserted below
            results[index] = exc

    first = threading.Thread(target=_call, args=(0,))
    second = threading.Thread(target=_call, args=(1,))
    first.start()
    assert probe_started.wait(timeout=5), "first caller never reached its probe"
    second.start()
    assert follower_joined.wait(timeout=5), "second caller never reached the in-flight wait"
    assert results[1] is None, (
        "second caller returned before the in-flight probe resolved — "
        "it must wait for the real answer, not assume success"
    )

    release_probe.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert calls == 1, "a follower must not start its own second probe on failure"
    assert all(isinstance(r, UnavailableError) for r in results)
    assert not any(isinstance(r, CliToolSurfaceError) for r in results)




def test_no_builtin_gate_sync_and_async_share_one_cache(
    claude_binary, monkeypatch,
) -> None:
    async_commands = _answer_with(monkeypatch, _init_line([]))
    sync_commands = _answer_sync_with(monkeypatch, _init_line([]))

    asyncio.run(averify_no_builtin_cli_tools())
    verify_no_builtin_cli_tools()

    assert len(async_commands) == 1
    assert len(sync_commands) == 0


# ── expected MCP tool names track the real server registration ────────


def test_expected_mcp_tool_names_matches_the_registered_mcp_server() -> None:
    """provider._EXPECTED_MCP_TOOL_NAMES is a literal tuple, not an import
    from mcp_server.server (that would pull in the ``mcp`` package, which
    the scoring-worker container does not install — see CLAUDE.md). This
    is the drift check that keeps the literal list honest against the
    server's own registration instead."""
    from songmaker_cli.mcp_server.server import build_server

    server = build_server(session_factory=lambda: None)
    registered = asyncio.run(server.list_tools())
    registered_names = {f"{provider.COWRITER_TOOL_PREFIX}{tool.name}" for tool in registered}

    assert registered_names == provider._EXPECTED_MCP_TOOL_NAMES
