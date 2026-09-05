"""Codex subscription CLI co-writer transport."""

from __future__ import annotations

import asyncio
import json
import os
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

_RECORDED_STREAM = Path(__file__).parent / "fixtures" / "codex_cli_real_stream.jsonl"
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


def _stream():
    return codex_cli_adapter.stream_codex_cli_turn(
        system="system", model="codex-test", messages=[{"role": "user", "content": "hello"}],
    )


async def _collect():
    return [event async for event in _stream()]


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


def _recorded_stream_lines() -> list[bytes]:
    events = [json.loads(line) for line in _RECORDED_STREAM.read_text().splitlines()]
    for event in events:
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            item["text"] = "OK"
    return [json.dumps(event).encode() + b"\n" for event in events]


@pytest.mark.acceptance("ACC-COWRITER-12")
def test_codex_cli_streams_text_then_one_final_and_pins_its_command(monkeypatch) -> None:
    calls: list = []
    observed_cwd_modes: list[int] = []
    observed_auth: list[dict] = []
    runner = _runner([
        b'{"type":"thread.started"}\n',
        b'{"type":"turn.started"}\n',
        b'{"type":"item.completed","item":{"type":"reasoning"}}\n',
        b'{"type":"item.completed","item":{"type":"agent_message","text":"hello"}}\n',
        b'{"type":"turn.completed","usage":{}}\n',
    ], _outcome(), calls)

    def capture_cwd_mode(command, **kwargs):
        observed_cwd_modes.append(os.stat(kwargs["cwd"]).st_mode & 0o777)
        auth_path = Path(kwargs["extra_env"]["CODEX_HOME"]) / "auth.json"
        observed_auth.append(json.loads(auth_path.read_text()))
        assert auth_path.stat().st_mode & 0o777 == 0o600
        return runner(command, **kwargs)

    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", capture_cwd_mode)

    assert asyncio.run(_collect()) == [
        AssistantTextEvent(text="hello"),
        FinalEvent(text="hello"),
    ]
    command, kwargs = calls[0]
    assert command == (
        "codex", "exec", "--json", "--sandbox", "read-only", "--skip-git-repo-check",
        "--ignore-user-config", "--ignore-rules", "--ephemeral", "--disable", "code_mode_host",
        "--disable", "code_mode", "--disable", "code_mode_only", "-c", 'approval_policy="never"',
        "-c", "mcp_servers={}", "--model", "codex-test", "-",
    )
    assert kwargs["stdin_payload"] == b"system\n\nUser: hello"
    assert kwargs["read"] == "all"
    assert kwargs["output_read_limit_bytes"] == (
        codex_cli_adapter.CODEX_CLI_TURN_OUTPUT_READ_LIMIT_BYTES
    )
    assert observed_cwd_modes == [0o700]
    assert observed_auth == [_REDACTED_CODEX_LOGIN]
    assert calls[0][1]["extra_env"]["CODEX_HOME"].endswith("/codex-home")
    assert os.path.basename(kwargs["cwd"]).startswith("songmaker-codex-cli-")
    assert not os.path.exists(kwargs["cwd"])


def test_codex_cli_accepts_the_recorded_real_stream_and_returns_one_final(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(
        codex_cli_adapter,
        "run_cli_bounded",
        _runner(_recorded_stream_lines(), _outcome(), calls),
    )

    assert asyncio.run(_collect()) == [
        AssistantTextEvent(text="OK"),
        FinalEvent(text="OK"),
    ]


def test_codex_tool_transport_starts_then_resumes_with_private_prompt_files(monkeypatch) -> None:
    calls: list = []
    prompts: list[bytes] = []
    scrubbed_calls = 0
    thread_id = "fixture-codex-thread-527"
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
        prompt_file = next(Path(kwargs["cwd"]).glob("prompt-*"))
        prompts.append(prompt_file.read_bytes())
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
        for config in (
            'approval_policy="never"',
            "mcp_servers={}",
            "features.shell_tool=false",
            'web_search="disabled"',
            'sandbox_mode="read-only"',
        ):
            assert config in command
    assert prompts == [
        b"system\n\nUser: hello",
        b'<songmaker_tool_result>\n{"songs":[]}\n</songmaker_tool_result>',
    ]
    assert not Path(first_kwargs["cwd"]).exists()
    assert first_kwargs["extra_env"] == second_kwargs["extra_env"]
    assert scrubbed_calls == 2


def test_codex_tool_transport_rejects_a_multi_result_batch_without_a_resume(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", _runner([
        b'{"type":"thread.started","thread_id":"fixture-codex-thread-527"}\n',
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


@pytest.mark.parametrize("item_type", (
    "file_change", "command_execution", "mcp_tool_call", "web_search",
))
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
            b'{"type":"thread.started","thread_id":"fixture-codex-thread-527"}\n',
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


def test_codex_cli_turn_names_pool_saturation_without_starting_a_runner(monkeypatch) -> None:
    process_pool = CodexProcessPool(maximum_processes=1, maximum_cover_runs=1)
    process_pool.reserve(CodexProcessKind.TEXT)
    monkeypatch.setattr(codex_cli_adapter, "get_codex_process_pool", lambda: process_pool)
    runner_called = False

    def fake_runner(*_args, **_kwargs):
        nonlocal runner_called
        runner_called = True
        raise AssertionError("a saturated pool must reject before spawning")

    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", fake_runner)

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(_collect())

    assert raised.value.reason.code is SafeRouteReasonCode.CLI_CAPACITY_EXHAUSTED
    assert not runner_called


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


@pytest.mark.parametrize("event_type", sorted(codex_cli_adapter._ITEM_EVENT_TYPES))
@pytest.mark.parametrize("item_type", sorted(codex_cli_adapter._INFORMATIONAL_ITEM_TYPES))
def test_codex_cli_ignores_informational_item_lifecycle_events(
    monkeypatch, event_type, item_type,
) -> None:
    calls: list = []
    item: dict[str, str] = {"type": item_type}
    expected = [FinalEvent(text="")]
    if event_type == "item.completed" and item_type == "agent_message":
        item["text"] = "OK"
        expected = [AssistantTextEvent(text="OK"), FinalEvent(text="OK")]
    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", _runner([
        json.dumps({"type": event_type, "item": item}).encode() + b"\n",
        b'{"type":"turn.completed","usage":{}}\n',
    ], _outcome(), calls))

    assert asyncio.run(_collect()) == expected


@pytest.mark.parametrize("item_type", sorted(codex_cli_adapter._BLOCKED_ITEM_TYPES))
def test_codex_cli_blocks_tool_items_without_emitting_a_final(monkeypatch, item_type) -> None:
    calls: list = []
    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", _runner([
        json.dumps({"type": "item.started", "item": {"type": item_type}}).encode() + b"\n",
    ], _outcome(), calls))

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(_collect())

    assert raised.value.reason.code is SafeRouteReasonCode.TOOL_EXECUTION_FAILED
    assert calls


@pytest.mark.parametrize(
    "line",
    (
        b"not json\n",
        b'{"type":"item.completed","item":{"type":"future_item"}}\n',
        b'{"type":"item.completed","item":{"type":"agent_message"}}\n',
        b'{"type":"turn.completed"}\n',
    ),
)
def test_codex_cli_rejects_malformed_and_unknown_stream_items(monkeypatch, line) -> None:
    calls: list = []
    monkeypatch.setattr(
        codex_cli_adapter, "run_cli_bounded", _runner([line], _outcome(), calls),
    )

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(_collect())

    assert raised.value.reason.code is SafeRouteReasonCode.CLI_PROTOCOL_ERROR


def test_codex_cli_names_unknown_stream_events_in_the_log(monkeypatch, caplog) -> None:
    calls: list = []
    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", _runner([
        b'{"type":"turn.unknown"}\n',
    ], _outcome(), calls))
    caplog.set_level("WARNING")

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(_collect())

    assert raised.value.reason.code is SafeRouteReasonCode.CLI_PROTOCOL_ERROR
    assert "event_type=turn.unknown" in caplog.text


def test_codex_cli_names_unknown_item_types_without_logging_item_content(
    monkeypatch, caplog,
) -> None:
    calls: list = []
    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", _runner([
        b'{"type":"item.completed","item":{"type":"future_item","text":"secret"}}\n',
    ], _outcome(), calls))
    caplog.set_level("WARNING")

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(_collect())

    assert raised.value.reason.code is SafeRouteReasonCode.CLI_PROTOCOL_ERROR
    assert "event_type=item.completed" in caplog.text
    assert "item_type=future_item" in caplog.text
    assert "secret" not in caplog.text


def test_codex_cli_delivers_a_completed_turn_after_logging_an_error_item(
    monkeypatch, caplog,
) -> None:
    calls: list = []
    message = (
        "Code Mode is unavailable because failed to spawn code-mode host "
        "/private/companion/token-value"
    )
    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", _runner([
        json.dumps({"type": "item.completed", "item": {
            "type": "error", "message": message,
        }}).encode() + b"\n",
        b'{"type":"item.completed","item":{"type":"agent_message","text":"OK"}}\n',
        b'{"type":"turn.completed","usage":{}}\n',
    ], _outcome(), calls))
    caplog.set_level("WARNING")

    assert asyncio.run(_collect()) == [
        AssistantTextEvent(text="OK"),
        FinalEvent(text="OK"),
    ]

    assert "message_class=code_mode_is_unavailable" in caplog.text
    assert message not in caplog.text
    assert "/private/companion" not in caplog.text


@pytest.mark.parametrize(
    ("message", "reason"),
    (
        ("Code Mode is unavailable", SafeRouteReasonCode.CLI_PROTOCOL_ERROR),
        ("Request failed with 401 Unauthorized", SafeRouteReasonCode.CLI_AUTH_REJECTED),
    ),
)
def test_codex_cli_classifies_an_error_item_without_a_completed_turn(
    monkeypatch, message, reason,
) -> None:
    calls: list = []
    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", _runner([
        json.dumps({"type": "item.completed", "item": {
            "type": "error", "message": message,
        }}).encode() + b"\n",
    ], _outcome(), calls))

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(_collect())

    assert raised.value.reason.code is reason


@pytest.mark.parametrize("event_type", ("item.started", "item.updated"))
def test_codex_cli_rejects_nonterminal_error_items_as_protocol_errors(
    monkeypatch, event_type,
) -> None:
    calls: list = []
    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", _runner([
        json.dumps({"type": event_type, "item": {
            "type": "error", "message": "not a terminal CLI failure",
        }}).encode() + b"\n",
    ], _outcome(), calls))

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(_collect())

    assert raised.value.reason.code is SafeRouteReasonCode.CLI_PROTOCOL_ERROR


@pytest.mark.parametrize(
    "lines",
    (
        [],
        [b'{"type":"turn.completed","usage":{}}\n', b'{"type":"turn.completed","usage":{}}\n'],
    ),
)
def test_codex_cli_requires_exactly_one_successful_completed_turn(monkeypatch, lines) -> None:
    calls: list = []
    monkeypatch.setattr(
        codex_cli_adapter, "run_cli_bounded", _runner(lines, _outcome(), calls),
    )

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(_collect())

    assert raised.value.reason.code is SafeRouteReasonCode.CLI_PROTOCOL_ERROR


@pytest.mark.parametrize(
    ("line", "outcome", "code"),
    (
        (
            b'{"type":"error","message":"Reconnecting after 401 Unauthorized"}\n',
            _outcome(),
            SafeRouteReasonCode.CLI_AUTH_REJECTED,
        ),
        (
            b'{"type":"turn.failed","error":{"message":"failed"}}\n',
            _outcome(stderr="unauthenticated"),
            SafeRouteReasonCode.CLI_AUTH_REJECTED,
        ),
        (
            b'{"type":"error","message":"internal diagnostic"}\n',
            _outcome(),
            SafeRouteReasonCode.CLI_PROTOCOL_ERROR,
        ),
    ),
)
def test_codex_cli_classifies_errors_without_logging_payloads(
    monkeypatch, caplog, line, outcome, code,
) -> None:
    calls: list = []
    monkeypatch.setattr(
        codex_cli_adapter, "run_cli_bounded", _runner([line], outcome, calls),
    )
    caplog.set_level("WARNING")

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(_collect())

    assert raised.value.reason.code is code
    assert "internal diagnostic" not in caplog.text
    assert "unauthenticated" not in caplog.text


@pytest.mark.parametrize(
    ("lines", "outcome", "code"),
    (
        ([], _outcome(complete=False, stderr="401"), SafeRouteReasonCode.CLI_AUTH_REJECTED),
        ([], _outcome(complete=False), SafeRouteReasonCode.CLI_PROTOCOL_ERROR),
        (
            [b'{"type":"turn.completed","usage":{}}\n'],
            _outcome(returncode=1),
            SafeRouteReasonCode.CLI_PROTOCOL_ERROR,
        ),
        (
            [],
            _outcome(complete=False, reason=CliRunReason.OUTPUT_LIMIT_REACHED),
            SafeRouteReasonCode.CLI_PROTOCOL_ERROR,
        ),
    ),
)
def test_codex_cli_classifies_runner_failures(monkeypatch, lines, outcome, code) -> None:
    calls: list = []
    monkeypatch.setattr(
        codex_cli_adapter, "run_cli_bounded", _runner(lines, outcome, calls),
    )

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(_collect())

    assert raised.value.reason.code is code


def test_closing_a_codex_stream_requests_runner_cancellation_and_waits_for_reap(
    monkeypatch,
) -> None:
    started = threading.Event()
    aborted = threading.Event()

    def run_cli_bounded(_command, **kwargs):
        channel = kwargs["stdout_line_channel"]
        assert channel._send(
            b'{"type":"item.completed","item":{"type":"agent_message","text":"partial"}}\n',
        )
        assert started.wait(timeout=1)
        while not channel.abort_requested():
            time.sleep(0.001)
        aborted.set()
        outcome = _outcome(complete=False)
        channel._close(outcome)
        kwargs["on_spawned"](1)
        kwargs["on_reaped"](1, False)
        return outcome

    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", run_cli_bounded)

    async def close_stream() -> None:
        stream = _stream()
        assert await anext(stream) == AssistantTextEvent(text="partial")
        started.set()
        await stream.aclose()

    asyncio.run(close_stream())
    assert aborted.is_set()
