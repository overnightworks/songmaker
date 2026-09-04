"""Explicit co-writer transport dispatch."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import httpx
import pytest

from songmaker_cli.agent_cli import AgentCliUnavailableError
from songmaker_cli.claude.provider import (
    AssistantTextEvent,
    CliBinaryUnavailableError,
    CliToolSurfaceError,
    StreamEvent,
    UnavailableError,
)
from songmaker_cli.cowriter import claude_adapter, dispatch, openai_adapter
from songmaker_cli.cowriter.catalog import ProviderRoute
from songmaker_cli.cowriter.errors import (
    ProviderUnavailableError,
    SafeRouteReasonCode,
    normalize_route_failure,
)


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


def test_codex_cover_route_reports_an_unavailable_cli_probe(monkeypatch) -> None:
    monkeypatch.setattr(
        dispatch,
        "codex_cli_access_token_is_present",
        lambda: (_ for _ in ()).throw(AgentCliUnavailableError("unreadable mirror")),
    )

    with pytest.raises(ProviderUnavailableError) as raised:
        dispatch.cover_image_provider_method()

    assert raised.value.reason.code is SafeRouteReasonCode.CLI_BINARY_UNAVAILABLE


def _assert_cli_failure_never_falls_back_to_http(monkeypatch, provider: str, adapter: str) -> None:
    async def failing_cli(**_kwargs):
        raise ProviderUnavailableError(
            provider,
            "cli",
            normalize_route_failure(SafeRouteReasonCode.CLI_AUTH_REJECTED),
        )
        yield AssistantTextEvent(text="unreachable")

    monkeypatch.setattr(dispatch, adapter, failing_cli)
    monkeypatch.setattr(
        dispatch,
        "stream_openai_compatible_turn",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("HTTP must not run")),
    )

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(_events(provider, ProviderRoute.CLI))

    assert raised.value.reason.code is SafeRouteReasonCode.CLI_AUTH_REJECTED


@pytest.mark.acceptance("ACC-COWRITER-11")
def test_grok_cli_failure_never_falls_back_to_http(monkeypatch):
    _assert_cli_failure_never_falls_back_to_http(monkeypatch, "grok", "stream_grok_cli_turn")


@pytest.mark.acceptance("ACC-COWRITER-13")
def test_codex_cli_failure_never_falls_back_to_http(monkeypatch):
    _assert_cli_failure_never_falls_back_to_http(monkeypatch, "codex", "stream_codex_cli_turn")


def test_dispatch_preserves_the_adapter_named_reason(monkeypatch):
    async def failing_cli(**_kwargs):
        raise ProviderUnavailableError(
            "grok",
            "cli",
            normalize_route_failure(SafeRouteReasonCode.CLI_AUTH_REJECTED),
        )
        yield AssistantTextEvent(text="unreachable")

    monkeypatch.setattr(dispatch, "stream_grok_cli_turn", failing_cli)

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(_events("grok", ProviderRoute.CLI))

    assert raised.value.reason.code is SafeRouteReasonCode.CLI_AUTH_REJECTED


@pytest.mark.parametrize(
    ("source_error", "reason"),
    [
        (CliBinaryUnavailableError("missing binary"), SafeRouteReasonCode.CLI_BINARY_UNAVAILABLE),
        (CliToolSurfaceError("unexpected tool"), SafeRouteReasonCode.TOOL_EXECUTION_FAILED),
        (UnavailableError("invalid stream"), SafeRouteReasonCode.CLI_PROTOCOL_ERROR),
    ],
)
def test_claude_adapter_maps_typed_cli_failure_sources(monkeypatch, source_error, reason):
    async def failing_stream(**_kwargs):
        raise source_error
        yield AssistantTextEvent(text="unreachable")

    monkeypatch.setattr(claude_adapter, "acall_claude_with_mcp_stream", failing_stream)

    async def collect():
        return [
            event async for event in claude_adapter.stream_claude_turn(
                user_id="user", system="system", model="model", messages=[],
            )
        ]

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(collect())

    assert raised.value.reason.code is reason


class _AsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


@pytest.mark.parametrize(
    ("post", "reason"),
    [
        (
            lambda: (_ for _ in ()).throw(httpx.ConnectError("offline")),
            SafeRouteReasonCode.API_HTTP_ERROR,
        ),
        (
            lambda: MagicMock(status_code=200, json=lambda: []),
            SafeRouteReasonCode.API_PROTOCOL_ERROR,
        ),
    ],
)
def test_openai_adapter_maps_http_and_protocol_sources(post, reason):
    class Client:
        async def post(self, *_args, **_kwargs):
            return post()

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(
            openai_adapter._post_chat(
                Client(), "grok", "https://provider.example/chat", "key", "model", [], [],
            ),
        )

    assert raised.value.reason.code is reason


def test_openai_adapter_maps_tool_limit_and_execution_sources(monkeypatch):
    tool_call = {
        "id": "call-1",
        "function": {"name": "list_albums", "arguments": "{}"},
    }

    async def tool_response(*_args, **_kwargs):
        return {"choices": [{"message": {"content": "", "tool_calls": [tool_call]}}]}

    monkeypatch.setattr(openai_adapter, "_post_chat", tool_response)
    monkeypatch.setattr(openai_adapter.httpx, "AsyncClient", lambda **_kwargs: _AsyncClient())

    async def collect():
        return [
            event async for event in openai_adapter.stream_openai_compatible_turn(
                provider="grok",
                api_url="https://provider.example/chat",
                api_key="key",
                model="model",
                system="system",
                messages=[],
                session=MagicMock(),
                user=MagicMock(),
            )
        ]

    monkeypatch.setattr(openai_adapter, "COWRITER_MAX_TOOL_ROUNDS", 0)
    with pytest.raises(ProviderUnavailableError) as limited:
        asyncio.run(collect())
    assert limited.value.reason.code is SafeRouteReasonCode.TOOL_LIMIT_EXCEEDED

    monkeypatch.setattr(openai_adapter, "COWRITER_MAX_TOOL_ROUNDS", 1)
    monkeypatch.setattr(
        "songmaker_cli.cowriter.tools.execute_cowriter_tool",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("tool exploded")),
    )
    with pytest.raises(ProviderUnavailableError) as failed:
        asyncio.run(collect())
    assert failed.value.reason.code is SafeRouteReasonCode.TOOL_EXECUTION_FAILED


def test_claude_api_is_the_pending_route_without_an_adapter_attempt(monkeypatch):
    monkeypatch.setattr(
        dispatch,
        "stream_openai_compatible_turn",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("HTTP must not run")),
    )

    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(_events("claude", ProviderRoute.API))

    assert raised.value.reason.code is SafeRouteReasonCode.CLAUDE_API_TOOL_LOOP_PENDING
