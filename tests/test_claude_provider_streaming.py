"""Tests for the streaming Claude provider path."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from songmaker_cli.claude import provider
from songmaker_cli.claude.provider import (
    AssistantTextEvent,
    ErrorEvent,
    FinalEvent,
    StreamEvent,
    ToolCallEvent,
    ToolResultEvent,
    UnavailableError,
    _parse_stream_event,
    _safe_json_loads,
    acall_claude_with_mcp_stream,
)


class FakeStreamReader:
    """Minimal stand-in for asyncio.StreamReader.readline()."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)

    async def read(self) -> bytes:
        out = b"".join(self._lines)
        self._lines = []
        return out


def _make_fake_proc(
    stdout_lines: list[bytes],
    *,
    returncode: int = 0,
    stderr_bytes: bytes = b"",
) -> Any:
    proc = MagicMock()
    proc.stdout = FakeStreamReader(stdout_lines)
    proc.stderr = FakeStreamReader([stderr_bytes] if stderr_bytes else [])
    proc.returncode = returncode

    async def _wait() -> None:
        return None

    proc.wait = _wait
    proc.kill = MagicMock()
    return proc


def _assistant_line(text: str) -> bytes:
    return json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": text}]},
    }).encode() + b"\n"


def _tool_use_line(name: str, use_id: str, inp: dict) -> bytes:
    return json.dumps({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use", "id": use_id, "name": name, "input": inp,
        }]},
    }).encode() + b"\n"


def _tool_result_line(use_id: str, content: str) -> bytes:
    return json.dumps({
        "type": "user",
        "message": {"content": [{
            "type": "tool_result",
            "tool_use_id": use_id,
            "content": [{"type": "text", "text": content}],
        }]},
    }).encode() + b"\n"


def _result_line(text: str) -> bytes:
    return json.dumps({
        "type": "result", "subtype": "success", "result": text,
    }).encode() + b"\n"


async def _collect(agen) -> list[StreamEvent]:
    out: list[StreamEvent] = []
    async for ev in agen:
        out.append(ev)
    return out


# ── _safe_json_loads ──────────────────────────────────────────────────


def test_safe_json_loads_blank_line_returns_none() -> None:
    assert _safe_json_loads(b"   \n") is None


def test_safe_json_loads_valid_object() -> None:
    assert _safe_json_loads(b'{"a": 1}') == {"a": 1}


def test_safe_json_loads_malformed_skipped(caplog) -> None:
    caplog.set_level("WARNING")
    assert _safe_json_loads(b"not-json\n") is None
    assert any("malformed" in r.message.lower() for r in caplog.records)


def test_safe_json_loads_non_object_skipped(caplog) -> None:
    caplog.set_level("WARNING")
    assert _safe_json_loads(b"42") is None
    assert any("non-object" in r.message.lower() for r in caplog.records)


# ── _parse_stream_event ──────────────────────────────────────────────


def test_parse_assistant_text_event() -> None:
    chunks: list[str] = []
    ev = _parse_stream_event({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "hello"}]},
    }, chunks)
    assert isinstance(ev, AssistantTextEvent)
    assert ev.text == "hello"
    assert chunks == ["hello"]


def test_parse_assistant_tool_use_event() -> None:
    chunks: list[str] = []
    ev = _parse_stream_event({
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use", "id": "tu-1", "name": "foo", "input": {"x": 1},
        }]},
    }, chunks)
    assert isinstance(ev, ToolCallEvent)
    assert ev.tool_use_id == "tu-1"
    assert ev.name == "foo"
    assert ev.input == {"x": 1}


def test_parse_user_tool_result_event() -> None:
    ev = _parse_stream_event({
        "type": "user",
        "message": {"content": [{
            "type": "tool_result",
            "tool_use_id": "tu-1",
            "content": [{"type": "text", "text": "ok"}],
            "is_error": False,
        }]},
    }, [])
    assert isinstance(ev, ToolResultEvent)
    assert ev.tool_use_id == "tu-1"
    assert ev.content == "ok"
    assert ev.is_error is False


def test_parse_user_tool_result_string_content() -> None:
    ev = _parse_stream_event({
        "type": "user",
        "message": {"content": [{
            "type": "tool_result",
            "tool_use_id": "tu-1",
            "content": "plain",
        }]},
    }, [])
    assert isinstance(ev, ToolResultEvent)
    assert ev.content == "plain"


def test_parse_user_tool_result_missing_content() -> None:
    ev = _parse_stream_event({
        "type": "user",
        "message": {"content": [{
            "type": "tool_result", "tool_use_id": "tu-1",
        }]},
    }, [])
    assert isinstance(ev, ToolResultEvent)
    assert ev.content == ""


def test_parse_result_event_returns_final() -> None:
    ev = _parse_stream_event(
        {"type": "result", "result": "done"}, [],
    )
    assert isinstance(ev, FinalEvent)
    assert ev.text == "done"


def test_parse_result_event_without_text_returns_none() -> None:
    assert _parse_stream_event({"type": "result"}, []) is None


def test_parse_assistant_empty_content_returns_none() -> None:
    assert _parse_stream_event(
        {"type": "assistant", "message": {"content": []}}, [],
    ) is None


def test_parse_user_empty_content_returns_none() -> None:
    assert _parse_stream_event(
        {"type": "user", "message": {"content": []}}, [],
    ) is None


def test_parse_unknown_type_ignored() -> None:
    assert _parse_stream_event({"type": "system"}, []) is None


# ── acall_claude_with_mcp_stream integration ─────────────────────────


def test_stream_yields_ordered_events(monkeypatch) -> None:
    monkeypatch.setattr(
        provider, "_require_claude_binary", lambda: "/bin/claude",
    )

    lines = [
        _assistant_line("Hi, "),
        _tool_use_line("mcp__songmaker__get_song", "tu-1", {"song_id": "s1"}),
        _tool_result_line("tu-1", "song data"),
        _assistant_line("done."),
        _result_line("Hi, done."),
    ]

    async def fake_exec(*_cmd, **_kw):
        return _make_fake_proc(lines)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    events = asyncio.run(_collect(
        acall_claude_with_mcp_stream(prompt="hi", user_id="u"),
    ))
    kinds = [e.type for e in events]
    assert kinds == [
        "assistant_text", "tool_call", "tool_result",
        "assistant_text", "final",
    ]
    assert isinstance(events[-1], FinalEvent)
    assert events[-1].text == "Hi, done."


def test_stream_skips_malformed_lines(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        provider, "_require_claude_binary", lambda: "/bin/claude",
    )
    caplog.set_level("WARNING")

    lines = [
        b"not-json-at-all\n",
        _assistant_line("hello"),
        _result_line("hello"),
    ]

    async def fake_exec(*_cmd, **_kw):
        return _make_fake_proc(lines)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    events = asyncio.run(_collect(
        acall_claude_with_mcp_stream(prompt="hi", user_id="u"),
    ))
    assert [e.type for e in events] == ["assistant_text", "final"]
    assert any("malformed" in r.message.lower() for r in caplog.records)


def test_stream_regression_matches_non_streaming_final_text(monkeypatch) -> None:
    """Final event must equal result.result, matching non-streaming json path."""
    monkeypatch.setattr(
        provider, "_require_claude_binary", lambda: "/bin/claude",
    )
    expected = "The quick brown fox"
    lines = [
        _assistant_line("The quick "),
        _assistant_line("brown fox"),
        _result_line(expected),
    ]

    async def fake_exec(*_cmd, **_kw):
        return _make_fake_proc(lines)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    events = asyncio.run(_collect(
        acall_claude_with_mcp_stream(prompt="hi", user_id="u"),
    ))
    final = [e for e in events if isinstance(e, FinalEvent)]
    assert len(final) == 1
    assert final[0].text == expected


def test_stream_falls_back_to_assembled_text_when_no_result(monkeypatch) -> None:
    monkeypatch.setattr(
        provider, "_require_claude_binary", lambda: "/bin/claude",
    )
    lines = [
        _assistant_line("piece one "),
        _assistant_line("piece two"),
    ]

    async def fake_exec(*_cmd, **_kw):
        return _make_fake_proc(lines)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    events = asyncio.run(_collect(
        acall_claude_with_mcp_stream(prompt="hi", user_id="u"),
    ))
    final = [e for e in events if isinstance(e, FinalEvent)][0]
    assert final.text == "piece one piece two"


def test_stream_nonzero_exit_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        provider, "_require_claude_binary", lambda: "/bin/claude",
    )

    async def fake_exec(*_cmd, **_kw):
        return _make_fake_proc([], returncode=2, stderr_bytes=b"boom")

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    with pytest.raises(UnavailableError):
        asyncio.run(_collect(
            acall_claude_with_mcp_stream(prompt="hi", user_id="u"),
        ))


def test_stream_binary_missing_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        provider, "_require_claude_binary", lambda: "/bin/claude",
    )

    async def fake_exec(*_cmd, **_kw):
        raise FileNotFoundError()

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    with pytest.raises(UnavailableError):
        asyncio.run(_collect(
            acall_claude_with_mcp_stream(prompt="hi", user_id="u"),
        ))


def test_stream_timeout_kills_subprocess(monkeypatch) -> None:
    monkeypatch.setattr(
        provider, "_require_claude_binary", lambda: "/bin/claude",
    )

    killed = {"value": False}

    class StallingReader(FakeStreamReader):
        async def readline(self) -> bytes:
            await asyncio.sleep(10)
            return b""

    async def fake_exec(*_cmd, **_kw):
        proc = MagicMock()
        proc.stdout = StallingReader([])
        proc.stderr = FakeStreamReader([])
        proc.returncode = 0

        def _kill() -> None:
            killed["value"] = True

        proc.kill = _kill

        async def _wait() -> None:
            return None

        proc.wait = _wait
        return proc

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    with pytest.raises(UnavailableError):
        asyncio.run(_collect(
            acall_claude_with_mcp_stream(
                prompt="hi", user_id="u", timeout_seconds=0.1,
            ),
        ))
    assert killed["value"] is True


def test_stream_cmd_uses_stream_json_and_verbose() -> None:
    from songmaker_cli.claude.provider import _build_mcp_cli_cmd

    cmd = _build_mcp_cli_cmd(
        "claude", "prompt", None, "opus", "u", stream=True,
    )
    assert "--output-format" in cmd
    idx = cmd.index("--output-format")
    assert cmd[idx + 1] == "stream-json"
    assert "--verbose" in cmd


def test_stream_cmd_non_stream_keeps_json() -> None:
    from songmaker_cli.claude.provider import _build_mcp_cli_cmd

    cmd = _build_mcp_cli_cmd("claude", "prompt", None, "opus", "u")
    idx = cmd.index("--output-format")
    assert cmd[idx + 1] == "json"
    assert "--verbose" not in cmd


def test_error_event_model() -> None:
    ev = ErrorEvent(message="oops")
    assert ev.type == "error"
    assert ev.message == "oops"


def test_iter_lines_returns_immediately_when_stdout_missing() -> None:
    from songmaker_cli.claude.provider import _iter_lines

    async def _run() -> list[bytes]:
        out: list[bytes] = []
        async for line in _iter_lines(None, 1):
            out.append(line)
        return out

    assert asyncio.run(_run()) == []


def test_stream_passes_buffer_limit_above_asyncio_default(monkeypatch) -> None:
    monkeypatch.setattr(
        provider, "_require_claude_binary", lambda: "/bin/claude",
    )

    captured: dict[str, Any] = {}

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _make_fake_proc([_result_line("ok")])

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    asyncio.run(_collect(
        acall_claude_with_mcp_stream(prompt="hi", user_id="u"),
    ))

    assert "limit" in captured["kwargs"]
    assert captured["kwargs"]["limit"] == provider._STREAM_BUFFER_LIMIT
    assert captured["kwargs"]["limit"] > 64 * 1024


def test_stream_consumes_oversized_tool_result_line(monkeypatch) -> None:
    monkeypatch.setattr(
        provider, "_require_claude_binary", lambda: "/bin/claude",
    )

    huge_payload = "x" * (256 * 1024)
    lines = [
        _tool_use_line("mcp__songmaker__get_song", "tu-1", {"song_id": "s1"}),
        _tool_result_line("tu-1", huge_payload),
        _result_line("done"),
    ]

    async def fake_exec(*_cmd, **_kw):
        return _make_fake_proc(lines)

    monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)

    events = asyncio.run(_collect(
        acall_claude_with_mcp_stream(prompt="hi", user_id="u"),
    ))
    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert len(tool_results) == 1
    assert tool_results[0].content == huge_payload
    assert isinstance(events[-1], FinalEvent)
