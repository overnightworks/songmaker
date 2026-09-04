"""Grok subscription CLI transport for the shared co-writer tool loop."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from urllib.parse import quote

import pytest

from songmaker_cli.agent_cli import CliRunOutcome, CliRunReason
from songmaker_cli.claude.provider import AssistantTextEvent, FinalEvent, ToolCallEvent
from songmaker_cli.cowriter import grok_cli_adapter
from songmaker_cli.cowriter.errors import ProviderUnavailableError, SafeRouteReasonCode
from songmaker_cli.cowriter.tool_loop import (
    InitialTurn,
    ToolCallBatch,
    ToolResult,
    ToolResultBatch,
    stream_tool_loop,
)

_SESSION_ID = "3e04bf5b-4e1c-4f26-8e1e-2f17c5f6d9cf"


def _outcome(*, returncode: int = 0, complete: bool = True, stderr: str = "") -> CliRunOutcome:
    return CliRunOutcome(
        started=True,
        spawn_error=None,
        returncode=returncode,
        stdout="",
        stderr=stderr,
        complete=complete,
        became_zombie=False,
        reason=CliRunReason.COMPLETE,
    )


def _runner(lines, outcome, calls):
    def run_cli_bounded(command, **kwargs):
        calls.append((command, kwargs))
        for line in lines:
            assert kwargs["stdout_line_channel"]._send(line)
        kwargs["stdout_line_channel"]._close(outcome)
        return outcome

    return run_cli_bounded


def _tool_call_text() -> str:
    return (
        '<songmaker_tool_call>\n'
        '{"name":"list_songs","arguments":{}}\n'
        '</songmaker_tool_call>'
    )


def _tool_round_lines(text: str, session_id: str = _SESSION_ID) -> list[bytes]:
    return [
        json.dumps({"type": "text", "data": text}).encode() + b"\n",
        json.dumps({
            "type": "end", "stopReason": "stop", "sessionId": session_id,
        }).encode() + b"\n",
    ]


def _tool_transport_events(transport, executor):
    return stream_tool_loop(
        provider="grok",
        route="cli",
        system="system",
        messages=[{"role": "user", "content": "hello"}],
        transport=transport,
        executor=executor,
    )


async def _collect_transport_responses(transport) -> list[object]:
    return [item async for item in transport.stream(InitialTurn("system", []))]


def test_grok_tool_transport_starts_then_resumes_with_prompt_files_only(monkeypatch) -> None:
    calls = []
    rounds = iter([_tool_round_lines(_tool_call_text()), _tool_round_lines("done")])

    def run_cli_bounded(command, **kwargs):
        calls.append((command, kwargs))
        for line in next(rounds):
            assert kwargs["stdout_line_channel"]._send(line)
        outcome = _outcome()
        kwargs["stdout_line_channel"]._close(outcome)
        return outcome

    monkeypatch.setattr(grok_cli_adapter, "run_cli_bounded", run_cli_bounded)
    transport = grok_cli_adapter.GrokCliToolTransport(model="grok-test")

    events = asyncio.run(_collect_tool_events(
        _tool_transport_events(transport, lambda _name, _arguments: ('{"songs":[]}', False)),
    ))

    assert isinstance(events[0], ToolCallEvent)
    assert events[-1] == FinalEvent(text="done")
    first_command, first_kwargs = calls[0]
    second_command, second_kwargs = calls[1]
    assert "--session-id" not in first_command
    assert "--resume" not in first_command
    assert second_command[-2:] == ("--resume", _SESSION_ID)
    for command, kwargs in calls:
        assert command.count("--deny") == 1
        assert command[command.index("--deny") + 1] == "*"
        assert kwargs["stdin_payload"] is None
        assert kwargs["prompt_file_arg_index"] == 2
        assert kwargs["output_read_limit_bytes"] == (
            grok_cli_adapter.GROK_CLI_TURN_OUTPUT_READ_LIMIT_BYTES
        )
        assert "GROK_HOME" not in kwargs["extra_env"]
        assert kwargs["unset_env"] == ("GROK_HOME",)
    assert first_kwargs["prompt_file_bytes"] == b"system\n\nUser: hello"
    assert second_kwargs["prompt_file_bytes"] == (
        b'<songmaker_tool_result>\n{"songs":[]}\n</songmaker_tool_result>'
    )
    assert first_kwargs["deadline"] == second_kwargs["deadline"]
    assert not Path(first_kwargs["cwd"]).exists()


def test_grok_tool_transport_rejects_a_multi_result_batch(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        grok_cli_adapter,
        "run_cli_bounded",
        _runner(_tool_round_lines(_tool_call_text()), _outcome(), calls),
    )
    transport = grok_cli_adapter.GrokCliToolTransport(model="grok-test")

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


@pytest.mark.parametrize("session_id", (None, "not-a-uuid"))
def test_grok_tool_transport_rejects_missing_or_invalid_session_id(
    monkeypatch, session_id,
) -> None:
    calls = []
    end_event = {"type": "end", "stopReason": "stop"}
    if session_id is not None:
        end_event["sessionId"] = session_id
    lines = [
        json.dumps({"type": "text", "data": "done"}).encode() + b"\n",
        json.dumps(end_event).encode() + b"\n",
    ]
    monkeypatch.setattr(
        grok_cli_adapter,
        "run_cli_bounded",
        _runner(lines, _outcome(), calls),
    )
    transport = grok_cli_adapter.GrokCliToolTransport(model="grok-test")

    async def collect() -> None:
        with pytest.raises(ProviderUnavailableError) as raised:
            async for _ in transport.stream(InitialTurn("system", [])):
                pass
        assert raised.value.reason.code is SafeRouteReasonCode.CLI_PROTOCOL_ERROR
        await transport.aclose()

    asyncio.run(collect())


def test_grok_tool_transport_normalizes_malformed_json_without_its_document(monkeypatch) -> None:
    document = '{"type":"text","data":"private lyrics"'
    calls = []
    monkeypatch.setattr(
        grok_cli_adapter,
        "run_cli_bounded",
        _runner([document.encode() + b"\n"], _outcome(), calls),
    )
    transport = grok_cli_adapter.GrokCliToolTransport(model="grok-test")

    async def collect() -> None:
        with pytest.raises(ProviderUnavailableError) as raised:
            await _collect_transport_responses(transport)
        assert raised.value.reason.code is SafeRouteReasonCode.CLI_PROTOCOL_ERROR
        assert raised.value.__cause__ is None
        assert not hasattr(raised.value.__context__, "doc")
        assert document not in str(raised.value)
        await transport.aclose()

    asyncio.run(collect())


def test_grok_tool_transport_rejects_unknown_events_without_logging_the_protocol(
    monkeypatch, caplog,
) -> None:
    calls = []
    event_type = "unexpected"
    monkeypatch.setattr(
        grok_cli_adapter,
        "run_cli_bounded",
        _runner([json.dumps({"type": event_type}).encode() + b"\n"], _outcome(), calls),
    )
    caplog.set_level("WARNING")
    transport = grok_cli_adapter.GrokCliToolTransport(model="grok-test")

    async def collect() -> None:
        with pytest.raises(ProviderUnavailableError) as raised:
            await _collect_transport_responses(transport)
        assert raised.value.reason.code is SafeRouteReasonCode.CLI_PROTOCOL_ERROR
        await transport.aclose()

    asyncio.run(collect())
    assert event_type not in caplog.text


@pytest.mark.parametrize("event_type", ("thought", "usage", "available_commands", "plan"))
def test_grok_tool_transport_accepts_ignored_observations_without_data(
    monkeypatch, event_type,
) -> None:
    calls = []
    lines = [
        json.dumps({"type": event_type}).encode() + b"\n",
        *_tool_round_lines("done"),
    ]
    monkeypatch.setattr(
        grok_cli_adapter,
        "run_cli_bounded",
        _runner(lines, _outcome(), calls),
    )
    transport = grok_cli_adapter.GrokCliToolTransport(model="grok-test")

    async def collect() -> None:
        assert await _collect_transport_responses(transport) == [
            grok_cli_adapter.TextDelta("done"),
            grok_cli_adapter.FinalText(""),
        ]
        await transport.aclose()

    asyncio.run(collect())


def test_grok_tool_transport_rejects_a_second_end_event(monkeypatch) -> None:
    calls = []
    lines = [*_tool_round_lines("done"), _tool_round_lines("ignored")[1]]
    monkeypatch.setattr(
        grok_cli_adapter,
        "run_cli_bounded",
        _runner(lines, _outcome(), calls),
    )
    transport = grok_cli_adapter.GrokCliToolTransport(model="grok-test")

    async def collect() -> None:
        with pytest.raises(ProviderUnavailableError) as raised:
            await _collect_transport_responses(transport)
        assert raised.value.reason.code is SafeRouteReasonCode.CLI_PROTOCOL_ERROR
        await transport.aclose()

    asyncio.run(collect())


@pytest.mark.parametrize(
    ("lines", "outcome", "code"),
    (
        (
            [b'{"type":"error","message":"login problem"}\n'],
            _outcome(stderr="OIDC 401"),
            SafeRouteReasonCode.CLI_AUTH_REJECTED,
        ),
        (
            [b'{"type":"error","message":"unauthenticated"}\n'],
            _outcome(),
            SafeRouteReasonCode.CLI_AUTH_REJECTED,
        ),
        (
            [b'{"type":"text","data":"partial"}\n'],
            _outcome(complete=False, stderr="OIDC 401"),
            SafeRouteReasonCode.CLI_AUTH_REJECTED,
        ),
        ([], _outcome(complete=False), SafeRouteReasonCode.CLI_PROTOCOL_ERROR),
        (
            [b'{"type":"text","data":"partial"}\n'],
            _outcome(complete=False),
            SafeRouteReasonCode.CLI_PROTOCOL_ERROR,
        ),
        (
            [b'{"type":"end","stopReason":"stop","sessionId":"' + _SESSION_ID.encode()
             + b'"}\n'],
            _outcome(returncode=1),
            SafeRouteReasonCode.CLI_PROTOCOL_ERROR,
        ),
    ),
)
def test_grok_tool_transport_names_failed_or_incomplete_runs_without_leaking_stderr(
    monkeypatch, caplog, lines, outcome, code,
) -> None:
    calls = []
    monkeypatch.setattr(
        grok_cli_adapter,
        "run_cli_bounded",
        _runner(lines, outcome, calls),
    )
    caplog.set_level("WARNING")
    transport = grok_cli_adapter.GrokCliToolTransport(model="grok-test")

    async def collect() -> None:
        with pytest.raises(ProviderUnavailableError) as raised:
            await _collect_transport_responses(transport)
        assert raised.value.reason.code is code
        await transport.aclose()

    asyncio.run(collect())
    assert "OIDC 401" not in caplog.text


def test_grok_tool_transport_rejects_a_changed_resume_session_id(monkeypatch) -> None:
    calls = []
    changed_session_id = "4ee93ca6-9a08-4d8a-8539-e113a8d677ed"
    rounds = iter([
        _tool_round_lines("first"),
        _tool_round_lines("second", changed_session_id),
    ])

    def run_cli_bounded(command, **kwargs):
        calls.append((command, kwargs))
        for line in next(rounds):
            assert kwargs["stdout_line_channel"]._send(line)
        outcome = _outcome()
        kwargs["stdout_line_channel"]._close(outcome)
        return outcome

    monkeypatch.setattr(grok_cli_adapter, "run_cli_bounded", run_cli_bounded)
    transport = grok_cli_adapter.GrokCliToolTransport(model="grok-test")

    async def collect() -> None:
        assert [item async for item in transport.stream(InitialTurn("system", []))] == [
            grok_cli_adapter.TextDelta("first"),
            grok_cli_adapter.FinalText(""),
        ]
        with pytest.raises(ProviderUnavailableError) as raised:
            async for _ in transport.stream(ToolResultBatch((
                ToolResult("one", "1", False),
            ))):
                pass
        assert raised.value.reason.code is SafeRouteReasonCode.CLI_PROTOCOL_ERROR
        await transport.aclose()

    asyncio.run(collect())
    assert calls[1][0][-2:] == ("--resume", _SESSION_ID)


@pytest.mark.parametrize("event_type", ("tool_call", "tool_call_update"))
def test_grok_tool_transport_aborts_native_calls_before_the_loop_executes(
    monkeypatch, event_type,
) -> None:
    aborted = threading.Event()

    def run_cli_bounded(_command, **kwargs):
        channel = kwargs["stdout_line_channel"]
        assert channel._send(json.dumps({"type": event_type}).encode() + b"\n")
        while not channel.abort_requested():
            time.sleep(0.001)
        aborted.set()
        outcome = _outcome(complete=False)
        channel._close(outcome)
        return outcome

    monkeypatch.setattr(grok_cli_adapter, "run_cli_bounded", run_cli_bounded)
    executed = False

    def executor(_name, _arguments):
        nonlocal executed
        executed = True
        return "unreachable", False

    async def collect() -> None:
        transport = grok_cli_adapter.GrokCliToolTransport(model="grok-test")
        with pytest.raises(ProviderUnavailableError) as raised:
            async for _ in _tool_transport_events(transport, executor):
                pass
        assert raised.value.reason.code is SafeRouteReasonCode.TOOL_PROTOCOL_ERROR

    asyncio.run(collect())
    assert aborted.is_set()
    assert not executed


def test_closing_the_tool_loop_aborts_and_reaps_the_grok_runner(monkeypatch) -> None:
    started = threading.Event()
    aborted = threading.Event()

    def run_cli_bounded(_command, **kwargs):
        channel = kwargs["stdout_line_channel"]
        assert channel._send(b'{"type":"text","data":"partial"}\n')
        assert started.wait(timeout=1)
        while not channel.abort_requested():
            time.sleep(0.001)
        aborted.set()
        channel._close(_outcome(complete=False))
        return _outcome(complete=False)

    monkeypatch.setattr(grok_cli_adapter, "run_cli_bounded", run_cli_bounded)
    transport = grok_cli_adapter.GrokCliToolTransport(model="grok-test")

    async def close_turn() -> None:
        turn = _tool_transport_events(transport, lambda _name, _arguments: ("unused", False))
        assert await anext(turn) == AssistantTextEvent(text="partial")
        started.set()
        await turn.aclose()

    asyncio.run(close_turn())
    assert aborted.is_set()


def test_grok_tool_transport_removes_its_private_session_tree_and_redacts_logs(
    monkeypatch, tmp_path, caplog,
) -> None:
    calls = []
    lyrics = "private lyrics"
    song_id = "song-private"
    call_json = f'{{"lyrics":"{lyrics}","song_id":"{song_id}"}}'
    stderr_document = "private stderr document"
    tool_call = (
        f"<songmaker_tool_call>\n"
        f'{{"name":"update_song_lyrics","arguments":{call_json}}}\n'
        "</songmaker_tool_call>"
    )

    def run_cli_bounded(command, **kwargs):
        calls.append((command, kwargs))
        session_tree = (
            tmp_path / ".grok" / "sessions" / quote(kwargs["cwd"], safe="") / _SESSION_ID
        )
        session_tree.mkdir(parents=True)
        (session_tree / "prompt_history.jsonl").write_text(f"{lyrics} {song_id}")
        for line in _tool_round_lines(tool_call):
            assert kwargs["stdout_line_channel"]._send(line)
        outcome = _outcome(stderr=stderr_document)
        kwargs["stdout_line_channel"]._close(outcome)
        return outcome

    monkeypatch.setattr(grok_cli_adapter, "run_cli_bounded", run_cli_bounded)
    monkeypatch.setattr(grok_cli_adapter.Path, "home", lambda: tmp_path)
    caplog.set_level("INFO", logger="songmaker_cli.cowriter.grok_cli_adapter")
    transport = grok_cli_adapter.GrokCliToolTransport(model="grok-test")

    async def collect_and_close() -> None:
        assert isinstance(
            [item async for item in transport.stream(InitialTurn("system", []))][0],
            ToolCallBatch,
        )
        await transport.aclose()

    asyncio.run(collect_and_close())
    cwd = calls[0][1]["cwd"]
    assert not (tmp_path / ".grok" / "sessions" / quote(cwd, safe="")).exists()
    for forbidden in (lyrics, song_id, call_json, stderr_document, "prompt_history"):
        assert forbidden not in caplog.text


async def _collect_tool_events(stream) -> list[object]:
    return [event async for event in stream]
