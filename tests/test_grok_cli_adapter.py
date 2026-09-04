"""Grok subscription CLI co-writer transport."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time

import pytest

from songmaker_cli.agent_cli import CliRunOutcome, CliRunReason
from songmaker_cli.claude.provider import AssistantTextEvent, FinalEvent
from songmaker_cli.cowriter import grok_cli_adapter
from songmaker_cli.cowriter.errors import ProviderUnavailableError, SafeRouteReasonCode


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


def test_grok_cli_logs_the_length_of_an_unknown_event_type_before_rejecting_it(
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
    assert f"type_length={len(event_type)}" in caplog.text


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

    assert raised.value.reason.code is SafeRouteReasonCode.TOOL_EXECUTION_FAILED
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
