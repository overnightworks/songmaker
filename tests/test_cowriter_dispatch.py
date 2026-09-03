"""Cancellation behavior of the co-writer provider dispatcher."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from songmaker_cli.claude.provider import AssistantTextEvent, StreamEvent
from songmaker_cli.cowriter import claude_adapter, dispatch
from songmaker_cli.cowriter.errors import ProviderUnavailableError


class _TrackingStream(AsyncIterator[StreamEvent]):
    def __init__(self) -> None:
        self.aclose_calls = 0
        self._has_yielded = False

    def __aiter__(self) -> _TrackingStream:
        return self

    async def __anext__(self) -> StreamEvent:
        if not self._has_yielded:
            self._has_yielded = True
            return AssistantTextEvent(text="partial")
        await asyncio.Future()

    async def aclose(self) -> None:
        self.aclose_calls += 1


async def _collect_codex_turn() -> list[StreamEvent]:
    return [event async for event in dispatch.stream_cowriter_turn(
        provider="codex",
        model="codex-test",
        user_id="user-1",
        system="system",
        messages=[],
        session=MagicMock(),
        user=MagicMock(),
    )]


def test_closing_claude_dispatch_stream_closes_provider_stream(monkeypatch) -> None:
    provider_stream = _TrackingStream()
    monkeypatch.setattr(
        claude_adapter,
        "acall_claude_with_mcp_stream",
        lambda **_kwargs: provider_stream,
    )

    async def _close_stream() -> None:
        stream = dispatch.stream_cowriter_turn(
            provider="claude",
            model="claude-test",
            user_id="user-1",
            system="system",
            messages=[],
            session=MagicMock(),
            user=MagicMock(),
        )
        assert await anext(stream) == AssistantTextEvent(text="partial")
        await stream.aclose()

    asyncio.run(_close_stream())

    assert provider_stream.aclose_calls == 1


def test_grok_dispatch_prefers_a_mirrored_cli_token_over_an_api_key(monkeypatch) -> None:
    provider_stream = _TrackingStream()
    monkeypatch.setattr(dispatch, "_grok_cli_token_is_present", lambda: True)
    monkeypatch.setattr(dispatch, "stream_grok_cli_turn", lambda **_kwargs: provider_stream)
    monkeypatch.setattr(
        dispatch,
        "stream_openai_compatible_turn",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("HTTP path must not run")),
    )

    async def collect() -> list[StreamEvent]:
        stream = dispatch.stream_cowriter_turn(
            provider="grok",
            model="grok-test",
            user_id="user-1",
            system="system",
            messages=[],
            session=MagicMock(),
            user=MagicMock(),
        )
        event = await anext(stream)
        await stream.aclose()
        return [event]

    assert asyncio.run(collect()) == [AssistantTextEvent(text="partial")]
    assert provider_stream.aclose_calls == 1


def test_grok_dispatch_uses_the_api_only_when_the_mirror_has_no_token(monkeypatch) -> None:
    monkeypatch.setattr(dispatch, "_grok_cli_token_is_present", lambda: False)
    monkeypatch.setenv("XAI_API_KEY", "api-key")
    dispatched = []

    async def api_stream(**kwargs):
        dispatched.append(kwargs)
        yield AssistantTextEvent(text="API")

    monkeypatch.setattr(dispatch, "stream_openai_compatible_turn", api_stream)

    async def collect() -> list[StreamEvent]:
        return [event async for event in dispatch.stream_cowriter_turn(
            provider="grok",
            model="grok-test",
            user_id="user-1",
            system="system",
            messages=[],
            session=MagicMock(),
            user=MagicMock(),
        )]

    assert asyncio.run(collect()) == [AssistantTextEvent(text="API")]
    assert dispatched[0]["api_key"] == "api-key"


@pytest.mark.parametrize("mirror_document", (None, {}, {"realm": {}}))
def test_grok_dispatch_uses_the_api_for_a_missing_or_tokenless_mirror(
    monkeypatch,
    tmp_path: Path,
    mirror_document,
) -> None:
    auth_file = tmp_path / "auth.json"
    monkeypatch.setattr(dispatch, "GROK_CLI_AUTH_FILE", str(auth_file))
    if mirror_document is not None:
        auth_file.write_text(json.dumps(mirror_document))
    monkeypatch.setenv("XAI_API_KEY", "api-key")
    dispatched = []

    async def api_stream(**kwargs):
        dispatched.append(kwargs)
        yield AssistantTextEvent(text="API")

    monkeypatch.setattr(dispatch, "stream_openai_compatible_turn", api_stream)

    async def collect() -> list[StreamEvent]:
        return [event async for event in dispatch.stream_cowriter_turn(
            provider="grok",
            model="grok-test",
            user_id="user-1",
            system="system",
            messages=[],
            session=MagicMock(),
            user=MagicMock(),
        )]

    assert asyncio.run(collect()) == [AssistantTextEvent(text="API")]
    assert dispatched[0]["api_key"] == "api-key"


def test_grok_dispatch_names_the_missing_api_credential_when_no_mirror_exists(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(dispatch, "GROK_CLI_AUTH_FILE", str(tmp_path / "auth.json"))
    monkeypatch.delenv("XAI_API_KEY", raising=False)

    async def collect() -> list[StreamEvent]:
        return [
            event
            async for event in dispatch.stream_cowriter_turn(
                provider="grok",
                model="grok-test",
                user_id="user-1",
                system="system",
                messages=[],
                session=MagicMock(),
                user=MagicMock(),
            )
        ]

    with pytest.raises(ProviderUnavailableError, match="XAI_API_KEY"):
        asyncio.run(collect())


@pytest.mark.acceptance("ACC-COWRITER-11")
def test_grok_dispatch_does_not_fall_back_to_http_after_a_cli_error(monkeypatch) -> None:
    monkeypatch.setattr(dispatch, "_grok_cli_token_is_present", lambda: True)

    async def cli_stream(**_kwargs):
        raise ProviderUnavailableError("grok", "cli_login_expired")
        yield AssistantTextEvent(text="unreachable")

    monkeypatch.setattr(dispatch, "stream_grok_cli_turn", cli_stream)
    monkeypatch.setattr(
        dispatch,
        "stream_openai_compatible_turn",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("HTTP path must not run")),
    )

    async def collect() -> list[StreamEvent]:
        return [
            event
            async for event in dispatch.stream_cowriter_turn(
                provider="grok",
                model="grok-test",
                user_id="user-1",
                system="system",
                messages=[],
                session=MagicMock(),
                user=MagicMock(),
            )
        ]

    with pytest.raises(ProviderUnavailableError, match="cli_login_expired"):
        asyncio.run(collect())


def test_grok_cli_token_discriminator_accepts_only_a_nonempty_string_key(
    monkeypatch, tmp_path: Path,
) -> None:
    auth_file = tmp_path / "auth.json"
    monkeypatch.setattr(dispatch, "GROK_CLI_AUTH_FILE", str(auth_file))

    auth_file.write_text(json.dumps({"realm": {"key": "subscription-token"}}))
    assert dispatch._grok_cli_token_is_present() is True

    auth_file.write_text(json.dumps({"realm": {}}))
    assert dispatch._grok_cli_token_is_present() is False


@pytest.mark.acceptance("ACC-COWRITER-12")
def test_codex_dispatch_prefers_a_mirrored_cli_access_token_over_an_api_key(
    monkeypatch,
) -> None:
    provider_stream = _TrackingStream()
    monkeypatch.setattr(dispatch, "_codex_cli_access_token_is_present", lambda: True)
    monkeypatch.setattr(dispatch, "stream_codex_cli_turn", lambda **_kwargs: provider_stream)
    monkeypatch.setattr(
        dispatch,
        "stream_openai_compatible_turn",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("HTTP path must not run")),
    )

    async def collect() -> list[StreamEvent]:
        stream = dispatch.stream_cowriter_turn(
            provider="codex",
            model="codex-test",
            user_id="user-1",
            system="system",
            messages=[],
            session=MagicMock(),
            user=MagicMock(),
        )
        event = await anext(stream)
        await stream.aclose()
        return [event]

    assert asyncio.run(collect()) == [AssistantTextEvent(text="partial")]
    assert provider_stream.aclose_calls == 1


@pytest.mark.parametrize(
    "mirror_document",
    (None, {}, {"tokens": {}}, {"tokens": {"access_token": ""}}),
)
def test_codex_dispatch_uses_the_api_for_a_missing_or_tokenless_mirror(
    monkeypatch,
    tmp_path: Path,
    mirror_document,
) -> None:
    auth_file = tmp_path / "auth.json"
    monkeypatch.setattr(dispatch, "CODEX_CLI_AUTH_FILE", str(auth_file))
    if mirror_document is not None:
        auth_file.write_text(json.dumps(mirror_document))
    monkeypatch.setenv("OPENAI_API_KEY", "api-key")
    dispatched = []

    async def api_stream(**kwargs):
        dispatched.append(kwargs)
        yield AssistantTextEvent(text="API")

    monkeypatch.setattr(dispatch, "stream_openai_compatible_turn", api_stream)

    assert asyncio.run(_collect_codex_turn()) == [AssistantTextEvent(text="API")]
    assert dispatched[0]["api_key"] == "api-key"


@pytest.mark.parametrize(
    "mirror_document",
    (
        [],
        {"tokens": None},
        {"tokens": []},
        {"tokens": {"access_token": None}},
        {"tokens": {"access_token": 1}},
    ),
)
def test_codex_dispatch_rejects_invalid_mirror_without_http_fallback(
    monkeypatch,
    tmp_path: Path,
    mirror_document,
) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps(mirror_document))
    monkeypatch.setattr(dispatch, "CODEX_CLI_AUTH_FILE", str(auth_file))
    monkeypatch.setattr(
        dispatch,
        "stream_openai_compatible_turn",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("HTTP path must not run")),
    )

    with pytest.raises(ProviderUnavailableError, match="codex_cli_error"):
        asyncio.run(_collect_codex_turn())


def test_codex_dispatch_rejects_invalid_json_without_http_fallback(
    monkeypatch,
    tmp_path: Path,
) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text("{")
    monkeypatch.setattr(dispatch, "CODEX_CLI_AUTH_FILE", str(auth_file))
    monkeypatch.setattr(
        dispatch,
        "stream_openai_compatible_turn",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("HTTP path must not run")),
    )

    with pytest.raises(ProviderUnavailableError, match="codex_cli_error"):
        asyncio.run(_collect_codex_turn())


def test_codex_cli_access_token_discriminator_reports_an_unreadable_mirror(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        dispatch.Path,
        "read_text",
        lambda _path: (_ for _ in ()).throw(OSError("unreadable")),
    )

    with pytest.raises(ProviderUnavailableError, match="codex_cli_error"):
        dispatch._codex_cli_access_token_is_present()


@pytest.mark.acceptance("ACC-COWRITER-13")
def test_codex_dispatch_does_not_fall_back_to_http_after_a_cli_error(monkeypatch) -> None:
    monkeypatch.setattr(dispatch, "_codex_cli_access_token_is_present", lambda: True)

    async def cli_stream(**_kwargs):
        raise ProviderUnavailableError("codex", "cli_login_expired")
        yield AssistantTextEvent(text="unreachable")

    monkeypatch.setattr(dispatch, "stream_codex_cli_turn", cli_stream)
    monkeypatch.setattr(
        dispatch,
        "stream_openai_compatible_turn",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("HTTP path must not run")),
    )

    with pytest.raises(ProviderUnavailableError, match="cli_login_expired"):
        asyncio.run(_collect_codex_turn())


def test_codex_cli_access_token_discriminator_accepts_only_a_nonempty_string(
    monkeypatch, tmp_path: Path,
) -> None:
    auth_file = tmp_path / "auth.json"
    monkeypatch.setattr(dispatch, "CODEX_CLI_AUTH_FILE", str(auth_file))

    auth_file.write_text(json.dumps({"tokens": {"access_token": "subscription-token"}}))
    assert dispatch._codex_cli_access_token_is_present() is True

    auth_file.write_text(json.dumps({"tokens": {"access_token": ""}}))
    assert dispatch._codex_cli_access_token_is_present() is False
