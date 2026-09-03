"""Cancellation behavior of the Claude co-writer adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from songmaker_cli.claude.provider import AssistantTextEvent, StreamEvent
from songmaker_cli.cowriter import claude_adapter


class _TrackingProviderStream(AsyncIterator[StreamEvent]):
    def __init__(self) -> None:
        self.aclose_calls = 0
        self._has_yielded = False

    def __aiter__(self) -> _TrackingProviderStream:
        return self

    async def __anext__(self) -> StreamEvent:
        if not self._has_yielded:
            self._has_yielded = True
            return AssistantTextEvent(text="partial")
        await asyncio.Future()

    async def aclose(self) -> None:
        self.aclose_calls += 1


def test_closing_claude_adapter_stream_closes_provider_stream(monkeypatch) -> None:
    provider_stream = _TrackingProviderStream()
    monkeypatch.setattr(
        claude_adapter,
        "acall_claude_with_mcp_stream",
        lambda **_kwargs: provider_stream,
    )

    async def _close_stream() -> None:
        stream = claude_adapter.stream_claude_turn(
            user_id="user-1",
            system="system",
            model="claude-test",
            messages=[],
        )
        assert await anext(stream) == AssistantTextEvent(text="partial")
        await stream.aclose()

    asyncio.run(_close_stream())

    assert provider_stream.aclose_calls == 1
