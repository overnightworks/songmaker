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
from songmaker_cli.claude.provider import AssistantTextEvent, FinalEvent
from songmaker_cli.cowriter import codex_cli_adapter
from songmaker_cli.cowriter.errors import ProviderUnavailableError, SafeRouteReasonCode

_RECORDED_STREAM = Path(__file__).parent / "fixtures" / "codex_cli_real_stream.jsonl"


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
        return outcome

    return run_cli_bounded


def _stream():
    return codex_cli_adapter.stream_codex_cli_turn(
        system="system", model="codex-test", messages=[{"role": "user", "content": "hello"}],
    )


async def _collect():
    return [event async for event in _stream()]


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
    runner = _runner([
        b'{"type":"thread.started"}\n',
        b'{"type":"turn.started"}\n',
        b'{"type":"item.completed","item":{"type":"reasoning"}}\n',
        b'{"type":"item.completed","item":{"type":"agent_message","text":"hello"}}\n',
        b'{"type":"turn.completed","usage":{}}\n',
    ], _outcome(), calls)

    def capture_cwd_mode(command, **kwargs):
        observed_cwd_modes.append(os.stat(kwargs["cwd"]).st_mode & 0o777)
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
        return outcome

    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", run_cli_bounded)

    async def close_stream() -> None:
        stream = _stream()
        assert await anext(stream) == AssistantTextEvent(text="partial")
        started.set()
        await stream.aclose()

    asyncio.run(close_stream())
    assert aborted.is_set()
