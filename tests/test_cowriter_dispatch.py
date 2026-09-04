"""Explicit co-writer transport dispatch."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest

from songmaker_cli.claude.provider import AssistantTextEvent, StreamEvent
from songmaker_cli.cowriter import dispatch
from songmaker_cli.cowriter.catalog import ProviderRoute
from songmaker_cli.cowriter.errors import ProviderUnavailableError, SafeRouteReasonCode


class _Stream(AsyncIterator[StreamEvent]):
    def __init__(self) -> None:
        self.closed = False
        self.sent = False

    def __aiter__(self) -> _Stream:
        return self

    async def __anext__(self) -> StreamEvent:
        if self.sent:
            raise StopAsyncIteration
        self.sent = True
        return AssistantTextEvent(text="route")

    async def aclose(self) -> None:
        self.closed = True


async def _events(provider: str, route: ProviderRoute) -> list[StreamEvent]:
    return [
        event async for event in dispatch.stream_cowriter_turn(
            provider=provider,
            route=route,
            model="model",
            user_id="user",
            system="system",
            messages=[],
            session=MagicMock(),
            user=MagicMock(),
        )
    ]


@pytest.mark.parametrize(
    ("provider", "route", "adapter"),
    [
        ("claude", ProviderRoute.CLI, "stream_claude_turn"),
        ("grok", ProviderRoute.CLI, "stream_grok_cli_turn"),
        ("codex", ProviderRoute.CLI, "stream_codex_cli_turn"),
    ],
)
def test_cli_dispatch_uses_only_the_explicit_provider_adapter(
    monkeypatch,
    provider,
    route,
    adapter,
):
    stream = _Stream()
    monkeypatch.setattr(dispatch, adapter, lambda **_kwargs: stream)
    monkeypatch.setattr(
        dispatch,
        "stream_openai_compatible_turn",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("HTTP must not run")),
    )

    assert asyncio.run(_events(provider, route)) == [AssistantTextEvent(text="route")]
    assert stream.closed


def test_api_dispatch_uses_http_only_when_api_is_selected(monkeypatch):
    stream = _Stream()
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setattr(dispatch, "stream_openai_compatible_turn", lambda **_kwargs: stream)
    monkeypatch.setattr(
        dispatch,
        "stream_grok_cli_turn",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("CLI must not run")),
    )

    assert asyncio.run(_events("grok", ProviderRoute.API)) == [AssistantTextEvent(text="route")]


def test_cli_failure_never_falls_back_to_http(monkeypatch):
    async def failing_cli(**_kwargs):
        raise ProviderUnavailableError("grok", "raw CLI output")
        yield AssistantTextEvent(text="unreachable")

    monkeypatch.setattr(dispatch, "stream_grok_cli_turn", failing_cli)
    monkeypatch.setattr(
        dispatch,
        "stream_openai_compatible_turn",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("HTTP must not run")),
    )

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(_events("grok", ProviderRoute.CLI))

    assert raised.value.reason.code is SafeRouteReasonCode.ROUTE_FAILED


def test_claude_api_is_the_pending_route_without_an_adapter_attempt(monkeypatch):
    monkeypatch.setattr(
        dispatch,
        "stream_openai_compatible_turn",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("HTTP must not run")),
    )

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(_events("claude", ProviderRoute.API))

    assert raised.value.reason.code is SafeRouteReasonCode.CLAUDE_API_TOOL_LOOP_PENDING
