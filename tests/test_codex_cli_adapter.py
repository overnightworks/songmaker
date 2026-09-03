"""Codex subscription CLI co-writer transport."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time

import pytest

from songmaker_cli.agent_cli import CliRunOutcome, CliRunReason
from songmaker_cli.claude.provider import AssistantTextEvent, FinalEvent
from songmaker_cli.cowriter import codex_cli_adapter
from songmaker_cli.cowriter.errors import ProviderUnavailableError


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
        "--ignore-user-config", "--ignore-rules", "--ephemeral", "-c", 'approval_policy="never"',
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


@pytest.mark.parametrize("item_type", sorted(codex_cli_adapter._BLOCKED_ITEM_TYPES))
def test_codex_cli_blocks_tool_items_without_emitting_a_final(monkeypatch, item_type) -> None:
    calls: list = []
    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", _runner([
        json.dumps({"type": "item.started", "item": {"type": item_type}}).encode() + b"\n",
    ], _outcome(), calls))

    with pytest.raises(ProviderUnavailableError, match="codex_cli_tool_call_blocked"):
        asyncio.run(_collect())

    assert calls


@pytest.mark.parametrize(
    "line",
    (
        b"not json\n",
        b'{"type":"item.completed","item":{"type":"todo_list"}}\n',
        b'{"type":"item.completed","item":{"type":"agent_message"}}\n',
        b'{"type":"turn.completed"}\n',
    ),
)
def test_codex_cli_rejects_malformed_and_unknown_stream_items(monkeypatch, line) -> None:
    calls: list = []
    monkeypatch.setattr(
        codex_cli_adapter, "run_cli_bounded", _runner([line], _outcome(), calls),
    )

    with pytest.raises(ProviderUnavailableError, match="codex_cli_stream_protocol_error"):
        asyncio.run(_collect())


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

    with pytest.raises(ProviderUnavailableError, match="codex_cli_stream_protocol_error"):
        asyncio.run(_collect())


@pytest.mark.parametrize(
    ("line", "outcome", "code"),
    (
        (
            b'{"type":"error","message":"Reconnecting after 401 Unauthorized"}\n',
            _outcome(),
            "cli_login_expired",
        ),
        (
            b'{"type":"turn.failed","error":{"message":"failed"}}\n',
            _outcome(stderr="unauthenticated"),
            "cli_login_expired",
        ),
        (b'{"type":"error","message":"internal diagnostic"}\n', _outcome(), "codex_cli_error"),
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

    with pytest.raises(ProviderUnavailableError, match=code):
        asyncio.run(_collect())

    assert "internal diagnostic" not in caplog.text
    assert "unauthenticated" not in caplog.text


@pytest.mark.parametrize(
    ("lines", "outcome", "code"),
    (
        ([], _outcome(complete=False, stderr="401"), "cli_login_expired"),
        ([], _outcome(complete=False), "codex_cli_error"),
        ([b'{"type":"turn.completed","usage":{}}\n'], _outcome(returncode=1), "codex_cli_error"),
        ([], _outcome(complete=False, reason=CliRunReason.OUTPUT_LIMIT_REACHED), "codex_cli_error"),
    ),
)
def test_codex_cli_classifies_runner_failures(monkeypatch, lines, outcome, code) -> None:
    calls: list = []
    monkeypatch.setattr(
        codex_cli_adapter, "run_cli_bounded", _runner(lines, outcome, calls),
    )

    with pytest.raises(ProviderUnavailableError, match=code):
        asyncio.run(_collect())


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
