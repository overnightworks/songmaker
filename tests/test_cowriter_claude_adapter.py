"""Claude API co-writer tool-loop behavior."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from songmaker_cli.claude.provider import (
    AssistantTextEvent,
    FinalEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from songmaker_cli.cowriter import claude_adapter, tool_loop
from songmaker_cli.cowriter.errors import ProviderUnavailableError, SafeRouteReasonCode
from songmaker_cli.cowriter.tools import COWRITER_TOOLS, anthropic_tool_schemas
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Song, User
from songmaker_cli.middleware import AuthenticatedUser


@dataclass
class _TextBlock:
    text: str
    type: str = "text"


@dataclass
class _ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass
class _AssistantMessage:
    content: list[object]


class _FakeStream:
    def __init__(self, text: list[str], message: _AssistantMessage) -> None:
        self._text = text
        self._message = message
        self.closed = False

    async def __aenter__(self) -> _FakeStream:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        self.closed = True
        return False

    @property
    def text_stream(self):
        return self._texts()

    async def _texts(self):
        for text in self._text:
            yield text

    async def get_final_message(self) -> _AssistantMessage:
        return self._message


class _BlockingFakeStream(_FakeStream):
    async def _texts(self):
        yield "partial"
        await asyncio.Future()


class _FailingFakeStream(_FakeStream):
    async def _texts(self):
        raise _ApiError()
        yield "unreachable"


class _FinalMessageFailingStream(_FakeStream):
    async def get_final_message(self) -> _AssistantMessage:
        raise RuntimeError("invalid SDK message")


class _FakeMessages:
    def __init__(self, streams: list[_FakeStream]) -> None:
        self._streams = streams
        self.requests: list[dict[str, object]] = []

    def stream(self, **kwargs: object) -> _FakeStream:
        self.requests.append(kwargs)
        return self._streams.pop(0)


class _FakeClient:
    def __init__(self, streams: list[_FakeStream]) -> None:
        self.messages = _FakeMessages(streams)
        self.closed = False

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        self.closed = True
        return False


class _ApiError(Exception):
    pass


def _install_anthropic(monkeypatch, client: _FakeClient) -> list[dict[str, object]]:
    constructions: list[dict[str, object]] = []

    class AsyncAnthropic:
        def __init__(self, **kwargs: object) -> None:
            constructions.append(kwargs)

        async def __aenter__(self) -> _FakeClient:
            return await client.__aenter__()

        async def __aexit__(self, *args: object) -> bool:
            return await client.__aexit__(*args)

    monkeypatch.setitem(
        sys.modules,
        "anthropic",
        SimpleNamespace(AsyncAnthropic=AsyncAnthropic, APIError=_ApiError),
    )
    return constructions


async def _events(**kwargs: object) -> list[object]:
    return [event async for event in claude_adapter.stream_claude_api_turn(**kwargs)]


def _turn_arguments(
    session: object | None = None,
    user: AuthenticatedUser | None = None,
) -> dict[str, object]:
    return {
        "api_key": "test-key",
        "system": "system",
        "model": "claude-test",
        "messages": [{"role": "user", "content": "hello"}],
        "session": session or MagicMock(),
        "user": user or AuthenticatedUser(id="u", username="u", role="user", is_active=True),
    }


def test_anthropic_schemas_derive_from_the_shared_tool_catalog() -> None:
    schemas = anthropic_tool_schemas()

    assert [schema["name"] for schema in schemas] == [tool.name for tool in COWRITER_TOOLS]
    assert [schema["input_schema"] for schema in schemas] == [
        tool.parameters for tool in COWRITER_TOOLS
    ]


def test_claude_api_streams_deltas_and_carries_tool_errors_back_to_the_model(monkeypatch) -> None:
    first = _FakeStream(
        ["draft"],
        _AssistantMessage([
            _TextBlock("draft"),
            _ToolUseBlock("call-1", "get_song", {"song_id": "s1"}),
        ]),
    )
    second = _FakeStream(["done"], _AssistantMessage([_TextBlock("done")]))
    client = _FakeClient([first, second])
    constructions = _install_anthropic(monkeypatch, client)
    execute = MagicMock(return_value=("not yours", True))
    monkeypatch.setattr("songmaker_cli.cowriter.tools.execute_cowriter_tool", execute)

    events = asyncio.run(_events(**_turn_arguments()))

    assert events == [
        AssistantTextEvent(text="draft"),
        ToolCallEvent(tool_use_id="call-1", name="get_song", input={"song_id": "s1"}),
        ToolResultEvent(tool_use_id="call-1", content="not yours", is_error=True),
        AssistantTextEvent(text="done"),
        FinalEvent(text="draftdone"),
    ]
    assert constructions == [{"api_key": "test-key", "timeout": 600, "max_retries": 0}]
    assert client.closed
    assert first.closed
    assert second.closed
    assert client.messages.requests[1]["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": first._message.content},
        {"role": "user", "content": [{
            "type": "tool_result",
            "tool_use_id": "call-1",
            "content": "not yours",
            "is_error": True,
        }]},
    ]


def test_claude_api_refuses_a_tool_call_after_the_limit(monkeypatch) -> None:
    client = _FakeClient([
        _FakeStream([], _AssistantMessage([_ToolUseBlock("call-1", "list_albums", {})])),
    ])
    _install_anthropic(monkeypatch, client)
    monkeypatch.setattr(tool_loop, "COWRITER_MAX_TOOL_ROUNDS", 0)

    arguments = _turn_arguments()
    events = _events(**arguments)
    with pytest.raises(ProviderUnavailableError) as raised:
        asyncio.run(events)

    assert raised.value.reason.code is SafeRouteReasonCode.TOOL_LIMIT_EXCEEDED


def test_claude_api_names_protocol_and_tool_execution_failures(monkeypatch) -> None:
    malformed_client = _FakeClient([_FakeStream([], _AssistantMessage([
        _ToolUseBlock("", "get_song", {"song_id": "s1"}),
    ]))])
    _install_anthropic(monkeypatch, malformed_client)

    arguments = _turn_arguments()
    events = _events(**arguments)
    with pytest.raises(ProviderUnavailableError) as malformed:
        asyncio.run(events)

    assert malformed.value.reason.code is SafeRouteReasonCode.TOOL_PROTOCOL_ERROR

    failing_client = _FakeClient([
        _FakeStream([], _AssistantMessage([
            _ToolUseBlock("call-1", "get_song", {"song_id": "s1"}),
        ])),
        _FakeStream([], _AssistantMessage([])),
    ])
    _install_anthropic(monkeypatch, failing_client)
    monkeypatch.setattr(
        "songmaker_cli.cowriter.tools.execute_cowriter_tool",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("failed")),
    )

    events = asyncio.run(_events(**_turn_arguments()))

    assert events == [
        ToolCallEvent(tool_use_id="call-1", name="get_song", input={"song_id": "s1"}),
        ToolResultEvent(
            tool_use_id="call-1", content="Co-Writer tool failed.", is_error=True,
        ),
        FinalEvent(text=""),
    ]


def test_claude_api_names_missing_sdk_transport_and_stream_protocol_failures(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "anthropic", None)

    arguments = _turn_arguments()
    events = _events(**arguments)
    with pytest.raises(ProviderUnavailableError) as unavailable:
        asyncio.run(events)

    assert unavailable.value.reason.code is SafeRouteReasonCode.API_HTTP_ERROR

    transport_client = _FakeClient([_FailingFakeStream([], _AssistantMessage([]))])
    _install_anthropic(monkeypatch, transport_client)

    arguments = _turn_arguments()
    events = _events(**arguments)
    with pytest.raises(ProviderUnavailableError) as transport:
        asyncio.run(events)

    assert transport.value.reason.code is SafeRouteReasonCode.API_HTTP_ERROR

    protocol_stream = _FakeStream([], _AssistantMessage([]))
    protocol_stream._text = [None]
    protocol_client = _FakeClient([protocol_stream])
    _install_anthropic(monkeypatch, protocol_client)

    arguments = _turn_arguments()
    events = _events(**arguments)
    with pytest.raises(ProviderUnavailableError) as protocol:
        asyncio.run(events)

    assert protocol.value.reason.code is SafeRouteReasonCode.API_PROTOCOL_ERROR

    final_message_client = _FakeClient([
        _FinalMessageFailingStream([], _AssistantMessage([])),
    ])
    _install_anthropic(monkeypatch, final_message_client)

    arguments = _turn_arguments()
    events = _events(**arguments)
    with pytest.raises(ProviderUnavailableError) as final_message:
        asyncio.run(events)

    assert final_message.value.reason.code is SafeRouteReasonCode.API_PROTOCOL_ERROR


def test_closing_claude_api_stream_closes_the_http_stream_and_client(monkeypatch) -> None:
    stream = _BlockingFakeStream([], _AssistantMessage([]))
    client = _FakeClient([stream])
    _install_anthropic(monkeypatch, client)

    async def _close() -> None:
        turn = claude_adapter.stream_claude_api_turn(**_turn_arguments())
        assert await anext(turn) == AssistantTextEvent(text="partial")
        await turn.aclose()

    asyncio.run(_close())

    assert stream.closed
    assert client.closed


def test_claude_api_tool_loop_persists_an_owned_write_and_refuses_a_foreign_one(
    monkeypatch,
    tmp_path,
) -> None:
    factory = init_test_db(tmp_path / "claude-api.db")
    with factory() as session:
        session.add_all([
            User(id="owner", username="owner", password_hash="x", role="user"),
            User(id="other", username="other", password_hash="x", role="user"),
        ])
        session.flush()
        session.add_all([
            Album(id="own-album", title="Own", artist="Artist", created_by="owner"),
            Album(id="other-album", title="Other", artist="Artist", created_by="other"),
            Song(id="own-song", title="Own", album_id="own-album"),
            Song(id="other-song", title="Other", album_id="other-album"),
        ])
        session.commit()

    first = _FakeStream([], _AssistantMessage([
        _ToolUseBlock("own", "update_song_lyrics", {"song_id": "own-song", "lyrics": "new"}),
        _ToolUseBlock(
            "foreign",
            "update_song_lyrics",
            {"song_id": "other-song", "lyrics": "steal"},
        ),
    ]))
    second = _FakeStream(["complete"], _AssistantMessage([_TextBlock("complete")]))
    _install_anthropic(monkeypatch, _FakeClient([first, second]))
    user = AuthenticatedUser(id="owner", username="owner", role="user", is_active=True)
    with factory() as session:
        events = asyncio.run(_events(**_turn_arguments(session, user)))
    with factory() as session:
        own = session.get(Song, "own-song")
        foreign = session.get(Song, "other-song")
        own_lyrics = own.latest_version.lyrics if own is not None and own.latest_version else None
        foreign_lyrics = (
            foreign.latest_version.lyrics
            if foreign is not None and foreign.latest_version
            else None
        )

    assert own_lyrics == "new"
    assert foreign_lyrics is None
    foreign_result = next(
        event for event in events
        if isinstance(event, ToolResultEvent) and event.tool_use_id == "foreign"
    )
    assert foreign_result.is_error is True
