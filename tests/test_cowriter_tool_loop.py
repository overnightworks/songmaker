"""Contract tests for the transport-independent co-writer tool loop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from songmaker_cli.claude.provider import (
    AssistantTextEvent,
    FinalEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from songmaker_cli.cowriter import tool_loop
from songmaker_cli.cowriter.tool_loop import (
    FinalText,
    InitialTurn,
    TextDelta,
    ToolCall,
    ToolCallBatch,
    ToolLoopLimitError,
    ToolResultBatch,
    TransportResponse,
    stream_tool_loop,
)


class _FakeTransport:
    def __init__(self, responses: list[list[TransportResponse]]) -> None:
        self._responses = responses
        self.messages: list[InitialTurn | ToolResultBatch] = []
        self.closed = False

    async def stream(
        self, message: InitialTurn | ToolResultBatch,
    ) -> AsyncIterator[TransportResponse]:
        self.messages.append(message)
        for response in self._responses.pop(0):
            yield response

    async def aclose(self) -> None:
        self.closed = True


async def _events(
    transport: _FakeTransport,
    executor,
) -> list[object]:
    return [
        event
        async for event in stream_tool_loop(
            provider="grok",
            route="api",
            system="system",
            messages=[{"role": "user", "content": "hello"}],
            transport=transport,
            executor=executor,
        )
    ]


def test_passes_the_complete_tool_result_batch_to_the_transport() -> None:
    first = ToolCallBatch((
        ToolCall("call-1", "first", {"position": 1}),
        ToolCall("call-2", "second", {"position": 2}),
    ))
    transport = _FakeTransport([[TextDelta("draft "), first], [FinalText("done")]])

    events = asyncio.run(_events(
        transport,
        lambda name, arguments: (f"{name}:{arguments['position']}", False),
    ))

    assert transport.messages == [
        InitialTurn("system", [{"role": "user", "content": "hello"}]),
        ToolResultBatch((
            tool_loop.ToolResult("call-1", "first:1", False),
            tool_loop.ToolResult("call-2", "second:2", False),
        )),
    ]
    assert events == [
        AssistantTextEvent(text="draft "),
        ToolCallEvent(tool_use_id="call-1", name="first", input={"position": 1}),
        ToolResultEvent(tool_use_id="call-1", content="first:1", is_error=False),
        ToolCallEvent(tool_use_id="call-2", name="second", input={"position": 2}),
        ToolResultEvent(tool_use_id="call-2", content="second:2", is_error=False),
        AssistantTextEvent(text="done"),
        FinalEvent(text="draft done"),
    ]
    assert transport.closed


def test_allows_eight_tool_rounds_then_one_final_response() -> None:
    calls = [
        [ToolCallBatch((ToolCall(f"call-{index}", "read", {}),))]
        for index in range(tool_loop.COWRITER_MAX_TOOL_ROUNDS)
    ]
    transport = _FakeTransport([*calls, [FinalText("complete")]])

    events = asyncio.run(_events(transport, lambda _name, _arguments: ("ok", False)))

    assert sum(isinstance(event, ToolCallEvent) for event in events) == 8
    assert events[-1] == FinalEvent(text="complete")


def test_rejects_a_ninth_tool_round_without_executing_it(monkeypatch) -> None:
    monkeypatch.setattr(tool_loop, "COWRITER_MAX_TOOL_ROUNDS", 0)
    transport = _FakeTransport([[
        ToolCallBatch((ToolCall("call-9", "read", {}),)),
    ]])
    executed = False

    def executor(_name: str, _arguments: dict[str, Any]) -> tuple[str, bool]:
        nonlocal executed
        executed = True
        return "unreachable", False

    events = _events(transport, executor)
    with pytest.raises(ToolLoopLimitError):
        asyncio.run(events)

    assert not executed
    assert transport.closed


def test_executor_failure_returns_a_named_error_to_the_model() -> None:
    transport = _FakeTransport([
        [ToolCallBatch((ToolCall("call-1", "write", {"lyrics": "secret"}),))],
        [FinalText()],
    ])

    def executor(_name: str, _arguments: dict[str, Any]) -> tuple[str, bool]:
        raise RuntimeError("secret")

    events = asyncio.run(_events(transport, executor))

    assert events == [
        ToolCallEvent(tool_use_id="call-1", name="write", input={"lyrics": "secret"}),
        ToolResultEvent(
            tool_use_id="call-1", content="Co-Writer tool failed.", is_error=True,
        ),
        FinalEvent(text=""),
    ]
    assert transport.messages[1] == ToolResultBatch((
        tool_loop.ToolResult("call-1", "Co-Writer tool failed.", True),
    ))


def test_aclose_stops_the_active_transport_without_a_follow_up_round() -> None:
    class BlockingTransport(_FakeTransport):
        async def stream(
            self, message: InitialTurn | ToolResultBatch,
        ) -> AsyncIterator[TransportResponse]:
            self.messages.append(message)
            yield TextDelta("partial")
            await asyncio.Future()

    transport = BlockingTransport([])

    async def close_after_first_delta() -> None:
        turn = stream_tool_loop(
            provider="grok",
            route="cli",
            system="system",
            messages=[],
            transport=transport,
            executor=lambda _name, _arguments: ("unused", False),
        )
        assert await anext(turn) == AssistantTextEvent(text="partial")
        await turn.aclose()

    asyncio.run(close_after_first_delta())

    assert transport.closed
    assert len(transport.messages) == 1


def test_logs_never_include_tool_input_or_result(caplog) -> None:
    lyrics = "private lyrics"
    song_id = "song-private"
    call_json = '{"lyrics":"private lyrics","song_id":"song-private"}'
    transport = _FakeTransport([
        [ToolCallBatch((ToolCall("safe-call", "update_song_lyrics", {
            "lyrics": lyrics,
            "song_id": song_id,
        }),))],
        [FinalText()],
    ])
    caplog.set_level("INFO", logger="songmaker_cli.cowriter.tool_loop")

    asyncio.run(_events(transport, lambda _name, _arguments: (call_json, True)))

    assert "provider=grok" in caplog.text
    assert "route=api" in caplog.text
    assert "tool=update_song_lyrics" in caplog.text
    for forbidden in (lyrics, song_id, call_json):
        assert forbidden not in caplog.text
