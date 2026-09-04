"""Grok subscription CLI co-writer transport."""

from __future__ import annotations

import asyncio
import json
import os
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


def _stream():
    return grok_cli_adapter.stream_grok_cli_turn(
        system="system", model="grok-test", messages=[{"role": "user", "content": "hello"}],
    )


@pytest.mark.acceptance("ACC-COWRITER-09")
def test_grok_cli_streams_text_then_one_final_and_pins_its_command(monkeypatch) -> None:
    calls = []
    observed_cwd_modes = []
    lines = [
        b'{"type":"text","data":"hello"}\n',
        b'{"type":"available_commands","data":[]}\n',
        b'{"type":"end","stopReason":"stop"}\n',
    ]
    runner = _runner(lines, _outcome(), calls)

    def capture_cwd_mode(command, **kwargs):
        observed_cwd_modes.append(os.stat(kwargs["cwd"]).st_mode & 0o777)
        runner(command, **kwargs)

    monkeypatch.setattr(grok_cli_adapter, "run_cli_bounded", capture_cwd_mode)

    async def collect():
        return [event async for event in _stream()]

    events = asyncio.run(collect())

    assert events == [AssistantTextEvent(text="hello"), FinalEvent(text="hello")]
    command, kwargs = calls[0]
    assert command == (
        "grok", "--prompt-file", "<songmaker-private-prompt>",
        "--output-format", "streaming-json", "--deny", "*", "--max-turns", "1",
        "--no-subagents", "--disable-web-search", "--model", "grok-test",
    )
    assert kwargs["prompt_file_bytes"] == b"system\n\nUser: hello"
    assert kwargs["prompt_file_arg_index"] == 2
    cwd = kwargs["cwd"]
    assert cwd is not None
    assert observed_cwd_modes == [0o700]
    assert os.path.basename(cwd).startswith("songmaker-grok-cli-")
    assert kwargs["output_read_limit_bytes"] == (
        grok_cli_adapter.GROK_CLI_TURN_OUTPUT_READ_LIMIT_BYTES
    )
    assert not os.path.exists(cwd)


def test_grok_cli_text_turn_removes_its_private_session_tree(monkeypatch, tmp_path) -> None:
    calls = []
    lines = [
        b'{"type":"text","data":"hello"}\n',
        b'{"type":"end","stopReason":"stop"}\n',
    ]

    def run_cli_bounded(command, **kwargs):
        calls.append((command, kwargs))
        session_tree = tmp_path / ".grok" / "sessions" / quote(kwargs["cwd"], safe="")
        (session_tree / "legacy-session").mkdir(parents=True)
        (session_tree / "legacy-session" / "prompt_history.jsonl").write_text("private")
        for line in lines:
            assert kwargs["stdout_line_channel"]._send(line)
        outcome = _outcome()
        kwargs["stdout_line_channel"]._close(outcome)
        return outcome

    monkeypatch.setattr(grok_cli_adapter, "run_cli_bounded", run_cli_bounded)
    monkeypatch.setattr(grok_cli_adapter.Path, "home", lambda: tmp_path)

    async def collect():
        return [event async for event in _stream()]

    assert asyncio.run(collect())[-1] == FinalEvent(text="hello")
    cwd = calls[0][1]["cwd"]
    assert not (tmp_path / ".grok" / "sessions" / quote(cwd, safe="")).exists()


def test_grok_cli_removes_an_inherited_grok_home_from_the_child_environment(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("GROK_HOME", "/outside/profile")
    monkeypatch.setattr(
        grok_cli_adapter,
        "run_cli_bounded",
        _runner([
            b'{"type":"text","data":"hello"}\n',
            b'{"type":"end","stopReason":"stop"}\n',
        ], _outcome(), calls),
    )

    async def collect():
        return [event async for event in _stream()]

    assert asyncio.run(collect())[-1] == FinalEvent(text="hello")
    assert "GROK_HOME" not in calls[0][1]["extra_env"]
    assert calls[0][1]["unset_env"] == ("GROK_HOME",)


@pytest.mark.parametrize("event_type", sorted(grok_cli_adapter._IGNORED_EVENT_TYPES))
def test_grok_cli_accepts_ignored_observations_without_data(monkeypatch, event_type) -> None:
    calls = []
    lines = [
        json.dumps({"type": event_type}).encode() + b"\n",
        b'{"type":"text","data":"hello"}\n',
        b'{"type":"end","stopReason":"stop"}\n',
    ]
    monkeypatch.setattr(
        grok_cli_adapter,
        "run_cli_bounded",
        _runner(lines, _outcome(), calls),
    )

    async def collect():
        return [event async for event in _stream()]

    assert asyncio.run(collect()) == [
        AssistantTextEvent(text="hello"),
        FinalEvent(text="hello"),
    ]


def test_grok_cli_rejects_an_unknown_event_type_without_logging_its_protocol(
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

    async def collect():
        return [event async for event in _stream()]

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(collect())

    assert raised.value.reason.code is SafeRouteReasonCode.CLI_PROTOCOL_ERROR
    assert event_type not in caplog.text


@pytest.mark.parametrize("event_type", ("tool_call", "tool_call_update"))
def test_grok_cli_rejects_any_tool_call_and_never_emits_a_final(monkeypatch, event_type) -> None:
    calls = []
    lines = [json.dumps({"type": event_type}).encode() + b"\n"]
    monkeypatch.setattr(
        grok_cli_adapter,
        "run_cli_bounded",
        _runner(lines, _outcome(), calls),
    )

    async def collect():
        return [event async for event in _stream()]

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(collect())

    assert raised.value.reason.code is SafeRouteReasonCode.ROUTE_TEXT_ONLY
    assert calls


def test_grok_cli_process_streams_ndjson_through_the_bounded_runner(monkeypatch, tmp_path) -> None:
    fake_cli = tmp_path / "grok"
    fake_cli.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' "
        '\'{"type":"text","data":"hello"}\' '
        '\'{"type":"end","stopReason":"stop"}\'\n',
    )
    fake_cli.chmod(0o700)
    monkeypatch.setattr(grok_cli_adapter, "GROK_CLI_BINARY", str(fake_cli))

    async def collect():
        return [event async for event in _stream()]

    assert asyncio.run(collect()) == [
        AssistantTextEvent(text="hello"),
        FinalEvent(text="hello"),
    ]


@pytest.mark.parametrize(
    "lines",
    (
        [b"not json\n"],
        [
            b'{"type":"text","data":"one"}\n',
            b'{"type":"end","stopReason":"stop"}\n',
            b'{"type":"end","stopReason":"stop"}\n',
        ],
    ),
)
def test_grok_cli_rejects_an_invalid_or_unfinished_stream(monkeypatch, lines) -> None:
    calls = []
    monkeypatch.setattr(
        grok_cli_adapter,
        "run_cli_bounded",
        _runner(lines, _outcome(), calls),
    )

    async def collect():
        return [event async for event in _stream()]

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(collect())

    assert raised.value.reason.code is SafeRouteReasonCode.CLI_PROTOCOL_ERROR


def test_grok_cli_normalizes_malformed_json_without_its_document(monkeypatch) -> None:
    document = '{"type":"text","data":"private lyrics"'
    calls = []
    monkeypatch.setattr(
        grok_cli_adapter,
        "run_cli_bounded",
        _runner([document.encode() + b"\n"], _outcome(), calls),
    )

    async def collect():
        return [event async for event in _stream()]

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(collect())

    assert raised.value.reason.code is SafeRouteReasonCode.CLI_PROTOCOL_ERROR
    assert raised.value.__cause__ is None
    assert not hasattr(raised.value.__context__, "doc")
    assert document not in str(raised.value)


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
        (
            [],
            _outcome(complete=False),
            SafeRouteReasonCode.CLI_PROTOCOL_ERROR,
        ),
        (
            [b'{"type":"text","data":"partial"}\n'],
            _outcome(complete=False),
            SafeRouteReasonCode.CLI_PROTOCOL_ERROR,
        ),
        (
            [b'{"type":"end","stopReason":"stop"}\n'],
            _outcome(returncode=1),
            SafeRouteReasonCode.CLI_PROTOCOL_ERROR,
        ),
    ),
)
def test_grok_cli_names_failed_or_incomplete_runs_without_leaking_stderr(
    monkeypatch, caplog, lines, outcome, code,
) -> None:
    calls = []
    monkeypatch.setattr(
        grok_cli_adapter,
        "run_cli_bounded",
        _runner(lines, outcome, calls),
    )
    caplog.set_level("WARNING")

    async def collect():
        return [event async for event in _stream()]

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(collect())

    assert raised.value.reason.code is code
    assert "OIDC 401" not in caplog.text


def test_closing_a_grok_stream_requests_runner_cancellation_and_waits_for_reap(monkeypatch) -> None:
    started = threading.Event()
    aborted = threading.Event()

    def run_cli_bounded(_command, **kwargs):
        channel = kwargs["stdout_line_channel"]
        assert channel._send(b'{"type":"text","data":"partial"}\n')
        assert started.wait(timeout=1)
        while not channel.abort_requested():
            time.sleep(0.001)
        aborted.set()
        outcome = _outcome(complete=False)
        channel._close(outcome)
        return outcome

    monkeypatch.setattr(grok_cli_adapter, "run_cli_bounded", run_cli_bounded)

    async def close_stream() -> None:
        stream = _stream()
        assert await anext(stream) == AssistantTextEvent(text="partial")
        started.set()
        await stream.aclose()

    asyncio.run(close_stream())
    assert aborted.is_set()


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
