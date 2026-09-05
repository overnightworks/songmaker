"""Codex subscription CLI co-writer transport."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

import pytest

from songmaker_cli.agent_cli import CliRunOutcome, CliRunReason
from songmaker_cli.claude.provider import AssistantTextEvent, FinalEvent, ToolCallEvent
from songmaker_cli.cowriter import codex_cli_adapter
from songmaker_cli.cowriter.codex_process_pool import CodexProcessKind, CodexProcessPool
from songmaker_cli.cowriter.errors import (
    CodexProcessPoolSaturatedError,
    ProviderUnavailableError,
    SafeRouteReasonCode,
)
from songmaker_cli.cowriter.tool_loop import (
    InitialTurn,
    ToolCallBatch,
    ToolResult,
    ToolResultBatch,
    stream_tool_loop,
)

_REDACTED_CODEX_LOGIN = {
    "auth_mode": "chatgpt",
    "OPENAI_API_KEY": None,
    "last_refresh": "2026-09-04T19:20:00Z",
    "tokens": {
        "id_token": "id-token",
        "access_token": "access-token",
        "account_id": "account",
        "refresh_token": "",
    },
}
_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("missing", ("cli", "code_mode_host", "resources"))
def test_cover_image_capability_requires_every_codex_mount(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing: str,
) -> None:
    cli = tmp_path / "codex"
    code_mode_host = tmp_path / "codex-code-mode-host"
    resources = tmp_path / "codex-resources"
    for binary in (cli, code_mode_host):
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)
    resources.mkdir()
    monkeypatch.setattr(codex_cli_adapter, "CODEX_CLI_BINARY", str(cli))
    monkeypatch.setattr(codex_cli_adapter, "CODEX_CODE_MODE_HOST_BINARY", str(code_mode_host))
    monkeypatch.setattr(codex_cli_adapter, "CODEX_RESOURCES_DIRECTORY", str(resources))

    assert codex_cli_adapter.codex_cover_image_capability_is_available()

    if missing == "cli":
        cli.unlink()
    elif missing == "code_mode_host":
        code_mode_host.unlink()
    else:
        resources.rmdir()

    assert not codex_cli_adapter.codex_cover_image_capability_is_available()


@pytest.fixture(autouse=True)
def codex_login_mirror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    mirror = tmp_path / "auth.json"
    mirror.write_text(json.dumps(_REDACTED_CODEX_LOGIN))
    monkeypatch.setattr(codex_cli_adapter, "CODEX_CLI_AUTH_FILE", str(mirror))
    process_pool = CodexProcessPool(maximum_processes=8, maximum_cover_runs=1)
    monkeypatch.setattr(
        codex_cli_adapter,
        "get_codex_process_pool",
        lambda: process_pool,
    )
    return mirror


def _outcome(
    *, returncode: int = 0, complete: bool = True, stderr: str = "",
    reason: CliRunReason = CliRunReason.COMPLETE,
) -> CliRunOutcome:
    return CliRunOutcome(
        started=True,
        spawn_error=None,
        returncode=returncode,
        stdout="",
        stderr=stderr,
        complete=complete,
        became_zombie=False,
        reason=reason,
    )


def _runner(lines: list[bytes], outcome: CliRunOutcome, calls: list) -> object:
    def run_cli_bounded(command, **kwargs):
        calls.append((command, kwargs))
        for line in lines:
            if not kwargs["stdout_line_channel"]._send(line):
                break
        kwargs["stdout_line_channel"]._close(outcome)
        kwargs["on_spawned"](1)
        kwargs["on_reaped"](1, False)
        return outcome

    return run_cli_bounded


def _fixture_lines(name: str) -> list[bytes]:
    return [line.encode() + b"\n" for line in (_FIXTURES / name).read_text().splitlines()]


def _codex_tool_events(transport, executor):
    return stream_tool_loop(
        provider="codex",
        route="cli",
        system="system",
        messages=[{"role": "user", "content": "hello"}],
        transport=transport,
        executor=executor,
    )


async def _collect_tool_events(stream) -> list[object]:
    return [event async for event in stream]


def test_codex_tool_command_pins_read_only_isolation_for_start_and_resume() -> None:
    model = "codex-test"
    thread_id = "52700000-0000-4000-8000-000000000000"
    common = (
        "--json",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "-c", "approval_policy=\"never\"",
        "-c", "mcp_servers={}",
        "-c", "features.shell_tool=false",
        "-c", "features.unified_exec=false",
        "-c", "features.browser_use=false",
        "-c", "features.computer_use=false",
        "-c", "features.multi_agent=false",
        "-c", "features.image_generation=false",
        "-c", "features.plugins=false",
        "-c", "features.hooks=false",
        "-c", 'web_search="disabled"',
        "-c", "features.code_mode_host=false",
        "-c", "features.code_mode=false",
        "-c", "features.code_mode_only=false",
        "-c", 'sandbox_mode="read-only"',
        "--model", model,
    )

    assert codex_cli_adapter._build_codex_tool_command(model) == (
        "codex", "exec", "--sandbox", "read-only", *common, "-",
    )
    assert codex_cli_adapter._build_codex_tool_command(
        model,
        thread_id=thread_id,
    ) == ("codex", "exec", "resume", *common, thread_id, "-")


@pytest.mark.acceptance("ACC-COWRITER-12")
def test_codex_tool_transport_uses_an_empty_private_work_directory_on_resume(monkeypatch) -> None:
    calls: list = []
    prompts: list[bytes] = []
    scrubbed_calls = 0
    thread_id = "52700000-0000-4000-8000-000000000000"
    rounds = iter([
        [
            json.dumps({"type": "thread.started", "thread_id": thread_id}).encode() + b"\n",
            b'{"type":"item.completed","item":{"type":"agent_message","text":"<songmaker_tool_call>\\n{\\"name\\":\\"list_songs\\",\\"arguments\\":{}}\\n</songmaker_tool_call>"}}\n',
            b'{"type":"turn.completed","usage":{}}\n',
        ],
        [
            json.dumps({"type": "thread.started", "thread_id": thread_id}).encode() + b"\n",
            b'{"type":"item.completed","item":{"type":"agent_message","text":"done"}}\n',
            b'{"type":"turn.completed","usage":{}}\n',
        ],
    ])

    def run_cli_bounded(command, **kwargs):
        calls.append((command, kwargs))
        work_directory = Path(kwargs["cwd"])
        codex_home = Path(kwargs["extra_env"]["CODEX_HOME"])
        assert work_directory.name == "work"
        assert work_directory.parent == codex_home.parent
        assert work_directory != codex_home
        assert work_directory.stat().st_mode & 0o777 == 0o700
        assert list(work_directory.iterdir()) == []
        prompts.append(kwargs["stdin_payload"])
        for line in next(rounds):
            assert kwargs["stdout_line_channel"]._send(line)
        outcome = _outcome()
        kwargs["stdout_line_channel"]._close(outcome)
        kwargs["on_spawned"](len(calls))
        kwargs["on_reaped"](len(calls), False)
        return outcome

    def scrubbed_environment() -> dict[str, str]:
        nonlocal scrubbed_calls
        scrubbed_calls += 1
        return {"PATH": "/test/bin"}

    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", run_cli_bounded)
    monkeypatch.setattr(codex_cli_adapter, "scrubbed_env", scrubbed_environment)
    transport = codex_cli_adapter.CodexCliToolTransport(model="codex-test")
    events = asyncio.run(_collect_tool_events(_codex_tool_events(
        transport,
        lambda _name, _arguments: ('{"songs":[]}', False),
    )))

    assert isinstance(events[0], ToolCallEvent)
    assert events[-1] == FinalEvent(text="done")
    first_command, first_kwargs = calls[0]
    second_command, second_kwargs = calls[1]
    assert first_command[:5] == ("codex", "exec", "--sandbox", "read-only", "--json")
    assert second_command[:3] == ("codex", "exec", "resume")
    assert second_command[-2:] == (thread_id, "-")
    for command, kwargs in calls:
        assert "--ephemeral" not in command
        assert kwargs["stdin_payload"] in prompts
        assert kwargs["output_read_limit_bytes"] == (
            codex_cli_adapter.CODEX_CLI_TURN_OUTPUT_READ_LIMIT_BYTES
        )
        assert kwargs["deadline"] == first_kwargs["deadline"]
        assert kwargs["extra_env"]["CODEX_HOME"].endswith("/codex-home")
        assert kwargs["extra_env"]["PATH"] == "/test/bin"
        for config in (*codex_cli_adapter._CODEX_TOOL_ISOLATION_CONFIGS,
                       'sandbox_mode="read-only"'):
            assert config in command
    assert prompts == [
        b"system\n\nUser: hello",
        b'<songmaker_tool_result>\n{"songs":[]}\n</songmaker_tool_result>',
    ]
    assert not Path(first_kwargs["cwd"]).exists()
    assert first_kwargs["extra_env"] == second_kwargs["extra_env"]
    assert scrubbed_calls == 2


@pytest.mark.parametrize(
    "thread_id",
    ("fixture-codex-thread-527", "--dangerously-bypass-approvals-and-sandbox"),
)
def test_codex_tool_transport_rejects_non_uuid_thread_ids(thread_id: str) -> None:
    with pytest.raises(codex_cli_adapter._CodexCliStreamFailure):
        codex_cli_adapter._thread_started_id({"thread_id": thread_id})


def test_codex_tool_transport_rejects_a_multi_result_batch_without_a_resume(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", _runner([
        b'{"type":"thread.started","thread_id":"52700000-0000-4000-8000-000000000000"}\n',
        b'{"type":"item.completed","item":{"type":"agent_message","text":"done"}}\n',
        b'{"type":"turn.completed","usage":{}}\n',
    ], _outcome(), calls))
    transport = codex_cli_adapter.CodexCliToolTransport(model="codex-test")

    async def reject_batch() -> None:
        assert [item async for item in transport.stream(InitialTurn("system", []))]
        with pytest.raises(ProviderUnavailableError) as raised:
            async for _ in transport.stream(ToolResultBatch((
                ToolResult("one", "1", False),
                ToolResult("two", "2", False),
            ))):
                pass
        assert raised.value.reason.code is SafeRouteReasonCode.TOOL_PROTOCOL_ERROR
        await transport.aclose()

    asyncio.run(reject_batch())
    assert len(calls) == 1


@pytest.mark.parametrize("fixture_name", (
    "codex-tool-code-mode-host-disabled.jsonl",
    "codex-tool-code-mode-host-disabled-without-remediation.jsonl",
))
def test_codex_tool_transport_ignores_its_code_mode_host_isolation_notice(
    monkeypatch, caplog,
    fixture_name: str,
) -> None:
    calls: list = []
    monkeypatch.setattr(
        codex_cli_adapter,
        "run_cli_bounded",
        _runner(
            _fixture_lines(fixture_name),
            _outcome(),
            calls,
        ),
    )
    caplog.set_level("INFO", logger="songmaker_cli.cowriter.codex_cli_adapter")
    transport = codex_cli_adapter.CodexCliToolTransport(model="codex-test")

    events = asyncio.run(_collect_tool_events(_codex_tool_events(
        transport,
        lambda _name, _arguments: ("unreachable", False),
    )))

    assert events == [
        AssistantTextEvent(text="The open song is Midnight Drive."),
        FinalEvent(text="The open song is Midnight Drive."),
    ]
    assert len(calls) == 1
    assert "ignored its code-mode-host isolation notice" in caplog.text


def test_codex_tool_transport_aborts_for_an_unrelated_completed_error_item(monkeypatch) -> None:
    aborted = threading.Event()

    def run_cli_bounded(_command, **kwargs):
        channel = kwargs["stdout_line_channel"]
        for line in _fixture_lines("codex-tool-unrelated-error.jsonl"):
            assert channel._send(line)
        while not channel.abort_requested():
            time.sleep(0.001)
        aborted.set()
        outcome = _outcome(complete=False)
        channel._close(outcome)
        kwargs["on_spawned"](1)
        kwargs["on_reaped"](1, False)
        return outcome

    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", run_cli_bounded)
    transport = codex_cli_adapter.CodexCliToolTransport(model="codex-test")

    async def collect() -> None:
        with pytest.raises(ProviderUnavailableError) as raised:
            async for _ in transport.stream(InitialTurn("system", [])):
                pass
        assert raised.value.reason.code is SafeRouteReasonCode.CLI_PROTOCOL_ERROR

    asyncio.run(collect())
    assert aborted.is_set()


@pytest.mark.parametrize("item_type", sorted(codex_cli_adapter._BLOCKED_ITEM_TYPES))
def test_codex_tool_transport_aborts_native_tools_before_the_loop_executes(
    monkeypatch,
    item_type,
) -> None:
    aborted = threading.Event()

    def run_cli_bounded(_command, **kwargs):
        channel = kwargs["stdout_line_channel"]
        assert channel._send(json.dumps({
            "type": "item.started", "item": {"type": item_type},
        }).encode() + b"\n")
        while not channel.abort_requested():
            time.sleep(0.001)
        aborted.set()
        outcome = _outcome(complete=False)
        channel._close(outcome)
        kwargs["on_spawned"](1)
        kwargs["on_reaped"](1, False)
        return outcome

    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", run_cli_bounded)
    executed = False

    def executor(_name, _arguments):
        nonlocal executed
        executed = True
        return "unreachable", False

    async def collect() -> None:
        transport = codex_cli_adapter.CodexCliToolTransport(model="codex-test")
        with pytest.raises(ProviderUnavailableError) as raised:
            async for _ in _codex_tool_events(transport, executor):
                pass
        assert raised.value.reason.code is SafeRouteReasonCode.TOOL_EXECUTION_FAILED

    asyncio.run(collect())
    assert aborted.is_set()
    assert not executed


def test_codex_tool_transport_cleans_its_home_and_does_not_log_protocol_text(
    monkeypatch,
    caplog,
) -> None:
    calls: list = []
    lyrics = "private lyrics"
    song_id = "song-private"
    protocol = (
        "<songmaker_tool_call>\n"
        f'{{"name":"update_song_lyrics","arguments":{{"song_id":"{song_id}","lyrics":"{lyrics}"}}}}\n'
        "</songmaker_tool_call>"
    )

    def run_cli_bounded(command, **kwargs):
        calls.append((command, kwargs))
        home = Path(kwargs["extra_env"]["CODEX_HOME"])
        (home / "sessions").mkdir()
        (home / "sessions" / "private.jsonl").write_text(protocol)
        for line in (
            b'{"type":"thread.started","thread_id":"52700000-0000-4000-8000-000000000000"}\n',
            json.dumps({"type": "item.completed", "item": {
                "type": "agent_message", "text": protocol,
            }}).encode() + b"\n",
            b'{"type":"turn.completed","usage":{}}\n',
        ):
            assert kwargs["stdout_line_channel"]._send(line)
        outcome = _outcome(stderr="private stderr")
        kwargs["stdout_line_channel"]._close(outcome)
        kwargs["on_spawned"](1)
        kwargs["on_reaped"](1, False)
        return outcome

    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", run_cli_bounded)
    caplog.set_level("INFO", logger="songmaker_cli.cowriter.codex_cli_adapter")
    transport = codex_cli_adapter.CodexCliToolTransport(model="codex-test")

    async def collect_and_close() -> None:
        assert isinstance(
            [item async for item in transport.stream(InitialTurn("system", []))][0],
            ToolCallBatch,
        )
        await transport.aclose()

    asyncio.run(collect_and_close())
    assert not Path(calls[0][1]["cwd"]).exists()
    for forbidden in (lyrics, song_id, protocol, "private stderr", "private.jsonl"):
        assert forbidden not in caplog.text


def test_deadline_before_spawn_keeps_the_codex_slot_until_late_reap(monkeypatch) -> None:
    process_pool = CodexProcessPool(maximum_processes=1, maximum_cover_runs=1)
    monkeypatch.setattr(codex_cli_adapter, "get_codex_process_pool", lambda: process_pool)
    callbacks: dict[str, object] = {}

    def fake_runner(_command, **kwargs):
        callbacks.update(kwargs)
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

    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", fake_runner)
    reservation = process_pool.reserve(CodexProcessKind.TEXT)

    codex_cli_adapter._run_reserved_codex_cli(
        reservation,
        ("codex", "exec"),
        stdin_payload=b"prompt",
        read="all",
        deadline=10_000_000,
    )

    with pytest.raises(CodexProcessPoolSaturatedError):
        process_pool.reserve(CodexProcessKind.TEXT)
    callbacks["on_spawned"](41)
    callbacks["on_reaped"](41, True)
    assert process_pool.reservation_count() == 0
