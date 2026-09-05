"""Explicit co-writer transport dispatch."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from songmaker_cli.agent_cli import AgentCliUnavailableError
from songmaker_cli.claude.provider import (
    AssistantTextEvent,
    CliBinaryUnavailableError,
    CliToolSurfaceError,
    FinalEvent,
    StreamEvent,
    ToolCallEvent,
    ToolResultEvent,
    UnavailableError,
)
from songmaker_cli.cowriter import claude_adapter, dispatch, openai_adapter, tool_loop
from songmaker_cli.cowriter.catalog import ProviderRoute
from songmaker_cli.cowriter.errors import (
    ProviderUnavailableError,
    SafeRouteReasonCode,
    normalize_route_failure,
)
from songmaker_cli.cowriter.tool_loop import FinalText, TextDelta, ToolCall, ToolCallBatch
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Song, User, Version
from songmaker_cli.middleware import AuthenticatedUser


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


@pytest.mark.acceptance("ACC-COWRITER-09")
@pytest.mark.parametrize(
    ("provider", "transport_factory"),
    [
        ("grok", "GrokCliToolTransport"),
        ("codex", "CodexCliToolTransport"),
    ],
)
def test_cli_turn_uses_its_transport_through_the_shared_tool_loop(
    monkeypatch, provider, transport_factory,
):
    class Transport:
        closed = False

        def __init__(self):
            self.round = 0

        async def stream(self, _message):
            if self.round == 0:
                self.round += 1
                yield TextDelta("I will update it. ")
                yield ToolCallBatch((ToolCall(
                    "call-1", "update_song_lyrics", {"song_id": "own-song", "lyrics": "new"},
                ),))
                return
            yield FinalText("Done.")

        async def aclose(self):
            self.closed = True

    transport = Transport()
    monkeypatch.setattr(dispatch, transport_factory, lambda **_kwargs: transport)
    monkeypatch.setattr(
        dispatch,
        "stream_openai_compatible_turn",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("HTTP must not run")),
    )
    monkeypatch.setattr(
        "songmaker_cli.cowriter.tools.execute_cowriter_tool",
        lambda _session, _user, name, arguments: (
            "updated" if arguments["song_id"] == "own-song" else "Song not found", False,
        ),
    )

    events = asyncio.run(_events(provider, ProviderRoute.CLI))

    assert events == [
        AssistantTextEvent(text="I will update it. "),
        ToolCallEvent(
            tool_use_id="call-1", name="update_song_lyrics",
            input={"song_id": "own-song", "lyrics": "new"},
        ),
        ToolResultEvent(tool_use_id="call-1", content="updated", is_error=False),
        AssistantTextEvent(text="Done."),
        FinalEvent(text="I will update it. Done."),
    ]
    assert transport.closed


@pytest.mark.parametrize(
    ("provider", "transport_factory"),
    [
        ("grok", "GrokCliToolTransport"),
        ("codex", "CodexCliToolTransport"),
    ],
)
def test_cli_dispatch_names_a_text_protocol_error(monkeypatch, provider, transport_factory):
    class InvalidTransport:
        async def stream(self, _message):
            yield ToolCallBatch((ToolCall("call-1", "get_song", {"song_id": "s1"}),))
            yield FinalText()

        async def aclose(self):
            pass

    monkeypatch.setattr(dispatch, transport_factory, lambda **_kwargs: InvalidTransport())

    events = _events(provider, ProviderRoute.CLI)
    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(events)

    assert raised.value.reason.code is SafeRouteReasonCode.TOOL_PROTOCOL_ERROR


@pytest.mark.parametrize(
    ("provider", "transport_factory"),
    [
        ("grok", "GrokCliToolTransport"),
        ("codex", "CodexCliToolTransport"),
    ],
)
def test_cli_dispatch_executes_owned_calls_and_rejects_a_foreign_song(
    monkeypatch, tmp_path: Path, provider, transport_factory,
) -> None:
    factory = init_test_db(tmp_path / f"{provider}-dispatch.db")
    with factory() as session:
        session.add_all([
            User(id="owner", username="owner", password_hash="x", role="user"),
            User(id="other", username="other", password_hash="x", role="user"),
        ])
        session.flush()
        session.add_all([
            Album(id="owner-album", title="Owner", artist="Owner", created_by="owner"),
            Album(id="other-album", title="Other", artist="Other", created_by="other"),
            Song(id="owned-song", title="Owned", album_id="owner-album", track_number=1),
            Song(id="other-song", title="Other", album_id="other-album", track_number=1),
            Version(
                id="owned-version", song_id="owned-song", version_number=1,
                lyrics="old", prompt="rock", bpm=120, key_scale="Am", audio_duration=180,
            ),
            Version(
                id="other-version", song_id="other-song", version_number=1,
                lyrics="private", prompt="jazz", bpm=100, key_scale="C", audio_duration=180,
            ),
        ])
        session.commit()

    class Transport:
        def __init__(self) -> None:
            self.round = 0
            self.closed = False

        async def stream(self, _message):
            calls = (
                ToolCall("read-owned", "get_song", {"song_id": "owned-song"}),
                ToolCall(
                    "write-owned", "update_song_lyrics",
                    {"song_id": "owned-song", "lyrics": "new lyrics"},
                ),
                ToolCall(
                    "write-foreign",
                    "update_song_lyrics",
                    {"song_id": "other-song", "lyrics": "stolen lyrics"},
                ),
            )
            if self.round < len(calls):
                call = calls[self.round]
                self.round += 1
                yield ToolCallBatch((call,))
                return
            yield FinalText("done")

        async def aclose(self) -> None:
            self.closed = True

    transport = Transport()
    monkeypatch.setattr(dispatch, transport_factory, lambda **_kwargs: transport)
    user = AuthenticatedUser(id="owner", username="owner", role="user", is_active=True)

    async def collect():
        with factory() as session:
            return [
                event
                async for event in dispatch.stream_cowriter_turn(
                    provider=provider,
                    route=ProviderRoute.CLI,
                    model=f"{provider}-test",
                    user_id=user.id,
                    system="system",
                    messages=[],
                    session=session,
                    user=user,
                )
            ]

    events = asyncio.run(collect())

    results = [event for event in events if isinstance(event, ToolResultEvent)]
    assert [result.is_error for result in results] == [False, False, True]
    assert "Owned" in results[0].content
    assert "Updated lyrics" in results[1].content
    assert results[2].content == "Song not found"
    assert transport.closed
    with factory() as session:
        owned_versions = (
            session.query(Version)
            .filter_by(song_id="owned-song")
            .order_by(Version.version_number)
            .all()
        )
        assert [(version.version_number, version.lyrics) for version in owned_versions] == [
            (1, "old"),
            (2, "new lyrics"),
        ]
        assert session.get(Version, "other-version").lyrics == "private"


@pytest.mark.parametrize(
    ("provider", "transport_factory"),
    [
        ("grok", "GrokCliToolTransport"),
        ("codex", "CodexCliToolTransport"),
    ],
)
def test_closing_a_cli_turn_aborts_its_transport(monkeypatch, provider, transport_factory):
    class BlockingTransport:
        closed = False

        async def stream(self, _message):
            yield TextDelta("partial")
            await asyncio.Future()

        async def aclose(self):
            self.closed = True

    transport = BlockingTransport()
    monkeypatch.setattr(dispatch, transport_factory, lambda **_kwargs: transport)

    async def close_turn():
        turn = dispatch.stream_cowriter_turn(
            provider=provider,
            route=ProviderRoute.CLI,
            model="model",
            user_id="user",
            system="system",
            messages=[],
            session=MagicMock(),
            user=MagicMock(),
        )
        assert await anext(turn) == AssistantTextEvent(text="partial")
        await turn.aclose()

    asyncio.run(close_turn())

    assert transport.closed


def test_api_dispatch_uses_http_only_when_api_is_selected(monkeypatch):
    stream = _Stream()
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setattr(dispatch, "stream_openai_compatible_turn", lambda **_kwargs: stream)
    monkeypatch.setattr(
        dispatch,
        "GrokCliToolTransport",
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


def _assert_cli_failure_never_falls_back_to_http(
    monkeypatch, provider: str, transport_factory: str,
) -> None:
    class FailingTransport:
        async def stream(self, _message):
            raise ProviderUnavailableError(
                provider,
                "cli",
                normalize_route_failure(SafeRouteReasonCode.CLI_AUTH_REJECTED),
            )
            yield  # pragma: no cover

        async def aclose(self):
            pass

    monkeypatch.setattr(dispatch, transport_factory, lambda **_kwargs: FailingTransport())
    monkeypatch.setattr(
        dispatch,
        "stream_openai_compatible_turn",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("HTTP must not run")),
    )

    events = _events(provider, ProviderRoute.CLI)
    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(events)

    assert raised.value.reason.code is SafeRouteReasonCode.CLI_AUTH_REJECTED


@pytest.mark.acceptance("ACC-COWRITER-11")
def test_grok_cli_failure_never_falls_back_to_http(monkeypatch):
    _assert_cli_failure_never_falls_back_to_http(monkeypatch, "grok", "GrokCliToolTransport")


@pytest.mark.acceptance("ACC-COWRITER-13")
def test_codex_cli_failure_never_falls_back_to_http(monkeypatch):
    _assert_cli_failure_never_falls_back_to_http(monkeypatch, "codex", "CodexCliToolTransport")


def test_dispatch_preserves_the_adapter_named_reason(monkeypatch):
    async def failing_cli(**_kwargs):
        raise ProviderUnavailableError(
            "grok",
            "cli",
            normalize_route_failure(SafeRouteReasonCode.CLI_AUTH_REJECTED),
        )
        yield AssistantTextEvent(text="unreachable")

    class FailingTransport:
        async def stream(self, _message):
            raise ProviderUnavailableError(
                "grok",
                "cli",
                normalize_route_failure(SafeRouteReasonCode.CLI_AUTH_REJECTED),
            )
            yield  # pragma: no cover

        async def aclose(self):
            pass

    monkeypatch.setattr(dispatch, "GrokCliToolTransport", lambda **_kwargs: FailingTransport())

    events = _events("grok", ProviderRoute.CLI)
    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(events)

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

    collection = collect()
    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(collection)

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

    client = Client()
    request = openai_adapter._post_chat(
        client, "grok", "https://provider.example/chat", "key", "model", [], [],
    )
    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(request)

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

    monkeypatch.setattr(tool_loop, "COWRITER_MAX_TOOL_ROUNDS", 0)
    collection = collect()
    with pytest.raises(ProviderUnavailableError) as limited:
        asyncio.run(collection)
    assert limited.value.reason.code is SafeRouteReasonCode.TOOL_LIMIT_EXCEEDED

    monkeypatch.setattr(tool_loop, "COWRITER_MAX_TOOL_ROUNDS", 1)
    responses = [
        {"choices": [{"message": {"content": "", "tool_calls": [tool_call]}}]},
        {"choices": [{"message": {"content": "done"}}]},
    ]
    monkeypatch.setattr(
        openai_adapter,
        "_post_chat",
        lambda *_args, **_kwargs: _next_response(responses),
    )
    monkeypatch.setattr(
        "songmaker_cli.cowriter.tools.execute_cowriter_tool",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("tool exploded")),
    )
    events = asyncio.run(collect())
    result = next(event for event in events if event.type == "tool_result")
    assert result.is_error is True
    assert result.content == "Co-Writer tool failed."


async def _next_response(responses):
    return responses.pop(0)


def test_claude_api_dispatches_only_to_the_native_tool_adapter(monkeypatch):
    stream = _Stream()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(dispatch, "stream_claude_api_turn", lambda **_kwargs: stream)
    monkeypatch.setattr(
        dispatch,
        "stream_openai_compatible_turn",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("HTTP must not run")),
    )

    assert asyncio.run(_events("claude", ProviderRoute.API)) == [AssistantTextEvent(text="route")]
    assert stream.closed


def test_claude_api_missing_key_names_the_selected_route_without_an_adapter_attempt(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        dispatch,
        "stream_claude_api_turn",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("adapter must not run")),
    )

    events = _events("claude", ProviderRoute.API)
    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(events)

    assert raised.value.reason.code is SafeRouteReasonCode.API_KEY_NOT_SET
