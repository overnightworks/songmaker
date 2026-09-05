"""Tests for the Claude provider — API + CLI backends."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest
from conftest import fake_cli_process

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
from songmaker_cli.constants import (
    CLAUDE_CLI_COMPLETION_TIMEOUT_SECONDS,
    JUDGE_FAILURE_TIMEOUT,
    SECRET_ENV_KEYS,
)


def _reset_cli_process_pool_for_test() -> None:
    """Test isolation only; production cache invalidation keeps live slots."""
    with provider._zombie_registry_lock:
        provider._zombie_reap_reservations.clear()
        provider._zombie_reap_tasks.clear()
    with provider._tool_surface_lock:
        provider._tool_surface_probe_tasks.clear()


@pytest.fixture(autouse=True)
def _clear_claude_clients():
    clear_client_cache()
    clear_cli_login_status_cache()
    clear_cli_tool_surface_cache()
    _reset_cli_process_pool_for_test()
    yield
    clear_client_cache()
    clear_cli_login_status_cache()
    clear_cli_tool_surface_cache()
    _reset_cli_process_pool_for_test()


def _run_with_clock(coroutine, clock: dict[str, float]):
    loop = asyncio.new_event_loop()
    loop.time = lambda: clock["now"]
    try:
        return loop.run_until_complete(coroutine)
    finally:
        loop.close()


class _IncrementingMonotonicClock:
    def __init__(self, start: float, step: float) -> None:
        self.now = start
        self.step = step

    def __call__(self) -> float:
        current = self.now
        self.now += self.step
        return current


@pytest.fixture
def incrementing_monotonic_clock(monkeypatch: pytest.MonkeyPatch) -> _IncrementingMonotonicClock:
    clock = _IncrementingMonotonicClock(start=100.0, step=0.01)
    monkeypatch.setattr(provider.time, "monotonic", clock)
    return clock


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


def test_cli_login_status_delegates_to_the_shared_runner() -> None:
    runner_status = provider.CliLogin(logged_in=True, auth_method="claude.ai")
    with (
        patch(
            "songmaker_cli.claude.provider._find_claude_binary",
            return_value="/mounted/claude",
        ),
        patch(
            "songmaker_cli.claude.provider.claude_cli_login",
            return_value=runner_status,
        ) as login,
    ):
        status = cli_login_status()

    assert status is runner_status
    login.assert_called_once_with("/mounted/claude")


def test_cli_login_status_without_a_binary_delegates_the_unavailable_probe() -> None:
    logged_out = provider.CliLogin(logged_in=False, auth_method=None)
    with (
        patch("songmaker_cli.claude.provider._find_claude_binary", return_value=None),
        patch(
            "songmaker_cli.claude.provider.claude_cli_login",
            return_value=logged_out,
        ) as login,
    ):
        status = cli_login_status()

    assert status is logged_out
    login.assert_called_once_with(None)


def test_clearing_the_provider_login_cache_delegates_to_the_runner() -> None:
    with patch(
        "songmaker_cli.claude.provider.clear_claude_cli_login_cache",
    ) as clear:
        clear_cli_login_status_cache()

    clear.assert_called_once()


# ── list_cli_model_aliases ───────────────────────────────────────────


def _model_command_result(
    stdout: str,
    returncode: int = 0,
    stderr: str = "",
) -> MagicMock:
    return MagicMock(stdout=stdout, stderr=stderr, returncode=returncode)


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
        "sonnet",
        "opus",
        "haiku",
        "fable",
        "best",
        "sonnet[1m]",
        "opus[1m]",
        "fable[1m]",
        "opusplan",
        "default",
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
        with pytest.raises(UnavailableError, match="Claude CLI could not list models"):
            list_cli_model_aliases()


# ── _call_api ───────────────────────────────────────────────────────


def test_call_api_success() -> None:
    mock_client = MagicMock()
    mock_content = MagicMock()
    mock_content.text = "response text"
    mock_client.messages.create.return_value = MagicMock(content=[mock_content])

    mock_anthropic = MagicMock(APITimeoutError=Exception)
    mock_anthropic.Anthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        result = _call_api("hello", "sk-test", None, "claude-sonnet-4-20250514", 1024)

    assert result.text == "response text"


def test_call_api_with_system_prompt() -> None:
    mock_client = MagicMock()
    mock_content = MagicMock()
    mock_content.text = "ok"
    mock_client.messages.create.return_value = MagicMock(content=[mock_content])

    mock_anthropic = MagicMock(APITimeoutError=Exception)
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

    mock_anthropic = MagicMock(APITimeoutError=Exception)
    mock_anthropic.Anthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        result = _call_api("hello", "sk-test", None, "claude-sonnet-4-20250514", 1024)

    assert result.text == ""


def test_call_api_no_anthropic_package() -> None:
    with patch.dict("sys.modules", {"anthropic": None}):
        with pytest.raises(UnavailableError, match="anthropic package not installed"):
            _call_api("hello", "sk-test", None, "claude-sonnet-4-20250514", 1024)


def test_judge_api_uses_its_remaining_budget_without_retries(
    incrementing_monotonic_clock,
) -> None:
    mock_client = MagicMock()
    mock_client.with_options.return_value = mock_client
    mock_content = MagicMock(text="judge verdict")
    mock_client.messages.create.return_value = MagicMock(content=[mock_content])
    mock_anthropic = MagicMock(APITimeoutError=Exception)
    mock_anthropic.Anthropic.return_value = mock_client

    incrementing_monotonic_clock.step = 0.5
    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        result = call_claude(
            "hello",
            api_key="sk-test",
            model="claude-sonnet-4-6",
            timeout_seconds=10,
        )

    assert result.text == "judge verdict"
    assert mock_client.with_options.call_args.kwargs == {
        "timeout": 9.5,
        "max_retries": 0,
    }


def test_judge_api_timeout_uses_the_shared_timeout_reason() -> None:
    class APITimeoutError(Exception):
        pass

    mock_client = MagicMock()
    mock_client.with_options.return_value = mock_client
    mock_client.messages.create.side_effect = APITimeoutError()
    mock_anthropic = MagicMock(APITimeoutError=APITimeoutError)
    mock_anthropic.Anthropic.return_value = mock_client

    with (
        patch.dict("sys.modules", {"anthropic": mock_anthropic}),
        patch("songmaker_cli.claude.provider.time.monotonic", return_value=100.0),
    ):
        with pytest.raises(UnavailableError) as exc:
            _call_api("hello", "sk-test", None, "claude-sonnet-4-6", 1024, deadline=110.0)

    assert str(exc.value) == JUDGE_FAILURE_TIMEOUT


def test_nonjudge_api_timeout_keeps_the_provider_exception() -> None:
    class APITimeoutError(Exception):
        pass

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = APITimeoutError()
    mock_anthropic = MagicMock(APITimeoutError=APITimeoutError)
    mock_anthropic.Anthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        with pytest.raises(APITimeoutError):
            _call_api("hello", "sk-test", None, "claude-sonnet-4-6", 1024)


def test_judge_cli_gives_the_provider_request_the_remaining_budget(
    incrementing_monotonic_clock,
) -> None:
    gate = MagicMock(return_value="/usr/bin/claude")
    completed = MagicMock(returncode=0, stdout='{"result": "judge verdict"}', stderr="")

    incrementing_monotonic_clock.step = 2.5
    with (
        patch("songmaker_cli.claude.provider.verify_no_builtin_cli_tools", gate),
        patch("subprocess.run", return_value=completed) as run,
    ):
        result = call_claude(
            "hello",
            model="claude-sonnet-4-6",
            timeout_seconds=10,
        )

    assert result.text == "judge verdict"
    gate.assert_called_once_with()
    assert run.call_args.kwargs["timeout"] == 7.5


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
    monkeypatch.setattr(
        provider,
        "verify_no_builtin_cli_tools",
        lambda *, deadline=None: "/usr/bin/claude",
    )
    monkeypatch.setattr(
        provider,
        "averify_no_builtin_cli_tools",
        AsyncMock(return_value="/usr/bin/claude"),
    )


def test_call_cli_success(_no_tool_gate_open) -> None:
    json_output = json.dumps({"result": "cli response"})
    mock_proc = MagicMock(returncode=0, stdout=json_output, stderr="")

    with patch("subprocess.run", return_value=mock_proc):
        result = _call_cli("hello")

    assert result.text == "cli response"


def test_call_cli_uses_the_shared_process_pool_and_refuses_at_its_cap(
    _no_tool_gate_open,
    monkeypatch,
) -> None:
    monkeypatch.setattr(provider, "CLAUDE_CLI_MAX_CONCURRENT_PROCESSES", 1)
    run_calls = 0

    def fake_run(*_args: object, **_kwargs: object) -> MagicMock:
        nonlocal run_calls
        run_calls += 1
        with provider._zombie_registry_lock:
            assert len(provider._zombie_reap_reservations) == 1
        return MagicMock(returncode=0, stdout='{"result": "ok"}', stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        assert _call_cli("hello").text == "ok"

        live_turn = _reserve_zombie_process(42)
        with pytest.raises(UnavailableError) as exc:
            _call_cli("one too many")

    assert str(exc.value) == (
        "Claude CLI process pool is at its concurrency limit (1); refusing to start another"
    )
    assert run_calls == 1
    provider._release_zombie_reservation(live_turn)


def test_call_cli_strips_secrets_from_child_env(
    _no_tool_gate_open,
    monkeypatch: pytest.MonkeyPatch,
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
    _no_tool_gate_open,
    monkeypatch: pytest.MonkeyPatch,
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


@pytest.mark.parametrize("failure", ["missing", "nonzero"])
def test_acall_cli_surfaces_a_missing_or_failed_binary(
    _no_tool_gate_open,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    monkeypatch.setattr(provider, "averify_no_builtin_cli_tools", AsyncMock(return_value="claude"))
    if failure == "missing":
        spawn = AsyncMock(side_effect=FileNotFoundError())
    else:
        process = MagicMock(pid=1, returncode=1)
        process.communicate = AsyncMock(return_value=(b"", b"failed"))
        spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(provider, "_spawn_reserved_async_cli_process", spawn)

    with pytest.raises(UnavailableError, match="Claude CLI (binary not found|is unavailable)"):
        asyncio.run(_acall_cli("hello"))


@pytest.mark.parametrize("failure", ["missing", "nonzero"])
def test_cowriter_cli_surfaces_a_missing_or_failed_binary(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    monkeypatch.setattr(provider, "verify_cli_tool_surface", AsyncMock(return_value="claude"))
    monkeypatch.setattr(provider, "_write_mcp_config", lambda _user_id: "unused")
    monkeypatch.setattr(provider, "_unlink_quiet", lambda _path: None)
    if failure == "missing":
        spawn = AsyncMock(side_effect=FileNotFoundError())
    else:
        process = MagicMock(pid=1, returncode=1)
        process.communicate = AsyncMock(return_value=(b"", b"failed"))
        spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(provider, "_spawn_reserved_async_cli_process", spawn)

    with pytest.raises(UnavailableError, match="Claude CLI (binary not found|is unavailable)"):
        asyncio.run(provider.acall_claude_with_mcp("hello", user_id="user-1"))


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
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(
            cmd="claude",
            timeout=CLAUDE_CLI_COMPLETION_TIMEOUT_SECONDS,
        ),
    ):
        with pytest.raises(UnavailableError, match="timed out"):
            _call_cli("hello")


def test_call_cli_refuses_a_cli_the_gate_rejects(_no_tool_gate_open, monkeypatch) -> None:
    monkeypatch.setattr(
        provider,
        "verify_no_builtin_cli_tools",
        MagicMock(side_effect=CliToolSurfaceError("Bash")),
    )
    with patch("subprocess.run") as mock_run:
        with pytest.raises(CliToolSurfaceError):
            _call_cli("hello")
    mock_run.assert_not_called()


def test_acall_cli_refuses_a_cli_the_gate_rejects(_no_tool_gate_open, monkeypatch) -> None:
    monkeypatch.setattr(
        provider,
        "averify_no_builtin_cli_tools",
        AsyncMock(side_effect=CliToolSurfaceError("Bash")),
    )
    create = AsyncMock()
    with patch("asyncio.create_subprocess_exec", create):
        call = _acall_cli("hello")
        with pytest.raises(CliToolSurfaceError):
            asyncio.run(call)
    create.assert_not_called()


def test_call_cli_executes_the_binary_the_gate_verified(monkeypatch) -> None:
    """The gate resolves the CLI's symlink to its literal build path
    (#351 Finding 4); ``_call_cli`` must run that same path, not whatever
    ``_find_claude_binary`` alone would return."""
    monkeypatch.setattr(
        provider,
        "verify_no_builtin_cli_tools",
        lambda *, deadline=None: "/opt/claude/versions/2.1.257",
    )
    monkeypatch.setattr(
        provider,
        "_find_claude_binary",
        lambda: "/usr/local/bin/claude",
    )
    mock_proc = MagicMock(returncode=0, stdout='{"result": "ok"}', stderr="")

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        _call_cli("hello")

    assert mock_run.call_args[0][0][0] == "/opt/claude/versions/2.1.257"


def test_acall_cli_executes_the_binary_the_gate_verified(monkeypatch) -> None:
    monkeypatch.setattr(
        provider,
        "averify_no_builtin_cli_tools",
        AsyncMock(return_value="/opt/claude/versions/2.1.257"),
    )
    monkeypatch.setattr(
        provider,
        "_find_claude_binary",
        lambda: "/usr/local/bin/claude",
    )
    proc = MagicMock(returncode=0)
    proc.communicate = AsyncMock(return_value=(b'{"result":"ok"}', b""))
    create = AsyncMock(return_value=proc)

    with patch("asyncio.create_subprocess_exec", create):
        asyncio.run(_acall_cli("hello"))

    assert create.call_args.args[0] == "/opt/claude/versions/2.1.257"


def test_healthy_cowriter_turn_holds_its_process_pool_reservation_until_it_exits(
    monkeypatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    proc = MagicMock(pid=1234, returncode=0)

    async def communicate(_stdin: bytes) -> tuple[bytes, bytes]:
        started.set()
        await release.wait()
        return b'{"result":"ok"}', b""

    proc.communicate = AsyncMock(side_effect=communicate)
    monkeypatch.setattr(provider, "verify_cli_tool_surface", AsyncMock(return_value="claude"))
    monkeypatch.setattr(provider, "_write_mcp_config", lambda _user_id: "unused")
    monkeypatch.setattr(provider, "_unlink_quiet", lambda _path: None)
    monkeypatch.setattr(
        provider.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=proc),
    )

    async def run_turn() -> None:
        turn = asyncio.create_task(provider.acall_claude_with_mcp("hi", user_id="u-1"))
        await started.wait()
        with provider._zombie_registry_lock:
            assert len(provider._zombie_reap_reservations) == 1
        release.set()
        assert (await turn).text == "ok"
        with provider._zombie_registry_lock:
            assert not provider._zombie_reap_reservations

    asyncio.run(run_turn())


def test_cowriter_refuses_a_healthy_turn_when_the_shared_process_pool_is_full(
    monkeypatch,
) -> None:
    process_cap = 2
    monkeypatch.setattr(provider, "CLAUDE_CLI_MAX_CONCURRENT_PROCESSES", process_cap)
    monkeypatch.setattr(provider, "verify_cli_tool_surface", AsyncMock(return_value="claude"))
    monkeypatch.setattr(provider, "_write_mcp_config", lambda _user_id: "unused")
    monkeypatch.setattr(provider, "_unlink_quiet", lambda _path: None)
    release = asyncio.Event()
    started = [asyncio.Event() for _ in range(process_cap)]
    processes: list[MagicMock] = []
    spawned: list[tuple[object, ...]] = []

    for pid, turn_started in enumerate(started, start=1):
        proc = MagicMock(pid=pid, returncode=0)

        async def communicate(
            _stdin: bytes,
            turn_started: asyncio.Event = turn_started,
        ) -> tuple[bytes, bytes]:
            turn_started.set()
            await release.wait()
            return b'{"result":"ok"}', b""

        proc.communicate = AsyncMock(side_effect=communicate)
        processes.append(proc)

    async def fake_exec(*cmd: object, **_kwargs: object) -> MagicMock:
        spawned.append(cmd)
        return processes.pop(0)

    monkeypatch.setattr(provider.asyncio, "create_subprocess_exec", fake_exec)

    async def run_turns() -> None:
        running = []
        for turn_started in started:
            running.append(
                asyncio.create_task(provider.acall_claude_with_mcp("hi", user_id="u-1")),
            )
            await turn_started.wait()

        expected = (
            f"Claude CLI process pool is at its concurrency limit ({process_cap}); "
            "refusing to start another"
        )
        with pytest.raises(UnavailableError) as exc:
            await provider.acall_claude_with_mcp("hi", user_id="u-1")
        assert str(exc.value) == expected
        assert len(spawned) == process_cap
        with provider._tool_surface_lock:
            assert not provider._tool_surface_failures
            assert not provider._tool_surface_verdicts

        release.set()
        assert [turn.text for turn in await asyncio.gather(*running)] == ["ok"] * process_cap

    asyncio.run(run_turns())


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
    return (
        json.dumps(
            {
                "type": "system",
                "subtype": "init",
                "tools": tools,
                "slash_commands": slash_commands or [],
                "mcp_servers": [
                    {"name": "songmaker", "status": "connected" if mcp_connected else "failed"},
                ],
            }
        ).encode()
        + b"\n"
    )


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

    def fake_popen(cmd, **_kw):
        commands.append(tuple(cmd))
        return fake_cli_process(queued.pop(0))

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)
    return commands


_ALL_SONGMAKER_TOOLS = sorted(provider._EXPECTED_MCP_TOOL_NAMES)


def test_tool_surface_accepts_a_cli_offering_exactly_the_eleven_songmaker_tools(
    claude_binary,
    monkeypatch,
) -> None:
    _answer_with(monkeypatch, _init_line(_ALL_SONGMAKER_TOOLS))

    binary = asyncio.run(verify_cli_tool_surface())

    assert binary == str(claude_binary)


def test_tool_surface_rejects_a_cli_offering_an_unlisted_tool(
    claude_binary,
    monkeypatch,
) -> None:
    _answer_with(monkeypatch, _init_line([*_ALL_SONGMAKER_TOOLS, "Bash"]))

    probe = verify_cli_tool_surface()
    with pytest.raises(CliToolSurfaceError) as exc:
        asyncio.run(probe)
    assert "Bash" in str(exc.value)


def test_tool_surface_rejects_a_cli_offering_fewer_than_the_eleven_tools(
    claude_binary,
    monkeypatch,
) -> None:
    """A drift check that only flags additions would miss the songmaker
    server silently losing a registration too — #351 Finding 2 wants the
    reported set compared exactly, not just checked for extras."""
    _answer_with(monkeypatch, _init_line(_ALL_SONGMAKER_TOOLS[:-1]))

    probe = verify_cli_tool_surface()
    with pytest.raises(CliToolSurfaceError) as exc:
        asyncio.run(probe)
    assert "missing tools" in str(exc.value)
    assert _ALL_SONGMAKER_TOOLS[-1] in str(exc.value)


def test_tool_surface_rejects_a_cli_that_still_advertises_slash_commands(
    claude_binary,
    monkeypatch,
) -> None:
    _answer_with(
        monkeypatch,
        _init_line(_ALL_SONGMAKER_TOOLS, slash_commands=["/compact"]),
    )

    probe = verify_cli_tool_surface()
    with pytest.raises(CliToolSurfaceError) as exc:
        asyncio.run(probe)
    assert "/compact" in str(exc.value)


def test_tool_surface_is_probed_with_the_cowriter_restrictions(
    claude_binary,
    monkeypatch,
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
    claude_binary,
    monkeypatch,
) -> None:
    killed: list[int] = []

    def fake_popen(*_cmd, **_kw):
        return fake_cli_process(_init_line(_ALL_SONGMAKER_TOOLS), still_running=True)

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(provider.os, "killpg", lambda pid, _sig: killed.append(pid))
    monkeypatch.setattr(provider.agent_cli, "_process_group_exists", lambda _pid: False)

    asyncio.run(verify_cli_tool_surface())

    assert killed == [4343]


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
# The bounded exit helpers are the seam where these tests genuinely need real (tiny)
# timing. Everything built on top of it is tested by stubbing that seam.


def test_sigterm_exit_wait_reports_a_timeout() -> None:
    """#351 round 6, Finding 9: no real clock — ``proc.wait()`` reports the
    timeout itself rather than genuinely hanging, so this proves the
    branch (a TimeoutError becomes ``False``), not asyncio's own timer."""

    async def _timed_out() -> None:
        raise TimeoutError

    proc = MagicMock()
    proc.wait = AsyncMock(side_effect=_timed_out)

    completed = asyncio.run(provider._wait_for_sigterm_exit(proc))

    assert completed is False


def test_sigterm_exit_wait_reports_a_completed_process() -> None:
    proc = MagicMock()
    proc.wait = AsyncMock(return_value=0)

    completed = asyncio.run(provider._wait_for_sigterm_exit(proc))

    assert completed is True


def test_reap_process_group_tracks_a_zombie_when_the_wait_never_confirms_exit(
    monkeypatch,
    caplog,
) -> None:
    """No real waiting anywhere: the exit helpers are stubbed to always report
    'not yet', so the zombie path is exercised deterministically rather
    than resting on a real (even if tiny) wall-clock budget."""
    caplog.set_level("ERROR")
    signals: list[int] = []
    monkeypatch.setattr(provider.os, "killpg", lambda _pid, sig: signals.append(sig))
    monkeypatch.setattr(provider, "_wait_for_sigterm_exit", AsyncMock(return_value=False))
    monkeypatch.setattr(provider, "_wait_for_zombie_reap", AsyncMock(return_value=False))
    tracked: list[int] = []
    monkeypatch.setattr(
        provider,
        "_track_zombie_reap_async",
        lambda proc: tracked.append(proc.pid) or True,
    )

    proc = MagicMock()
    proc.pid = 9999
    proc.returncode = None

    became_zombie = asyncio.run(provider._reap_process_group(proc))

    assert became_zombie is True
    assert tracked == [9999]
    assert signals == [provider.signal.SIGTERM, provider.signal.SIGKILL]


def test_reap_process_group_confirms_a_normal_exit_without_signaling_a_zombie(
    monkeypatch,
) -> None:
    signals: list[int] = []
    monkeypatch.setattr(provider.os, "killpg", lambda _pid, sig: signals.append(sig))
    monkeypatch.setattr(provider, "_wait_for_sigterm_exit", AsyncMock(return_value=True))
    monkeypatch.setattr(provider, "CLAUDE_CLI_MAX_CONCURRENT_PROCESSES", 1)
    tracked: list[int] = []
    monkeypatch.setattr(provider, "_track_zombie_reap_async", lambda proc: tracked.append(proc.pid))

    proc = MagicMock()
    proc.pid = 4321
    proc.returncode = None
    _reserve_zombie_process(proc.pid)

    became_zombie = asyncio.run(provider._reap_process_group(proc))

    assert became_zombie is False
    assert tracked == []
    reservation = provider._reserve_zombie_admission()
    assert reservation is not None
    provider._release_zombie_reservation(reservation)


def _reserve_zombie_process(pid: int) -> object:
    reservation = provider._reserve_zombie_admission()
    assert reservation is not None
    provider._bind_zombie_reservation(reservation, pid)
    return reservation


def test_track_zombie_reap_logs_and_starts_a_background_reaper(monkeypatch, caplog) -> None:
    caplog.set_level("ERROR")
    monkeypatch.setattr(provider, "_reap_in_background", AsyncMock())

    async def _run() -> bool:
        proc = MagicMock()
        proc.pid = 5150
        _reserve_zombie_process(proc.pid)
        return provider._track_zombie_reap_async(proc)

    became_zombie = asyncio.run(_run())

    assert became_zombie is True
    assert any("did not exit" in r.message for r in caplog.records)


def test_track_zombie_reap_starts_the_reaper_held_by_its_reservation() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def wait() -> int:
        started.set()
        await release.wait()
        return 0

    async def _run() -> bool:
        proc = MagicMock()
        proc.pid = 5150
        proc.wait = AsyncMock(side_effect=wait)
        _reserve_zombie_process(proc.pid)
        became_zombie = provider._track_zombie_reap_async(proc)
        await started.wait()
        release.set()
        with provider._zombie_registry_lock:
            tasks = list(provider._zombie_reap_tasks)
        await asyncio.gather(*tasks)
        return became_zombie

    assert asyncio.run(_run()) is True
    reservation = provider._reserve_zombie_admission()
    assert reservation is not None
    provider._release_zombie_reservation(reservation)


def test_zombie_reap_reservations_have_a_hard_cap(monkeypatch, caplog) -> None:
    caplog.set_level("ERROR")
    monkeypatch.setattr(provider, "CLAUDE_CLI_MAX_CONCURRENT_PROCESSES", 2)

    first = _reserve_zombie_process(1)
    second = _reserve_zombie_process(2)
    assert provider._reserve_zombie_admission() is None
    assert any("at its concurrency limit (2)" in r.message for r in caplog.records)

    provider._release_zombie_reservation(1)
    provider._release_zombie_reservation(2)
    assert first is not second


def test_reap_in_background_eventually_reaps_logs_and_releases_its_reservation(caplog) -> None:
    """The zombie case is not silent: once the process this function was
    handed to actually does exit, that is logged too, and its reservation
    is freed for a later probe — this is where a stuck
    reap's process ultimately gets cleaned up."""
    caplog.set_level("INFO")
    _reserve_zombie_process(8888)
    proc = MagicMock()
    proc.pid = 8888
    proc.wait = AsyncMock(return_value=0)

    asyncio.run(provider._reap_in_background(proc))

    assert any("reaped in the background" in r.message for r in caplog.records)
    reservation = provider._reserve_zombie_admission()
    assert reservation is not None
    provider._release_zombie_reservation(reservation)


def test_shutdown_tool_surface_background_tasks_cancels_a_probe_runner_task(
    claude_binary,
    monkeypatch,
) -> None:
    probe_started = asyncio.Event()
    probe_cancelled = asyncio.Event()

    async def pending_probe(*_args, **_kwargs) -> provider._AnnouncedSurface:
        probe_started.set()
        try:
            await asyncio.Future()
        finally:
            probe_cancelled.set()

    monkeypatch.setattr(provider, "_probe_cli_surface_async", pending_probe)

    async def _run() -> None:
        waiter = asyncio.create_task(averify_no_builtin_cli_tools())
        await probe_started.wait()
        await provider.shutdown_tool_surface_background_tasks()
        await probe_cancelled.wait()
        with pytest.raises(UnavailableError):
            await waiter

    asyncio.run(asyncio.wait_for(_run(), timeout=2))


def test_tool_surface_is_probed_again_after_the_cli_updates_itself(
    claude_binary,
    monkeypatch,
) -> None:
    _answer_with(
        monkeypatch,
        _init_line(_ALL_SONGMAKER_TOOLS),
        _init_line([*_ALL_SONGMAKER_TOOLS, "FutureTool"]),
    )

    asyncio.run(verify_cli_tool_surface())
    claude_binary.write_bytes(b"cli-build-two-is-a-different-size")

    probe = verify_cli_tool_surface()
    with pytest.raises(CliToolSurfaceError) as exc:
        asyncio.run(probe)
    assert "FutureTool" in str(exc.value)


def test_tool_surface_is_probed_once_per_cli_build(
    claude_binary,
    monkeypatch,
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
    claude_binary,
    monkeypatch,
) -> None:
    """#351 round 3, Finding 2: two callers racing for the same cold key
    must share one probe. Genuine concurrency via two real asyncio tasks —
    a threading.Event (the spawn now happens on a worker thread — round 6)
    holds the first probe open until both tasks have had a chance to run,
    not a sleep. Covers the success path only — see the fail-closed test
    below for the mutations this one alone cannot catch."""
    calls = 0
    probe_started = threading.Event()
    release_probe = threading.Event()

    def fake_popen(*_cmd, **_kw):
        nonlocal calls
        calls += 1
        probe_started.set()
        release_probe.wait()
        return fake_cli_process(_init_line(_ALL_SONGMAKER_TOOLS))

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)

    async def _race() -> tuple[str, str]:
        first = asyncio.create_task(verify_cli_tool_surface())
        second = asyncio.create_task(verify_cli_tool_surface())
        await asyncio.to_thread(probe_started.wait, 5)
        release_probe.set()
        return await asyncio.gather(first, second)

    first, second = asyncio.run(asyncio.wait_for(_race(), timeout=5))

    assert calls == 1
    assert first == second == str(claude_binary)


def test_tool_surface_single_flight_waits_for_the_real_result_not_a_placeholder(
    claude_binary,
    monkeypatch,
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
    probe_started = threading.Event()
    release_probe = threading.Event()
    follower_waiting = asyncio.Event()

    def fake_popen(*_cmd, **_kw):
        nonlocal calls
        calls += 1
        probe_started.set()
        release_probe.wait()
        return fake_cli_process(b"not valid json\n")

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)

    real_await_follower = provider._await_follower_result_async

    async def _instrumented_await_follower(build, future, timeout_seconds):
        follower_waiting.set()
        return await real_await_follower(build, future, timeout_seconds)

    monkeypatch.setattr(
        provider,
        "_await_follower_result_async",
        _instrumented_await_follower,
    )

    async def _race() -> list[BaseException]:
        first = asyncio.create_task(verify_cli_tool_surface())
        second = asyncio.create_task(verify_cli_tool_surface())
        await asyncio.to_thread(probe_started.wait, 5)
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
    claude_binary,
    monkeypatch,
) -> None:
    """A process that outlives SIGKILL turns into a _ZombieProbeError, not
    a hang: single-flight must still resolve *both* concurrent callers to
    that one refusal. The probe itself is stubbed to fail instantly — no
    real timing anywhere, deliberately, since the reap bound is already
    proven at the unit level above; this is only about single-flight
    correctly propagating a zombie failure to every waiter.

    Needs the ``claude_binary`` fixture like its sibling tests: without
    it, ``_require_claude_binary()`` resolves whatever real ``claude``
    happens to be on *this* machine's ``PATH`` — present on a desktop
    with the CLI installed (green), absent on CI (``UnavailableError``
    raised before ``fake_probe`` is ever reached, so ``calls`` stays 0
    and the single-flight claim under test never actually runs). Not a
    real race — the coroutines already register/join the in-flight
    future synchronously before either ever yields — but a hidden
    dependency on real host state, same shape as depending on a real
    service.
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
            averify_no_builtin_cli_tools(),
            averify_no_builtin_cli_tools(),
            return_exceptions=True,
        )

    results = asyncio.run(asyncio.wait_for(_race(), timeout=2))

    assert calls == 1
    assert all(isinstance(r, UnavailableError) for r in results)


def test_tool_surface_reports_a_cli_that_vanished_mid_update(
    claude_binary,
    monkeypatch,
) -> None:
    claude_binary.unlink()

    probe = verify_cli_tool_surface()
    with pytest.raises(UnavailableError):
        asyncio.run(probe)


def test_tool_surface_rejects_a_cli_that_announces_nothing(
    claude_binary,
    monkeypatch,
) -> None:
    _answer_with(monkeypatch, b'{"type": "assistant"}\n')

    probe = verify_cli_tool_surface()
    with pytest.raises(UnavailableError):
        asyncio.run(probe)


def test_tool_surface_rejects_an_init_event_with_the_wrong_subtype(
    claude_binary,
    monkeypatch,
) -> None:
    line = (
        json.dumps(
            {
                "type": "system",
                "subtype": "not_init",
                "tools": [],
                "slash_commands": [],
            }
        ).encode()
        + b"\n"
    )
    _answer_with(monkeypatch, line)

    probe = verify_cli_tool_surface()
    with pytest.raises(UnavailableError):
        asyncio.run(probe)


def test_tool_surface_failure_is_cached_across_sequential_calls(
    claude_binary,
    monkeypatch,
) -> None:
    """Sequential calls only — see
    test_tool_surface_single_flight_serializes_concurrent_probes for the
    genuine-concurrency case a "stampede" claim actually needs (#351 round
    3, Finding 2)."""
    commands = _answer_with(monkeypatch, b"not json\n")

    first_probe = verify_cli_tool_surface()
    with pytest.raises(UnavailableError):
        asyncio.run(first_probe)
    second_probe = verify_cli_tool_surface()
    with pytest.raises(UnavailableError):
        asyncio.run(second_probe)

    assert len(commands) == 1


def test_tool_surface_failure_cache_expires_so_a_repair_takes_effect(
    claude_binary,
    monkeypatch,
) -> None:
    commands = _answer_with(monkeypatch, b"not json\n", _init_line(_ALL_SONGMAKER_TOOLS))
    clock = {"now": time.monotonic()}
    monkeypatch.setattr(provider, "time", SimpleNamespace(monotonic=lambda: clock["now"]))

    first_probe = verify_cli_tool_surface()
    with pytest.raises(UnavailableError):
        _run_with_clock(first_probe, clock)

    clock["now"] += provider.CLAUDE_CLI_TOOL_SURFACE_FAILURE_CACHE_SECONDS + 1
    _run_with_clock(verify_cli_tool_surface(), clock)

    assert len(commands) == 2


def test_tool_surface_treats_a_failed_mcp_connection_as_a_failure_not_a_permanent_verdict(
    claude_binary,
    monkeypatch,
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
    clock = {"now": time.monotonic()}
    monkeypatch.setattr(provider, "time", SimpleNamespace(monotonic=lambda: clock["now"]))

    failed_probe = verify_cli_tool_surface()
    with pytest.raises(UnavailableError) as exc:
        _run_with_clock(failed_probe, clock)
    assert not isinstance(exc.value, CliToolSurfaceError)

    clock["now"] += provider.CLAUDE_CLI_TOOL_SURFACE_FAILURE_CACHE_SECONDS + 1
    binary = _run_with_clock(verify_cli_tool_surface(), clock)

    assert binary == str(claude_binary)
    assert len(commands) == 2


# ── #351 round 7, Finding 4: /health follows the gate's live verdict ─


def test_claude_cli_tool_surface_health_transitions_from_unverified_to_ok(
    claude_binary,
    monkeypatch,
) -> None:
    """/health must not be a frozen boot snapshot — a later successful
    co-writer probe (e.g. the CLI was briefly unreachable at boot but is
    fine by the time someone actually opens a chat) must clear an
    earlier "unverified"."""
    commands = _answer_with(monkeypatch, b"not json\n", _init_line(_ALL_SONGMAKER_TOOLS))
    clock = {"now": time.monotonic()}
    monkeypatch.setattr(provider, "time", SimpleNamespace(monotonic=lambda: clock["now"]))

    failed_probe = verify_cli_tool_surface()
    with pytest.raises(UnavailableError):
        _run_with_clock(failed_probe, clock)
    assert provider.claude_cli_tool_surface_health() == "unverified"

    clock["now"] += provider.CLAUDE_CLI_TOOL_SURFACE_FAILURE_CACHE_SECONDS + 1
    _run_with_clock(verify_cli_tool_surface(), clock)

    assert provider.claude_cli_tool_surface_health() == "ok"
    assert len(commands) == 2


def test_claude_cli_tool_surface_health_transitions_from_ok_to_drift_after_a_build_change(
    claude_binary,
    monkeypatch,
) -> None:
    """A later drifted build (after a self-update) must replace an
    earlier "ok" — /health must not go on claiming clean forever just
    because the boot-time check once found it so."""
    commands = _answer_with(
        monkeypatch,
        _init_line(_ALL_SONGMAKER_TOOLS),
        _init_line([*_ALL_SONGMAKER_TOOLS, "FutureTool"]),
    )

    asyncio.run(verify_cli_tool_surface())
    assert provider.claude_cli_tool_surface_health() == "ok"

    claude_binary.write_bytes(b"a-different-build-entirely")
    probe = verify_cli_tool_surface()
    with pytest.raises(CliToolSurfaceError):
        asyncio.run(probe)

    assert provider.claude_cli_tool_surface_health() == "drift"
    assert len(commands) == 2


def test_claude_cli_tool_surface_health_becomes_unverified_when_a_cached_binary_disappears(
    claude_binary,
    monkeypatch,
) -> None:
    commands = _answer_with(monkeypatch, _init_line(_ALL_SONGMAKER_TOOLS))

    asyncio.run(verify_cli_tool_surface())
    assert provider.claude_cli_tool_surface_health() == "ok"
    monkeypatch.setattr(
        provider,
        "_require_claude_binary",
        lambda: (_ for _ in ()).throw(UnavailableError("Claude CLI is unavailable")),
    )

    probe = verify_cli_tool_surface()
    with pytest.raises(UnavailableError, match="unavailable"):
        asyncio.run(probe)

    assert provider.claude_cli_tool_surface_health() == "unverified"
    assert len(commands) == 1


def test_claude_cli_tool_surface_health_becomes_unverified_when_a_cached_binary_is_unreadable(
    claude_binary,
    monkeypatch,
) -> None:
    commands = _answer_with(monkeypatch, _init_line(_ALL_SONGMAKER_TOOLS))

    asyncio.run(verify_cli_tool_surface())
    assert provider.claude_cli_tool_surface_health() == "ok"
    monkeypatch.setattr(
        provider,
        "_binary_build",
        lambda _binary: (_ for _ in ()).throw(UnavailableError("Claude CLI is unreadable")),
    )

    probe = verify_cli_tool_surface()
    with pytest.raises(UnavailableError, match="unreadable"):
        asyncio.run(probe)

    assert provider.claude_cli_tool_surface_health() == "unverified"
    assert len(commands) == 1


# ── #351 round 6: unexpected tool/slash command always permanent ─────


def test_tool_surface_unexpected_tool_is_permanent_even_when_mcp_is_disconnected(
    claude_binary,
    monkeypatch,
) -> None:
    """#351 round 6, Finding 2: tools=["Bash"] plus a failed MCP connection
    used to fall through the disconnected-MCP short-failure path (the MCP
    check ran before the surface was ever evaluated) and get cached for
    only ten seconds — a nondeterministic build could then look clean once,
    get approved, and offer Bash again on the real turn. An unexpected
    tool is a permanent mismatch regardless of mcp_connected; only a
    *clean* absence explainable by the connection itself may be
    short-lived."""
    commands = _answer_with(monkeypatch, _init_line(["Bash"], mcp_connected=False))

    probe = verify_cli_tool_surface()
    with pytest.raises(CliToolSurfaceError) as exc:
        asyncio.run(probe)
    assert "Bash" in str(exc.value)

    # A second call, even immediately, must not re-probe — the mismatch is
    # cached forever, not merely for the ordinary ten-second failure TTL.
    probe = verify_cli_tool_surface()
    with pytest.raises(CliToolSurfaceError):
        asyncio.run(probe)
    assert len(commands) == 1


def test_tool_surface_slash_command_is_permanent_even_when_mcp_is_disconnected(
    claude_binary,
    monkeypatch,
) -> None:
    commands = _answer_with(
        monkeypatch,
        _init_line([], slash_commands=["/compact"], mcp_connected=False),
    )

    probe = verify_cli_tool_surface()
    with pytest.raises(CliToolSurfaceError) as exc:
        asyncio.run(probe)
    assert "/compact" in str(exc.value)

    probe = verify_cli_tool_surface()
    with pytest.raises(CliToolSurfaceError):
        asyncio.run(probe)
    assert len(commands) == 1


def test_tool_surface_permanent_mismatch_outlives_the_zombie_failure_ttl(
    claude_binary,
    monkeypatch,
) -> None:
    """A genuine verdict is not just "longer than ten seconds" — it never
    expires. Advancing the clock past even the zombie TTL (the longest one
    this module has) must not trigger a fresh probe."""
    commands = _answer_with(monkeypatch, _init_line([*_ALL_SONGMAKER_TOOLS, "Bash"]))
    clock = {"now": time.monotonic()}
    monkeypatch.setattr(provider, "time", SimpleNamespace(monotonic=lambda: clock["now"]))

    first_probe = verify_cli_tool_surface()
    with pytest.raises(CliToolSurfaceError):
        _run_with_clock(first_probe, clock)

    clock["now"] += provider.CLAUDE_CLI_ZOMBIE_FAILURE_CACHE_SECONDS + 1
    second_probe = verify_cli_tool_surface()
    with pytest.raises(CliToolSurfaceError):
        _run_with_clock(second_probe, clock)

    assert len(commands) == 1


def test_tool_surface_is_reprobed_after_a_genuine_symlink_retarget(
    tmp_path,
    monkeypatch,
) -> None:
    """#351 round 6, Finding 8: the 'CLI updates itself' test elsewhere
    overwrites the same file path — a real self-update repoints a symlink
    at a different target file instead. _binary_build resolves the
    symlink, so this must land on a different build key too."""
    target_a = tmp_path / "claude-2.1.257"
    target_a.write_bytes(b"cli-build-one")
    target_b = tmp_path / "claude-2.1.258"
    target_b.write_bytes(b"a-different-cli-build-entirely")
    symlink = tmp_path / "claude"
    symlink.symlink_to(target_a)

    with patch(
        "songmaker_cli.claude.provider._require_claude_binary",
        return_value=str(symlink),
    ):
        commands = _answer_with(
            monkeypatch,
            _init_line(_ALL_SONGMAKER_TOOLS),
            _init_line([*_ALL_SONGMAKER_TOOLS, "FutureTool"]),
        )

        asyncio.run(verify_cli_tool_surface())
        symlink.unlink()
        symlink.symlink_to(target_b)

        probe = verify_cli_tool_surface()
        with pytest.raises(CliToolSurfaceError) as exc:
            asyncio.run(probe)
        assert "FutureTool" in str(exc.value)

    assert len(commands) == 2


# ── #351 round 6, Finding 5: a zombie always wins ─────────────────────


def test_tool_surface_a_clean_read_followed_by_a_zombie_is_not_trusted(
    claude_binary,
    monkeypatch,
) -> None:
    """became_zombie used to count only when the answer phase had already
    failed — a clean init line read successfully, followed by the process
    outliving SIGKILL, produced an unbounded *clean* verdict and turn
    approval. A zombie always wins, regardless of what was read, and
    before parsing, the MCP check, or the verdict ever run."""
    _answer_with(monkeypatch, _init_line(_ALL_SONGMAKER_TOOLS))
    monkeypatch.setattr(provider.agent_cli, "_reap_process_group", lambda _proc: True)

    probe = verify_cli_tool_surface()
    with pytest.raises(provider._ZombieProbeError):
        asyncio.run(probe)

    with provider._tool_surface_lock:
        assert not provider._tool_surface_verdicts


def test_zombie_probe_keeps_its_pool_slot_until_the_runner_confirms_reap(
    claude_binary,
    monkeypatch,
) -> None:
    background_started = threading.Event()
    allow_background_reap = threading.Event()
    background_finished = threading.Event()
    monkeypatch.setattr(provider, "CLAUDE_CLI_MAX_CONCURRENT_PROCESSES", 1)
    monkeypatch.setattr(
        provider.subprocess,
        "Popen",
        lambda *_args, **_kwargs: fake_cli_process(_init_line([])),
    )
    monkeypatch.setattr(provider.agent_cli, "_reap_process_group", lambda _process: True)

    def await_background_reap(process, callback) -> None:
        background_started.set()
        assert allow_background_reap.wait(timeout=1)
        process.poll()
        provider.agent_cli._notify_reaped(callback, process.pid, became_zombie=True)
        background_finished.set()

    monkeypatch.setattr(provider.agent_cli, "_reap_in_background", await_background_reap)

    with pytest.raises(provider._ZombieProbeError):
        verify_no_builtin_cli_tools()

    assert background_started.wait(timeout=1)
    assert provider._reserve_zombie_admission() is None
    allow_background_reap.set()
    assert background_finished.wait(timeout=1)
    reservation = provider._reserve_zombie_admission()
    assert reservation is not None
    provider._release_zombie_reservation(reservation)


def test_tool_surface_a_clean_read_followed_by_a_zombie_gets_the_zombie_ttl(
    claude_binary,
    monkeypatch,
) -> None:
    commands = _answer_with(
        monkeypatch,
        _init_line(_ALL_SONGMAKER_TOOLS),
        _init_line(_ALL_SONGMAKER_TOOLS),
    )
    monkeypatch.setattr(provider.agent_cli, "_reap_process_group", lambda _proc: True)
    clock = {"now": time.monotonic()}
    monkeypatch.setattr(provider, "time", SimpleNamespace(monotonic=lambda: clock["now"]))

    probe = verify_cli_tool_surface()
    with pytest.raises(provider._ZombieProbeError):
        _run_with_clock(probe, clock)

    # The ordinary (short) failure TTL alone must not be enough to retry —
    # this second call is a cache hit, which always re-raises as a plain
    # UnavailableError (the cache carries the message and the TTL choice
    # it already made, not the original exception's exact type).
    clock["now"] += provider.CLAUDE_CLI_TOOL_SURFACE_FAILURE_CACHE_SECONDS + 1
    cached_probe = verify_cli_tool_surface()
    with pytest.raises(UnavailableError, match="outlived SIGKILL"):
        _run_with_clock(cached_probe, clock)
    assert len(commands) == 1

    # Past the zombie TTL a fresh probe runs — and this time the process
    # exits cleanly, so it should actually succeed.
    monkeypatch.setattr(provider.agent_cli, "_reap_process_group", lambda _proc: False)
    clock["now"] += provider.CLAUDE_CLI_ZOMBIE_FAILURE_CACHE_SECONDS + 1
    _run_with_clock(verify_cli_tool_surface(), clock)
    assert len(commands) == 2


def test_zombie_failure_uses_the_event_loop_clock_when_the_loop_is_offset(
    claude_binary,
    monkeypatch,
) -> None:
    commands = _answer_with(monkeypatch, _init_line(_ALL_SONGMAKER_TOOLS))
    monkeypatch.setattr(provider.agent_cli, "_reap_process_group", lambda _proc: True)
    loop = asyncio.new_event_loop()
    monotonic = time.monotonic
    monkeypatch.setattr(loop, "time", lambda: monotonic() - 43_000)
    monkeypatch.setattr(provider, "time", SimpleNamespace(monotonic=loop.time))
    monkeypatch.setattr(provider.agent_cli.time, "monotonic", loop.time)

    try:
        probe = verify_cli_tool_surface()
        with pytest.raises(provider._ZombieProbeError):
            loop.run_until_complete(probe)
    finally:
        loop.close()

    assert len(commands) == 1


# ── #351 round 6, Finding 3: cleanup and cancellation ─────────────────


def test_tool_surface_probe_normalizes_a_broken_pipe_during_write(
    claude_binary,
    monkeypatch,
) -> None:
    """#351 round 7, Finding 5: a broken pipe during the write must be
    normalized *at the write itself* — caught inline, reaped, and
    reported with its own message — not merely "some UnavailableError,
    eventually" surfacing however long the outer deadline takes to
    exhaust. The previous version of this test only checked the latter,
    which stayed green even without the inline ``except OSError`` around
    the write (confirmed live: removing it, the write's BrokenPipeError
    escapes ``_run``'s try instead of being caught inline, the thread's
    own ``finally`` still puts a result — but with the *generic* "Popen()
    did not return" payload, not the real cause, and pytest only warns
    on the escaped exception rather than failing). A generous timeout
    budget makes "prompt, not deadline-bound" and "the real cause, not
    the generic fallback" both load-bearing assertions here.
    """
    reaped: list[int] = []

    def fake_reap(proc) -> bool:
        reaped.append(proc.pid)
        return False

    def fake_popen(*_cmd, **_kw):
        proc = fake_cli_process(None)
        proc.pid = 9090
        proc.poll.return_value = 0
        proc._stdin_reader.close()
        return proc

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(provider.agent_cli, "_reap_process_group", fake_reap)
    monkeypatch.setattr(provider, "CLAUDE_CLI_TOOL_SURFACE_TIMEOUT_SECONDS", 5.0)

    started = time.monotonic()
    probe = verify_cli_tool_surface()
    with pytest.raises(UnavailableError, match="Broken pipe") as exc:
        asyncio.run(probe)
    elapsed = time.monotonic() - started

    assert not isinstance(exc.value, provider._ZombieProbeError)
    assert elapsed < 1.0, "normalized via the deadline instead of the write itself"
    assert reaped == [9090]


def test_tool_surface_probe_rejects_a_newline_free_stream_at_its_read_limit(
    claude_binary,
    monkeypatch,
) -> None:
    _build, key = provider._tool_surface_key(provider._NO_TOOLS_EXPECTED)

    def fake_popen(*_args, **_kwargs) -> MagicMock:
        proc = fake_cli_process(None)

        def write_stream() -> None:
            proc._stdout_writer.write(b"x" * (provider.CLI_OUTPUT_READ_LIMIT_BYTES + 1))
            proc._stdout_writer.close()

        threading.Thread(target=write_stream, daemon=True).start()
        return proc

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)

    with pytest.raises(UnavailableError, match="exceeded its read limit"):
        verify_no_builtin_cli_tools()

    with provider._tool_surface_lock:
        assert key in provider._tool_surface_failures
        assert key not in provider._tool_surface_verdicts


def test_probe_runner_task_cancellation_gives_waiters_a_normal_error(
    claude_binary,
    monkeypatch,
) -> None:
    """#351 round 6, Finding 3, updated for round 7's redesign: the probe
    now runs as its own independent task (``_run_probe_and_resolve_async``)
    that no single caller's own cancellation can reach — so what *can*
    still be cancelled directly is that task itself (exactly what
    ``shutdown_tool_surface_background_tasks()`` does). Its own
    CancelledError must not become a waiting caller's literal
    CancelledError — that would make an unrelated caller's own task look
    cancelled too. Every waiter gets a normal, catchable UnavailableError.
    """
    probe_started = threading.Event()

    def fake_popen(*_cmd, **_kw):
        probe_started.set()
        threading.Event().wait(999)  # never returns on its own
        return fake_cli_process(_init_line(_ALL_SONGMAKER_TOOLS))

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)

    async def _race():
        waiter = asyncio.create_task(verify_cli_tool_surface())
        await asyncio.to_thread(probe_started.wait, 5)

        with provider._tool_surface_lock:
            probe_tasks = list(provider._tool_surface_probe_tasks)
        assert len(probe_tasks) == 1
        probe_tasks[0].cancel()

        with pytest.raises(UnavailableError) as exc:
            await waiter
        return exc.value

    error = asyncio.run(asyncio.wait_for(_race(), timeout=5))

    assert not isinstance(error, asyncio.CancelledError)


def test_tool_surface_a_cancelled_leader_does_not_reopen_single_flight(
    claude_binary,
    monkeypatch,
) -> None:
    """#351 round 7, Finding 2: the probe runs as a task independent of
    whoever triggered it (``_run_probe_and_resolve_async``), not inline in
    the triggering caller's own coroutine — cancelling that caller's own
    wait must not remove the in-flight entry while the real probe is
    still running in the background. A third caller landing in exactly
    that window must still find it (or, if the probe finished by then,
    the verdict it already cached) rather than starting a second probe.
    """
    calls = 0
    probe_started = threading.Event()
    release_probe = threading.Event()

    def fake_popen(*_cmd, **_kw):
        nonlocal calls
        calls += 1
        probe_started.set()
        release_probe.wait()
        return fake_cli_process(_init_line(_ALL_SONGMAKER_TOOLS))

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)

    async def _race() -> str:
        first = asyncio.create_task(verify_cli_tool_surface())
        await asyncio.to_thread(probe_started.wait, 5)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

        # The real probe (its own independent task, on its own worker
        # thread) is still running here — first's cancellation only
        # interrupted first's own wait on the shared future.
        third = asyncio.create_task(verify_cli_tool_surface())
        release_probe.set()
        return await third

    result = asyncio.run(asyncio.wait_for(_race(), timeout=5))

    assert calls == 1
    assert result == str(claude_binary)


def test_tool_surface_inflight_future_is_resolved_even_when_evaluation_itself_raises(
    claude_binary,
    monkeypatch,
) -> None:
    """#351 round 6, Finding 7: _evaluate_tool_surface used to run outside
    the try/except that resolves the in-flight future — a bug there would
    leave the future (and the dict entry) dangling, degrading every later
    caller for that key to a follower timeout instead of a fresh probe.

    Since round 7 (Finding 2), the probe runs as its own task and every
    caller — including whichever one triggered it — reaches the shared
    future through the same follower-safe path, so what a caller actually
    sees for a bug here is the translated UnavailableError
    (_follower_safe_exception), not the raw RuntimeError; the dict cleanup
    is what this test is really about.
    """
    _answer_with(monkeypatch, _init_line(_ALL_SONGMAKER_TOOLS))
    monkeypatch.setattr(
        provider,
        "_evaluate_tool_surface",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    probe = verify_cli_tool_surface()
    with pytest.raises(UnavailableError, match="boom"):
        asyncio.run(probe)

    with provider._tool_surface_lock:
        assert not provider._tool_surface_inflight_async


# ── #351 round 6, Finding 4: the spawn step is off the event loop ────


def test_tool_surface_probe_stays_bounded_even_when_popen_itself_hangs(
    claude_binary,
    monkeypatch,
) -> None:
    """asyncio.create_subprocess_exec() still runs subprocess.Popen()
    synchronously on whichever thread calls it, including the event loop's
    own — so a spawn that hangs there could keep the loop from ever
    running the timer meant to enforce the deadline. The async gate now
    delegates to the sync twin via asyncio.to_thread specifically so a
    hung Popen() only blocks its own worker thread, never the caller."""
    popen_may_return = threading.Event()
    popen_returned = threading.Event()

    def fake_popen(*_cmd, **_kw):
        popen_may_return.wait()
        proc = fake_cli_process(_init_line([]))
        popen_returned.set()
        return proc

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(provider, "CLAUDE_CLI_NO_TOOL_SURFACE_TIMEOUT_SECONDS", 0.05)

    try:
        probe = averify_no_builtin_cli_tools()
        bounded_probe = asyncio.wait_for(probe, timeout=3)
        with pytest.raises(UnavailableError) as exc:
            asyncio.run(bounded_probe)
        assert str(exc.value) == "Claude CLI probe did not start within its budget"
    finally:
        popen_may_return.set()
        assert popen_returned.wait(timeout=1)


def test_tool_surface_probe_deadline_includes_the_default_executor_queue(
    claude_binary,
    monkeypatch,
) -> None:
    monkeypatch.setattr(provider, "_cleanup_margin_seconds", lambda: 0)

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        work_started = loop.create_future()
        release_work = threading.Event()

        def occupy_executor() -> None:
            loop.call_soon_threadsafe(work_started.set_result, None)
            release_work.wait()

        loop.set_default_executor(executor)
        occupied_work = loop.run_in_executor(None, occupy_executor)
        await work_started
        deadline = loop.time() + 0.05
        try:
            binary = str(claude_binary)
            probe = provider._probe_cli_surface_async(
                binary,
                mcp_config_path=None,
                deadline=deadline,
            )
            bounded_probe = asyncio.wait_for(probe, timeout=1)
            with pytest.raises(UnavailableError) as exc:
                await bounded_probe
            assert str(exc.value) == "Claude CLI probe cleanup did not finish within its budget"
        finally:
            release_work.set()
            await occupied_work

    asyncio.run(_run())


def test_delayed_probe_start_is_a_probe_failure_not_a_judge_timeout(
    claude_binary,
    monkeypatch,
) -> None:
    spawned: list[object] = []

    monkeypatch.setattr(provider.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(
        provider.subprocess,
        "Popen",
        lambda *_args, **_kwargs: spawned.append(1),
    )

    binary = str(claude_binary)
    with pytest.raises(UnavailableError) as exc:
        provider._probe_cli_surface_sync(binary, mcp_config_path=None, deadline=100.0)

    assert not isinstance(exc.value, provider._JudgeTimeoutExhausted)
    assert str(exc.value) == "Claude CLI probe preflight budget was already exhausted"
    assert spawned == []


def test_async_probe_waits_for_cleanup_after_its_answer_budget_is_exhausted(
    monkeypatch,
) -> None:
    worker_started = asyncio.Event()
    cleanup_may_finish = asyncio.Event()

    async def delayed_worker(*_args, **_kwargs) -> object:
        worker_started.set()
        await cleanup_may_finish.wait()
        raise provider._ZombieProbeError("probe process outlived SIGKILL")

    monkeypatch.setattr(provider.asyncio, "to_thread", delayed_worker)

    async def receive_zombie_after_cleanup() -> None:
        loop = asyncio.get_running_loop()
        probe = asyncio.create_task(
            provider._probe_cli_surface_async(
                "claude",
                mcp_config_path=None,
                deadline=loop.time(),
            ),
        )
        await asyncio.wait_for(worker_started.wait(), timeout=1)
        assert not probe.done()
        cleanup_may_finish.set()
        with pytest.raises(provider._ZombieProbeError):
            await probe

    asyncio.run(receive_zombie_after_cleanup())


@pytest.mark.parametrize("stdin_blocked", [False, True], ids=["read", "write"])
def test_probe_with_a_stalled_pipe_reaps_and_releases_its_admission(
    claude_binary,
    monkeypatch,
    incrementing_monotonic_clock,
    stdin_blocked: bool,
) -> None:
    spawned = threading.Event()
    pipe_stalled = threading.Event()
    expire_probe = threading.Event()
    reaped = threading.Event()
    processes: list[MagicMock] = []
    failures: list[BaseException] = []

    class StalledPipeSelector:
        """Drive the probe from pipe events instead of scheduler time."""

        def __init__(self) -> None:
            self._registrations: dict[object, SimpleNamespace] = {}

        def __enter__(self) -> StalledPipeSelector:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def register(self, fileobj: object, _events: int, data: str) -> None:
            self._registrations[fileobj] = SimpleNamespace(fileobj=fileobj, data=data)

        def unregister(self, fileobj: object) -> None:
            self._registrations.pop(fileobj)

        def get_map(self) -> dict[object, SimpleNamespace]:
            return self._registrations

        def select(self, timeout: float | None = None) -> list[tuple[SimpleNamespace, int]]:
            del timeout
            stdin = next(
                (item for item in self._registrations.values() if item.data == "stdin"),
                None,
            )
            if stdin is not None and not stdin_blocked:
                return [(stdin, 0)]
            pipe_stalled.set()
            expire_probe.wait()
            return []

    def fake_popen(*_cmd, **_kw) -> MagicMock:
        proc = fake_cli_process(None, stdin_blocked=stdin_blocked)
        processes.append(proc)
        spawned.set()
        return proc

    def fake_reap(_proc: object) -> bool:
        reaped.set()
        return False

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(provider.agent_cli, "_reap_process_group", fake_reap)
    monkeypatch.setattr(provider.agent_cli.selectors, "DefaultSelector", StalledPipeSelector)
    monkeypatch.setattr(provider, "CLAUDE_CLI_NO_TOOL_SURFACE_TIMEOUT_SECONDS", 5.0)
    monkeypatch.setattr(provider, "CLAUDE_CLI_MAX_CONCURRENT_PROCESSES", 1)
    incrementing_monotonic_clock.step = 0

    def probe() -> None:
        try:
            verify_no_builtin_cli_tools()
        except BaseException as error:
            failures.append(error)

    probe_thread = threading.Thread(target=probe)
    try:
        probe_thread.start()
        assert pipe_stalled.wait(timeout=1), failures
        assert spawned.is_set()
        incrementing_monotonic_clock.now += provider.CLAUDE_CLI_NO_TOOL_SURFACE_TIMEOUT_SECONDS
        expire_probe.set()
        probe_thread.join()

        assert len(failures) == 1
        assert isinstance(failures[0], UnavailableError)
        assert "did not answer" in str(failures[0])
        assert reaped.is_set()
        reservation = provider._reserve_zombie_admission()
        assert reservation is not None
        provider._release_zombie_reservation(reservation)
    finally:
        expire_probe.set()
        probe_thread.join(timeout=1)
        assert not probe_thread.is_alive()
        for proc in processes:
            proc.stdout.close()
            proc._stdin_reader.close()
            proc._stdout_writer.close()


def test_async_probe_returns_a_zombie_after_cleanup_crosses_its_answer_deadline(
    claude_binary,
    monkeypatch,
) -> None:
    process_spawned = threading.Event()
    cleanup_started = threading.Event()
    release_cleanup = threading.Event()
    processes: list[MagicMock] = []

    def fake_popen(*_cmd, **_kw) -> MagicMock:
        proc = fake_cli_process(None)
        processes.append(proc)
        process_spawned.set()
        return proc

    def fake_reap(_proc: object) -> bool:
        cleanup_started.set()
        assert release_cleanup.wait(timeout=1)
        return True

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(provider.agent_cli, "_reap_process_group", fake_reap)

    async def verify_after_cleanup() -> None:
        loop = asyncio.get_running_loop()
        probe = asyncio.create_task(
            provider._probe_cli_surface_async(
                str(claude_binary),
                mcp_config_path=None,
                deadline=loop.time() + 0.02,
            )
        )
        assert await asyncio.to_thread(process_spawned.wait, 1)
        assert await asyncio.to_thread(cleanup_started.wait, 1)
        assert not probe.done()
        release_cleanup.set()
        with pytest.raises(provider._ZombieProbeError):
            await probe

    try:
        asyncio.run(verify_after_cleanup())
    finally:
        release_cleanup.set()
        for proc in processes:
            if not proc.stdout.closed:
                proc.stdout.close()
            if not proc._stdin_reader.closed:
                proc._stdin_reader.close()
            if not proc._stdout_writer.closed:
                proc._stdout_writer.close()


def test_probe_reaps_a_process_whose_popen_call_returns_after_the_deadline(
    claude_binary,
    monkeypatch,
) -> None:
    """#351 round 7, Finding 1: reaping used to happen only in the calling
    function, after it successfully read the background thread's result
    — so a Popen() that returned *after* the caller had already given up
    was never reaped by anyone. Reaping now happens inside the thread's
    own finally, so it still runs even though nothing is listening for
    the answer by the time Popen() finally does return.
    """
    popen_may_return = threading.Event()
    reaped = threading.Event()
    reaped_pids: list[int] = []
    probe_threads: list[threading.Thread] = []
    real_thread = threading.Thread
    _build, key = provider._tool_surface_key(provider._NO_TOOLS_EXPECTED)

    def fake_popen(*_cmd, **_kw):
        popen_may_return.wait(5)
        return fake_cli_process(_init_line([]))

    def fake_reap(proc) -> bool:
        reaped_pids.append(proc.pid)
        reaped.set()
        return False

    def tracked_thread(*args, **kwargs) -> threading.Thread:
        thread = real_thread(*args, **kwargs)
        probe_threads.append(thread)
        return thread

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(provider.agent_cli, "_reap_process_group", fake_reap)
    monkeypatch.setattr(provider, "CLAUDE_CLI_NO_TOOL_SURFACE_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(provider, "CLAUDE_CLI_MAX_CONCURRENT_PROCESSES", 1)
    monkeypatch.setattr(provider.agent_cli.threading, "Thread", tracked_thread)

    started = time.monotonic()
    with pytest.raises(UnavailableError, match="did not start"):
        verify_no_builtin_cli_tools()  # gives up long before Popen() returns
    assert time.monotonic() - started < 1
    with provider._tool_surface_lock:
        assert key in provider._tool_surface_failures

    assert provider._reserve_zombie_admission() is None
    popen_may_return.set()  # only now does the "late" spawn actually complete

    assert reaped.wait(5), "the late-returning process was never reaped"
    probe_threads[0].join(timeout=1)
    assert not probe_threads[0].is_alive()
    assert reaped_pids == [4343]


def test_tool_surface_preflight_uses_its_configured_bound(
    claude_binary,
    monkeypatch,
    incrementing_monotonic_clock,
) -> None:
    observed_deadlines: list[float] = []

    def probe(*_args: object, deadline: float, **_kwargs: object) -> object:
        observed_deadlines.append(deadline)
        raise UnavailableError("probe stopped")

    monkeypatch.setattr(provider, "_probe_cli_surface_sync", probe)

    with pytest.raises(UnavailableError, match="probe stopped"):
        verify_no_builtin_cli_tools()

    assert observed_deadlines == [105.0]


def test_judge_deadline_keeps_and_caches_a_zombie_probe_failure(
    claude_binary,
    incrementing_monotonic_clock,
) -> None:
    _build, key = provider._tool_surface_key(provider._NO_TOOLS_EXPECTED)

    def zombie_probe(_deadline: float) -> provider._AnnouncedSurface:
        raise provider._ZombieProbeError("probe process outlived SIGKILL")

    with pytest.raises(provider._ZombieProbeError, match="outlived SIGKILL"):
        provider._verify_tool_surface_sync(_build, key, zombie_probe)

    with provider._tool_surface_lock:
        failure = provider._tool_surface_failures[key]
    assert failure.is_zombie is True
    assert failure.ttl_seconds() == provider.CLAUDE_CLI_ZOMBIE_FAILURE_CACHE_SECONDS


# ── #351 round 6, Finding 6: the reaper pool caps new probes too ─────


def test_tool_surface_probe_refuses_to_start_when_the_zombie_pool_is_saturated(
    claude_binary,
    monkeypatch,
) -> None:
    monkeypatch.setattr(provider, "CLAUDE_CLI_MAX_CONCURRENT_PROCESSES", 2)
    monkeypatch.setattr(provider.os, "killpg", lambda _pid, _signal: None)
    monkeypatch.setattr(provider, "_wait_for_sigterm_exit", AsyncMock(return_value=False))
    monkeypatch.setattr(provider, "_wait_for_zombie_reap", AsyncMock(return_value=False))
    monkeypatch.setattr(provider, "_write_mcp_config", lambda _user_id: "unused")
    monkeypatch.setattr(provider, "_unlink_quiet", lambda _path: None)
    spawned: list[object] = []
    monkeypatch.setattr(
        provider.subprocess,
        "Popen",
        lambda *_a, **_kw: spawned.append(1) or MagicMock(),
    )
    _build, key = provider._tool_surface_key(provider._NO_TOOLS_EXPECTED)

    async def _run() -> None:
        reapers_started = [asyncio.Event(), asyncio.Event()]
        release_reapers = asyncio.Event()
        processes: list[MagicMock] = []

        for pid, started in enumerate(reapers_started, start=1):
            proc = fake_cli_process(None, still_running=True)
            proc.pid = pid
            proc.returncode = None
            proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)

            async def wait(started: asyncio.Event = started) -> int:
                started.set()
                await release_reapers.wait()
                return 0

            proc.wait = AsyncMock(side_effect=wait)
            processes.append(proc)

        async def fake_exec(*_args: object, **_kwargs: object) -> MagicMock:
            return processes.pop(0)

        monkeypatch.setattr(provider.asyncio, "create_subprocess_exec", fake_exec)

        for _ in reapers_started:
            with pytest.raises(UnavailableError, match="timed out"):
                await provider.acall_claude_with_mcp(prompt="hi", user_id="u-1")

        await asyncio.gather(*(started.wait() for started in reapers_started))
        with pytest.raises(UnavailableError) as exc:
            verify_no_builtin_cli_tools()
        assert str(exc.value) == (
            "Claude CLI process pool is at its concurrency limit (2); refusing to start another"
        )
        assert spawned == []
        with provider._tool_surface_lock:
            assert key not in provider._tool_surface_failures
            assert key not in provider._tool_surface_verdicts
        release_reapers.set()
        with provider._zombie_registry_lock:
            tasks = list(provider._zombie_reap_tasks)
        await asyncio.gather(*tasks)

    asyncio.run(_run())


def test_zombie_reap_reservation_is_reserved_atomically_not_just_counted(monkeypatch) -> None:
    """#351 round 7, Finding 3: the old check-then-claim-later version let
    two concurrent probes both see room at cap-minus-one and both
    proceed. A real reservation closes that: the second concurrent
    attempt at the cap must be refused right at the reservation, not
    discover the gap only later when it happens to become a zombie."""
    monkeypatch.setattr(provider, "CLAUDE_CLI_MAX_CONCURRENT_PROCESSES", 1)

    reservation = provider._reserve_zombie_admission()
    assert reservation is not None
    provider._bind_zombie_reservation(reservation, 1)
    assert provider._reserve_zombie_admission() is None
    provider._release_zombie_reservation(1)
    next_reservation = provider._reserve_zombie_admission()
    assert next_reservation is not None
    provider._release_zombie_reservation(next_reservation)


def test_clearing_the_tool_surface_cache_keeps_live_processes_in_the_pool(
    monkeypatch,
) -> None:
    monkeypatch.setattr(provider, "CLAUDE_CLI_MAX_CONCURRENT_PROCESSES", 1)
    reservation = provider._reserve_zombie_admission()
    assert reservation is not None
    provider._bind_zombie_reservation(reservation, 42)

    clear_cli_tool_surface_cache()

    with provider._zombie_registry_lock:
        assert provider._zombie_reap_reservations == {reservation}
    assert provider._reserve_zombie_admission() is None
    provider._release_zombie_reservation(42)
    with provider._zombie_registry_lock:
        assert not provider._zombie_reap_reservations


def test_releasing_a_process_reservation_without_a_pid_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="without a PID"):
        provider._release_zombie_reservation(None)


def test_zombie_reap_reservation_has_no_toctou_window_under_real_concurrency(
    monkeypatch,
) -> None:
    """The same property, proven with two genuinely concurrent threads
    racing the same 1-slot pool rather than two sequential calls."""
    monkeypatch.setattr(provider, "CLAUDE_CLI_MAX_CONCURRENT_PROCESSES", 1)
    both_may_proceed = threading.Barrier(2)
    results: list[object | None] = []
    results_lock = threading.Lock()

    def _attempt() -> None:
        both_may_proceed.wait(timeout=5)
        reserved = provider._reserve_zombie_admission()
        with results_lock:
            results.append(reserved)

    threads = [threading.Thread(target=_attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    try:
        assert sum(reservation is not None for reservation in results) == 1
    finally:
        for reservation in results:
            if reservation is not None:
                provider._release_zombie_reservation(reservation)


def test_probe_runner_start_failure_releases_its_unbound_reservation(monkeypatch) -> None:
    monkeypatch.setattr(provider, "CLAUDE_CLI_MAX_CONCURRENT_PROCESSES", 1)

    def fail_start(_runner: threading.Thread) -> None:
        raise RuntimeError("thread start failed")

    monkeypatch.setattr(provider.agent_cli.threading.Thread, "start", fail_start)

    deadline = time.monotonic() + 1
    with pytest.raises(RuntimeError, match="thread start failed"):
        provider._probe_cli_surface_sync("claude", mcp_config_path=None, deadline=deadline)

    reservation = provider._reserve_zombie_admission()
    assert reservation is not None
    provider._release_zombie_reservation(reservation)


# ── #351 round 6, Finding 8: the non-streaming MCP entry point ───────


def test_cowriter_non_stream_turn_refuses_a_cli_with_an_unverified_tool_surface(
    monkeypatch,
) -> None:
    """The streaming entry point already had this proof; the
    non-streaming acall_claude_with_mcp needs its own — the global
    autouse mock of verify_cli_tool_surface would otherwise hide a
    regression that dropped this call from this specific entry point."""
    monkeypatch.setattr(
        provider,
        "verify_cli_tool_surface",
        AsyncMock(side_effect=CliToolSurfaceError("FutureTool")),
    )
    spawned: list[tuple[str, ...]] = []

    async def fake_exec(*cmd, **_kw):
        spawned.append(cmd)
        raise AssertionError("the co-writer must not spawn an unverified CLI")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    turn = provider.acall_claude_with_mcp(prompt="hi", user_id="u-1")
    with pytest.raises(CliToolSurfaceError):
        asyncio.run(turn)
    assert spawned == []


def test_cowriter_turn_refuses_a_cli_with_an_unverified_tool_surface(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        provider,
        "verify_cli_tool_surface",
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

    turn = _turn()
    with pytest.raises(CliToolSurfaceError):
        asyncio.run(turn)
    assert spawned == []


class _StreamReader:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        return self._lines.pop(0) if self._lines else b""

    async def read(self, size: int = -1) -> bytes:
        if not self._lines:
            return b""
        payload = b"".join(self._lines)
        if size >= 0:
            self._lines = [payload[size:]] if len(payload) > size else []
            return payload[:size]
        self._lines = []
        return payload


def _streaming_cli_process(lines: list[bytes], *, returncode: int = 0) -> MagicMock:
    process = MagicMock()
    process.pid = 2468
    process.returncode = returncode
    process.stdout = _StreamReader(lines)
    process.stderr = _StreamReader([])
    process.stdin = MagicMock()

    async def drain() -> None:
        return None

    async def wait() -> None:
        return None

    process.stdin.drain = drain
    process.wait = wait
    return process


async def _collect_stream_events(stream) -> list[object]:
    return [event async for event in stream]


def test_public_claude_stream_skips_malformed_cli_output(monkeypatch, caplog) -> None:
    process = _streaming_cli_process(
        [
            b"not-json\n",
            b'{"type":"assistant","message":{"content":[{"type":"text","text":"draft"}]}}\n',
            b'{"type":"result","result":"final"}\n',
        ]
    )

    async def spawn(*_command, **_kwargs):
        return process

    monkeypatch.setattr(provider, "verify_cli_tool_surface", AsyncMock(return_value="claude"))
    monkeypatch.setattr(provider, "_spawn_reserved_async_cli_process", spawn)
    monkeypatch.setattr(provider, "_write_mcp_config", lambda _user_id: "unused")
    monkeypatch.setattr(provider, "_unlink_quiet", lambda _path: None)
    caplog.set_level("WARNING", logger="songmaker_cli.claude.provider")

    events = asyncio.run(
        _collect_stream_events(
            acall_claude_with_mcp_stream(prompt="hi", user_id="u-1"),
        )
    )

    assert events == [
        provider.AssistantTextEvent(text="draft"),
        provider.FinalEvent(text="final"),
    ]
    assert "malformed JSON" in caplog.text


def test_public_claude_stream_names_a_nonzero_cli_exit(monkeypatch) -> None:
    process = _streaming_cli_process([], returncode=2)

    async def spawn(*_command, **_kwargs):
        return process

    monkeypatch.setattr(provider, "verify_cli_tool_surface", AsyncMock(return_value="claude"))
    monkeypatch.setattr(provider, "_spawn_reserved_async_cli_process", spawn)
    monkeypatch.setattr(provider, "_write_mcp_config", lambda _user_id: "unused")
    monkeypatch.setattr(provider, "_unlink_quiet", lambda _path: None)

    stream = acall_claude_with_mcp_stream(prompt="hi", user_id="u-1")
    events = _collect_stream_events(stream)
    with pytest.raises(UnavailableError, match="unavailable"):
        asyncio.run(events)


def test_public_claude_stream_names_a_missing_binary(monkeypatch) -> None:
    async def spawn(*_command, **_kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(provider, "verify_cli_tool_surface", AsyncMock(return_value="claude"))
    monkeypatch.setattr(provider, "_spawn_reserved_async_cli_process", spawn)
    monkeypatch.setattr(provider, "_write_mcp_config", lambda _user_id: "unused")
    monkeypatch.setattr(provider, "_unlink_quiet", lambda _path: None)

    stream = acall_claude_with_mcp_stream(prompt="hi", user_id="u-1")
    events = _collect_stream_events(stream)
    with pytest.raises(provider.CliBinaryUnavailableError, match="not found"):
        asyncio.run(events)


def test_stream_reap_completes_before_a_cancelled_closer_returns(monkeypatch) -> None:
    """A disconnect may cancel an ASGI 2.3 stream while it is closing.

    The reaper itself has awaits for SIGTERM/SIGKILL grace and process wait,
    so cancelling the closer must not cancel that work halfway through.
    """
    monkeypatch.setattr(provider, "verify_cli_tool_surface", AsyncMock(return_value="claude"))
    monkeypatch.setattr(provider, "_write_mcp_config", lambda _user_id: "unused")
    monkeypatch.setattr(provider, "_unlink_quiet", lambda _path: None)

    async def _run() -> None:
        proc = MagicMock()
        proc.stdin = None
        reaper_started = asyncio.Event()
        finish_reaper = asyncio.Event()
        reaper_finished = asyncio.Event()

        async def fake_spawn(*_args, **_kwargs):
            return proc

        async def fake_consume(*_args, **_kwargs):
            yield provider.AssistantTextEvent(text="partial")
            await asyncio.Future()

        async def fake_reap(_proc) -> bool:
            reaper_started.set()
            await finish_reaper.wait()
            reaper_finished.set()
            return False

        monkeypatch.setattr(provider, "_spawn_reserved_async_cli_process", fake_spawn)
        monkeypatch.setattr(provider, "_consume_stream", fake_consume)
        monkeypatch.setattr(provider, "_reap_process_group", fake_reap)

        stream = provider.acall_claude_with_mcp_stream(prompt="hi", user_id="u-1")
        assert (await anext(stream)).text == "partial"

        closer = asyncio.create_task(stream.aclose())
        await reaper_started.wait()
        closer.cancel()
        await asyncio.sleep(0)
        assert not closer.done()

        finish_reaper.set()
        with pytest.raises(asyncio.CancelledError):
            await closer
        assert reaper_finished.is_set()

    asyncio.run(_run())


def test_stream_reap_does_not_spin_under_anyio_level_cancellation(monkeypatch) -> None:
    """An ASGI cancellation scope must let the delayed reap make progress.

    The old asyncio.shield retry loop was immediately cancelled again by
    AnyIO's level cancellation, repeatedly attempting the shielded await
    while the reaper could not finish.  A cancellation shield waits once for
    the child reaper, then propagates cancellation after it has completed.
    """
    shield_calls = 0
    original_shield = asyncio.shield

    def count_shield(awaitable):
        nonlocal shield_calls
        shield_calls += 1
        return original_shield(awaitable)

    monkeypatch.setattr(asyncio, "shield", count_shield)

    async def _run() -> None:
        reaper_started = anyio.Event()
        finish_reaper = anyio.Event()
        reaper_finished = anyio.Event()
        close_finished = anyio.Event()
        reap_calls = 0

        async def fake_reap(_proc) -> bool:
            nonlocal reap_calls
            reap_calls += 1
            reaper_started.set()
            await finish_reaper.wait()
            reaper_finished.set()
            return False

        monkeypatch.setattr(provider, "_reap_process_group", fake_reap)

        async def close_after_cancellation() -> None:
            process = MagicMock()
            with pytest.raises(asyncio.CancelledError):
                await provider._reap_stream_process_after_cancellation(process)
            close_finished.set()

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(close_after_cancellation)
            await reaper_started.wait()
            task_group.cancel_scope.cancel()
            with anyio.CancelScope(shield=True):
                finish_reaper.set()
                await reaper_finished.wait()
                await close_finished.wait()

        assert reap_calls == 1
        assert shield_calls <= 2

    anyio.run(_run)


@pytest.mark.parametrize(
    ("failure", "expected_error", "message"),
    [
        (asyncio.TimeoutError(), UnavailableError, "timed out"),
        (RuntimeError("stream read failed"), RuntimeError, "stream read failed"),
    ],
    ids=["timeout", "error"],
)
def test_stream_failure_starts_one_background_reaper(
    monkeypatch,
    failure: BaseException,
    expected_error: type[BaseException],
    message: str,
) -> None:
    monkeypatch.setattr(provider, "CLAUDE_CLI_MAX_CONCURRENT_PROCESSES", 1)
    monkeypatch.setattr(provider.os, "killpg", lambda _pid, _signal: None)
    monkeypatch.setattr(provider, "_wait_for_sigterm_exit", AsyncMock(return_value=False))
    monkeypatch.setattr(provider, "_wait_for_zombie_reap", AsyncMock(return_value=False))
    monkeypatch.setattr(provider, "_write_mcp_config", lambda _user_id: "unused")
    monkeypatch.setattr(provider, "_unlink_quiet", lambda _path: None)

    async def _run() -> None:
        reaper_started = asyncio.Event()
        release_reaper = asyncio.Event()
        proc = MagicMock()
        proc.pid = 5150
        proc.returncode = None
        proc.stdin = None
        proc.stderr = None

        async def wait() -> int:
            reaper_started.set()
            await release_reaper.wait()
            return 0

        async def failing_lines(*_args: object):
            if failure is not None:
                raise failure
            yield b""

        proc.wait = AsyncMock(side_effect=wait)
        monkeypatch.setattr(
            provider.asyncio,
            "create_subprocess_exec",
            AsyncMock(return_value=proc),
        )
        monkeypatch.setattr(provider, "_iter_lines", failing_lines)

        async def stream() -> None:
            async for _ in provider.acall_claude_with_mcp_stream(prompt="hi", user_id="u-1"):
                pass

        with pytest.raises(expected_error, match=message):
            await stream()
        await reaper_started.wait()
        with provider._zombie_registry_lock:
            tasks = list(provider._zombie_reap_tasks)
        assert len(tasks) == 1
        proc.wait.assert_awaited_once_with()
        assert provider._reserve_zombie_admission() is None

        release_reaper.set()
        await asyncio.gather(*tasks)

    asyncio.run(_run())


# ── no-builtin-tools gate (_call_cli / _acall_cli) ────────────────────


def test_no_builtin_gate_accepts_a_cli_offering_nothing(
    claude_binary,
    monkeypatch,
) -> None:
    commands = _answer_with(monkeypatch, _init_line([]))

    binary = asyncio.run(averify_no_builtin_cli_tools())

    assert binary == str(claude_binary)
    assert "--mcp-config" not in commands[0]
    assert "--allowedTools" not in commands[0]


def test_no_builtin_gate_rejects_a_cli_offering_any_tool(
    claude_binary,
    monkeypatch,
) -> None:
    _answer_with(monkeypatch, _init_line(["Bash"]))

    probe = averify_no_builtin_cli_tools()
    with pytest.raises(CliToolSurfaceError) as exc:
        asyncio.run(probe)
    assert "Bash" in str(exc.value)


def test_no_builtin_gate_rejects_a_cli_still_advertising_slash_commands(
    claude_binary,
    monkeypatch,
) -> None:
    _answer_with(monkeypatch, _init_line([], slash_commands=["/help"]))

    probe = averify_no_builtin_cli_tools()
    with pytest.raises(CliToolSurfaceError) as exc:
        asyncio.run(probe)
    assert "/help" in str(exc.value)


def test_no_builtin_gate_and_mcp_gate_cache_independently(
    claude_binary,
    monkeypatch,
) -> None:
    """Same binary build, different expectation — a co-writer turn passing
    verify_cli_tool_surface() must not let _call_cli skip its own probe,
    and vice versa; they check different command shapes."""
    commands = _answer_with(
        monkeypatch,
        _init_line(_ALL_SONGMAKER_TOOLS),
        _init_line([]),
    )

    asyncio.run(verify_cli_tool_surface())
    asyncio.run(averify_no_builtin_cli_tools())

    assert len(commands) == 2


def test_no_builtin_gate_sync_twin_accepts_a_cli_offering_nothing(
    claude_binary,
    monkeypatch,
) -> None:
    _answer_with(monkeypatch, _init_line([]))

    binary = verify_no_builtin_cli_tools()

    assert binary == str(claude_binary)


def test_no_builtin_gate_sync_twin_rejects_a_cli_offering_any_tool(
    claude_binary,
    monkeypatch,
) -> None:
    _answer_with(monkeypatch, _init_line(["Bash"]))

    with pytest.raises(CliToolSurfaceError) as exc:
        verify_no_builtin_cli_tools()
    assert "Bash" in str(exc.value)


def test_no_builtin_gate_sync_twin_kills_a_still_running_probe(
    claude_binary,
    monkeypatch,
) -> None:
    killed: list[int] = []

    def fake_popen(_cmd, **_kw):
        return fake_cli_process(_init_line([]), still_running=True)

    monkeypatch.setattr(provider.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(provider.os, "killpg", lambda pid, _sig: killed.append(pid))
    monkeypatch.setattr(provider.agent_cli, "_process_group_exists", lambda _pid: False)

    verify_no_builtin_cli_tools()

    assert killed == [4343]


def test_no_builtin_gate_sync_single_flight_waits_for_the_real_result_not_a_placeholder(
    claude_binary,
    monkeypatch,
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
        return fake_cli_process(b"not valid json\n")

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
    claude_binary,
    monkeypatch,
) -> None:
    """Async and sync gates key their cache on the same (binary build,
    expectation) pair; since round 6 they even spawn through the same
    subprocess.Popen mechanism (the async gate delegates to the sync one
    via asyncio.to_thread), so one probe now answers both outright."""
    commands = _answer_with(monkeypatch, _init_line([]))

    asyncio.run(averify_no_builtin_cli_tools())
    verify_no_builtin_cli_tools()

    assert len(commands) == 1


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

    assert len(registered_names) == 12
    assert registered_names == provider._EXPECTED_MCP_TOOL_NAMES
