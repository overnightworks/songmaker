"""Co-writer provider switch (#34). Models come from the live catalog."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from conftest import TEST_SECRET, make_fake_redis, refresh_provider_snapshots
from fastapi import FastAPI
from fastapi.testclient import TestClient

from songmaker_cli.agent_cli import LOGGED_OUT, CliLogin, GrokCliStatus
from songmaker_cli.api_models.settings import ProviderSurfaceState, ProviderSurfaceStatus
from songmaker_cli.app_context import AppContext
from songmaker_cli.claude.provider import FinalEvent, ToolCallEvent
from songmaker_cli.constants import (
    COWRITER_MAX_TOOL_ROUNDS,
    SETTING_CLAUDE_SCORING_MODEL,
    SETTING_COWRITER_MODEL,
    SETTING_COWRITER_PROVIDER,
    SETTING_JUDGE_MODEL,
    SETTING_JUDGE_PROVIDER,
)
from songmaker_cli.cowriter.catalog import ProviderRoute, list_provider_models
from songmaker_cli.cowriter.errors import (
    ProviderModelCatalogUnavailableError,
    ProviderUnavailableError,
)
from songmaker_cli.cowriter.openai_adapter import (
    _parse_tool_call,
    stream_openai_compatible_turn,
)
from songmaker_cli.cowriter.tools import execute_cowriter_tool
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import (
    Album,
    AuditLog,
    AvailableModel,
    ChatMessage,
    Job,
    RateLimitSetting,
    Song,
    User,
)
from songmaker_cli.db.queries.settings import (
    get_cowriter_model,
    get_cowriter_models_by_provider,
    get_cowriter_provider,
    get_cowriter_tail_token_budget,
    get_effective_provider_routes,
    get_judge_model,
    get_judge_provider,
    get_raw_stored_cowriter_settings,
    get_raw_stored_judge_settings,
    set_claude_model,
    set_provider_routes,
)
from songmaker_cli.mcp_server.tools import tool_create_song
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

LIVE_CATALOG = {
    "claude": ["claude-opus-4-6", "claude-sonnet-4-6"],
    "grok": ["grok-4.6", "grok-4.5"],
    "codex": ["gpt-5.4"],
}


def test_legacy_provider_routes_preserve_the_old_per_provider_defaults(monkeypatch, tmp_path):
    factory = init_db(tmp_path / "routes.db")
    monkeypatch.setattr(
        "songmaker_cli.agent_cli.grok_cli_token_is_present", lambda: True,
    )
    monkeypatch.setattr(
        "songmaker_cli.agent_cli.codex_cli_access_token_is_present", lambda: False,
    )

    with factory() as session:
        assert get_effective_provider_routes(session) == {
            "claude": "cli", "grok": "cli", "codex": "api",
        }


def test_unavailable_legacy_probe_defaults_only_its_provider_to_cli(monkeypatch, tmp_path):
    from songmaker_cli.agent_cli import AgentCliUnavailableError

    factory = init_db(tmp_path / "routes.db")
    monkeypatch.setattr(
        "songmaker_cli.agent_cli.grok_cli_token_is_present",
        lambda: (_ for _ in ()).throw(AgentCliUnavailableError("broken")),
    )
    monkeypatch.setattr(
        "songmaker_cli.agent_cli.codex_cli_access_token_is_present", lambda: False,
    )

    with factory() as session:
        assert get_effective_provider_routes(session) == {
            "claude": "cli", "grok": "cli", "codex": "api",
        }


def test_provider_routes_are_compact_complete_and_reject_malformed_values(tmp_path):
    factory = init_db(tmp_path / "routes.db")
    routes = {"claude": "cli", "grok": "api", "codex": "cli"}

    with factory() as session:
        set_provider_routes(session, routes)
        session.commit()
        assert get_effective_provider_routes(session) == routes
        row = session.query(RateLimitSetting).filter_by(setting_key="provider_routes").one()
        assert len(row.value_text) <= 100
        row.value_text = '{"claude":"cli"}'
        session.commit()
        with pytest.raises(ValueError, match="exactly"):
            get_effective_provider_routes(session)


@pytest.fixture(autouse=True)
def _clear_agent_cli_caches():
    from songmaker_cli.agent_cli import clear_agent_cli_caches
    from songmaker_cli.cowriter.catalog import clear_provider_snapshots

    clear_agent_cli_caches()
    clear_provider_snapshots()
    yield
    clear_agent_cli_caches()
    clear_provider_snapshots()


def _fake_user(user_id: str, role: str = "user"):
    user = AuthenticatedUser(
        id=user_id, username=f"u-{user_id}", role=role, is_active=True,
    )
    return lambda: user


def _stream_events(response) -> list[dict]:
    events: list[dict] = []
    for line in response.iter_lines():
        if not line:
            continue
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def _seed(session, user_id: str) -> None:
    session.add(User(
        id=user_id, username=f"user-{user_id}", password_hash="x", role="admin",
    ))
    session.flush()
    session.add(Album(id="alb1", title="Rock", artist="B", created_by=user_id))
    session.add(Song(id="s1", title="Thunder", album_id="alb1", track_number=1))
    session.query(AvailableModel).filter(
        AvailableModel.id.in_(["turbo", "sft"]),
    ).update({"is_active": True}, synchronize_session=False)
    session.commit()


@pytest.fixture()
def admin_client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.list_provider_models",
        lambda provider, _route: list(LIVE_CATALOG[provider]),
    )
    factory = init_db(tmp_path / "cowriter.db")
    with factory() as session:
        _seed(session, "u-test")
    ctx = AppContext(
        db=factory,
        audio_dir=tmp_path / "audio",
        data_dir=tmp_path / "data",
        session_secret=TEST_SECRET,
        redis=make_fake_redis(),
    )
    from songmaker_cli.api import router
    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = _fake_user("u-test", "admin")
    app.include_router(router)
    yield TestClient(app), factory


def test_unknown_provider_rejected_at_settings_boundary(admin_client):
    client, _ = admin_client
    resp = client.put("/api/settings/cowriter", json={"provider": "bob", "model": "x"})
    assert resp.status_code == 422


def _save_removed_cowriter_provider(factory) -> None:
    with factory() as session:
        set_claude_model(session, SETTING_COWRITER_PROVIDER, "retired-provider")
        session.commit()


def _save_removed_judge_provider(factory) -> None:
    with factory() as session:
        set_claude_model(session, SETTING_JUDGE_PROVIDER, "retired-provider")
        set_claude_model(session, SETTING_JUDGE_MODEL, "retired-model")
        session.commit()


def _stored_cowriter_state(session) -> tuple[str | None, str | None, int]:
    stored = get_raw_stored_cowriter_settings(session)
    return stored.provider, stored.model, get_cowriter_tail_token_budget(session)


def test_raw_stored_cowriter_settings_preserve_the_unresolved_pair(admin_client):
    _, factory = admin_client
    with factory() as session:
        set_claude_model(session, SETTING_COWRITER_PROVIDER, "retired-provider")
        set_claude_model(session, SETTING_COWRITER_MODEL, "")
        session.commit()

    with factory() as session:
        stored = get_raw_stored_cowriter_settings(session)

    assert stored.provider == "retired-provider"
    assert stored.model == ""


def test_raw_stored_judge_settings_preserve_the_unresolved_pair(admin_client):
    _, factory = admin_client
    _save_removed_judge_provider(factory)

    with factory() as session:
        stored = get_raw_stored_judge_settings(session)

    assert stored.provider == "retired-provider"
    assert stored.model == "retired-model"


def test_get_cowriter_settings_names_a_removed_saved_provider(admin_client):
    client, factory = admin_client
    _save_removed_cowriter_provider(factory)

    resp = client.get("/api/settings/cowriter")

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Unknown co-writer provider 'retired-provider'"


def test_valid_cowriter_put_replaces_a_removed_saved_provider(
    admin_client, every_provider_is_configured,
):
    client, factory = admin_client
    _save_removed_cowriter_provider(factory)

    resp = client.put(
        "/api/settings/cowriter",
        json={"provider": "grok", "model": "grok-4.6"},
    )

    assert resp.status_code == 200
    assert resp.json()["provider"] == "grok"

    saved = client.get("/api/settings/cowriter")

    assert saved.status_code == 200
    assert saved.json()["provider"] == "grok"


def test_invalid_cowriter_put_rejects_a_removed_saved_provider_without_server_error(
    admin_client,
):
    client, factory = admin_client
    _save_removed_cowriter_provider(factory)

    resp = client.put(
        "/api/settings/cowriter",
        json={"provider": "retired-provider", "model": "retired-model"},
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Unknown co-writer provider 'retired-provider'"


def test_valid_judge_put_replaces_a_removed_saved_provider(
    admin_client, every_provider_is_configured,
):
    client, factory = admin_client
    _save_removed_judge_provider(factory)

    resp = client.put(
        "/api/settings/judge",
        json={"provider": "grok", "model": "grok-4.6"},
    )

    assert resp.status_code == 200
    assert resp.json()["provider"] == "grok"
    with factory() as session:
        assert get_raw_stored_judge_settings(session).provider == "grok"


def test_judge_put_rejects_a_replacement_when_the_new_provider_is_unconfigured(
    admin_client,
):
    client, factory = admin_client
    _save_removed_judge_provider(factory)
    status = ProviderSurfaceStatus(
        state=ProviderSurfaceState.UNCONFIGURED,
        needs="api_key",
        environment_key="XAI_API_KEY",
    )

    with patch("songmaker_cli.settings_api._surface_status", return_value=status):
        response = client.put(
            "/api/settings/judge",
            json={"provider": "grok", "model": "grok-4.6"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "provider": "grok",
        "surface": "judge",
        "status": status.model_dump(exclude_none=True),
    }
    with factory() as session:
        assert get_raw_stored_judge_settings(session).provider == "retired-provider"


def test_chat_rejects_a_removed_saved_provider_without_creating_a_job(admin_client):
    client, factory = admin_client
    _save_removed_cowriter_provider(factory)

    resp = client.post("/api/chat/turn", json={"message": "hello"})

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Unknown co-writer provider 'retired-provider'"
    with factory() as session:
        assert session.query(Job).count() == 0


def test_model_must_be_in_the_live_catalog(admin_client, every_provider_is_configured):
    client, _ = admin_client
    resp = client.put(
        "/api/settings/cowriter",
        json={"provider": "grok", "model": "grok-4"},
    )
    assert resp.status_code == 422
    ok = client.put(
        "/api/settings/cowriter",
        json={"provider": "grok", "model": "grok-4.6"},
    )
    assert ok.status_code == 200
    assert ok.json()["model"] == "grok-4.6"


def test_cowriter_keeps_each_provider_model_across_provider_saves(
    admin_client, every_provider_is_configured,
):
    client, factory = admin_client

    grok = client.put(
        "/api/settings/cowriter", json={"provider": "grok", "model": "grok-4.5"},
    )
    assert grok.status_code == 200
    codex = client.put(
        "/api/settings/cowriter", json={"provider": "codex", "model": "gpt-5.4"},
    )
    assert codex.status_code == 200

    saved = client.get("/api/settings/cowriter")

    assert saved.status_code == 200
    assert saved.json()["selected_models_by_provider"] == {
        "claude": "claude-opus-4-6",
        "codex": "gpt-5.4",
        "grok": "grok-4.5",
    }
    with factory() as session:
        assert get_cowriter_models_by_provider(session) == {
            "claude": "claude-opus-4-6",
            "codex": "gpt-5.4",
            "grok": "grok-4.5",
        }


def test_cowriter_save_preserves_the_legacy_active_pair(
    admin_client, every_provider_is_configured,
):
    client, factory = admin_client
    with factory() as session:
        set_claude_model(session, SETTING_COWRITER_PROVIDER, "grok")
        set_claude_model(session, SETTING_COWRITER_MODEL, "grok-4.6")
        session.commit()

    saved = client.put(
        "/api/settings/cowriter", json={"provider": "codex", "model": "gpt-5.4"},
    )

    assert saved.status_code == 200
    assert saved.json()["selected_models_by_provider"] == {
        "claude": "claude-opus-4-6",
        "codex": "gpt-5.4",
        "grok": "grok-4.6",
    }
    with factory() as session:
        assert get_cowriter_models_by_provider(session) == {
            "claude": "claude-opus-4-6",
            "codex": "gpt-5.4",
            "grok": "grok-4.6",
        }


def test_cowriter_get_returns_card_defaults_without_catalog_fallback(
    admin_client, every_provider_is_configured,
):
    client, _ = admin_client

    response = client.get("/api/settings/cowriter")

    assert response.status_code == 200
    assert response.json()["selected_models_by_provider"] == {
        "claude": "claude-opus-4-6",
        "codex": "",
        "grok": "",
    }


def test_codex_cli_catalog_is_returned_and_can_be_saved(admin_client, monkeypatch):
    client, factory = admin_client
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.list_provider_models", list_provider_models,
    )
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.codex_cli_access_token_is_present", lambda: True,
    )
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog._cli_is_logged_in", lambda _provider: True,
    )
    refresh_provider_snapshots()
    from songmaker_cli.db.queries.settings import set_provider_routes

    with factory() as session:
        set_provider_routes(session, {"claude": "cli", "grok": "api", "codex": "cli"})
        session.commit()

    settings = client.get("/api/settings/cowriter")

    assert settings.status_code == 200
    codex_models = settings.json()["models_by_provider"]["codex"]
    assert codex_models == list_provider_models("codex", ProviderRoute.CLI)
    assert settings.json()["models_sources"]["codex"] == "known models for the CLI route"
    readiness = settings.json()["provider_routes_status"]["codex"]["cli"]["readiness"]
    assert readiness["state"] == "ready"
    assert readiness["capability"] == "tools_available"
    assert readiness["reason"] is None
    saved = client.put(
        "/api/settings/cowriter", json={"provider": "codex", "model": codex_models[0]},
    )
    assert saved.status_code == 200

    assert saved.json()["provider"] == "codex"
    rejected = client.put(
        "/api/settings/cowriter", json={"provider": "codex", "model": "not-a-model"},
    )
    assert rejected.status_code == 422


def test_cowriter_rejects_unknown_and_cross_provider_models_before_and_after_saving(
    admin_client, every_provider_is_configured,
):
    client, _ = admin_client

    fresh_unknown = client.put(
        "/api/settings/cowriter",
        json={"provider": "claude", "model": "claude-nonexistent-9"},
    )
    assert fresh_unknown.status_code == 422

    saved = client.put(
        "/api/settings/cowriter",
        json={"provider": "claude", "model": "claude-opus-4-6"},
    )
    assert saved.status_code == 200

    saved_unknown = client.put(
        "/api/settings/cowriter",
        json={"provider": "claude", "model": "claude-nonexistent-9"},
    )
    assert saved_unknown.status_code == 422

    cross_provider = client.put(
        "/api/settings/cowriter",
        json={"provider": "grok", "model": "claude-opus-4-6"},
    )
    assert cross_provider.status_code == 422


def test_default_model_id_is_added_to_the_claude_cli_catalog_on_fresh_install(
    admin_client, monkeypatch, every_provider_is_configured,
):
    client, _ = admin_client
    aliases = {
        "claude": ["haiku", "opus", "sonnet"],
        "grok": LIVE_CATALOG["grok"],
        "codex": LIVE_CATALOG["codex"],
    }
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.list_provider_models",
        lambda provider, _route: aliases[provider],
    )
    refresh_provider_snapshots()

    settings = client.get("/api/settings/cowriter")

    assert settings.status_code == 200
    assert settings.json()["model"] == "claude-opus-4-6"
    assert settings.json()["models_by_provider"]["claude"] == [
        "haiku", "opus", "sonnet", "claude-opus-4-6",
    ]
    assert settings.json()["current_models_not_in_catalog"] == {
        "claude": "claude-opus-4-6",
    }
    saved = client.put(
        "/api/settings/cowriter",
        json={"provider": "claude", "model": "claude-opus-4-6"},
    )
    assert saved.status_code == 200


def test_claude_api_catalog_is_ready_for_the_cowriter_and_judge(
    admin_client, every_provider_is_configured,
):
    client, factory = admin_client
    with factory() as session:
        set_provider_routes(
            session,
            {"claude": "api", "grok": "api", "codex": "api"},
        )
        session.commit()

    refresh_provider_snapshots()
    cowriter = client.get("/api/settings/cowriter").json()
    claude_api = cowriter["provider_routes_status"]["claude"]["api"]
    assert claude_api["models"] == LIVE_CATALOG["claude"]
    assert claude_api["readiness"]["state"] == "ready"
    assert claude_api["readiness"]["capability"] == "tools_available"
    assert claude_api["readiness"]["reason"] is None

    judge = client.get("/api/settings/judge").json()
    assert judge["models_by_provider"]["claude"] == LIVE_CATALOG["claude"]
    saved = client.put(
        "/api/settings/judge",
        json={"provider": "claude", "model": "claude-sonnet-4-6"},
    )
    assert saved.status_code == 200

    providers = {
        item["provider"]: item
        for item in client.get("/api/settings/providers").json()
    }
    assert providers["claude"]["cowriter"]["state"] == "configured"
    assert providers["claude"]["judge"]["state"] == "configured"


def test_claude_api_without_its_sdk_cannot_be_selected_for_the_cowriter(
    admin_client,
    monkeypatch,
):
    client, _ = admin_client
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("songmaker_cli.cowriter.catalog._anthropic_sdk_available", lambda: False)
    monkeypatch.setattr("songmaker_cli.cowriter.catalog._cli_setup_method", lambda _provider: None)
    refresh_provider_snapshots()

    response = client.put(
        "/api/settings/cowriter",
        json={
            "provider": "claude",
            "model": "claude-opus-4-6",
            "provider_routes": {"claude": "api", "grok": "api", "codex": "api"},
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "api_http_error"


@pytest.mark.acceptance("ACC-COWRITER-14")
def test_chat_turn_uses_the_claude_api_sdk_tool_loop_and_persists_the_conversation(
    admin_client,
    every_provider_is_configured,
    monkeypatch,
):
    client, factory = admin_client
    with factory() as session:
        session.add(User(
            id="u-foreign",
            username="u-foreign",
            password_hash="x",
            role="user",
        ))
        session.flush()
        session.add(Album(
            id="alb-foreign",
            title="Foreign",
            artist="B",
            created_by="u-foreign",
        ))
        session.add(Song(
            id="s-foreign",
            title="Foreign song",
            album_id="alb-foreign",
            track_number=1,
        ))
        session.commit()
    settings = client.put(
        "/api/settings/cowriter",
        json={
            "provider": "claude",
            "model": "claude-opus-4-6",
            "provider_routes": {"claude": "api", "grok": "api", "codex": "api"},
        },
    )
    assert settings.status_code == 200

    class ToolUse:
        type = "tool_use"

        def __init__(self, tool_use_id: str, name: str, input: dict) -> None:
            self.id = tool_use_id
            self.name = name
            self.input = input

    class Message:
        def __init__(self, content: list[object]) -> None:
            self.content = content

    class Stream:
        def __init__(self, text: list[str], message: Message) -> None:
            self._text = text
            self._message = message

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> bool:
            return False

        @property
        def text_stream(self):
            return self._texts()

        async def _texts(self):
            for text in self._text:
                yield text

        async def get_final_message(self) -> Message:
            return self._message

    class Messages:
        def __init__(self) -> None:
            self.requests: list[dict] = []
            self.streams = [
                Stream([], Message([
                    ToolUse(
                        "write-1",
                        "update_song_lyrics",
                        {"song_id": "s1", "lyrics": "API-written lyrics"},
                    ),
                    ToolUse(
                        "write-foreign",
                        "update_song_lyrics",
                        {"song_id": "s-foreign", "lyrics": "stolen lyrics"},
                    ),
                ])),
                Stream(["finished"], Message([])),
            ]

        def stream(self, **kwargs):
            self.requests.append(kwargs)
            return self.streams.pop(0)

    class Client:
        def __init__(self) -> None:
            self.messages = Messages()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> bool:
            return False

    fake_client = Client()

    class AsyncAnthropic:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self) -> Client:
            return await fake_client.__aenter__()

        async def __aexit__(self, *args) -> bool:
            return await fake_client.__aexit__(*args)

    monkeypatch.setitem(
        sys.modules,
        "anthropic",
        SimpleNamespace(AsyncAnthropic=AsyncAnthropic, APIError=Exception),
    )
    client.app.dependency_overrides[get_current_user] = _fake_user("u-test", "user")

    response = client.post("/api/chat/turn", json={"message": "Please revise the lyrics."})
    events = _stream_events(response)
    final = next(event for event in events if event["type"] == "final")

    assert response.status_code == 200
    assert final["assistant_message"]["content"] == "finished"
    assert [event["type"] for event in events].count("tool_call") == 2
    tool_results = {
        event["tool_use_id"]: event
        for event in events
        if event["type"] == "tool_result"
    }
    assert tool_results["write-1"]["is_error"] is False
    assert tool_results["write-foreign"]["is_error"] is True
    assert fake_client.messages.requests[0]["model"] == "claude-opus-4-6"
    assert fake_client.messages.requests[1]["messages"][-1]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "write-1",
            "content": tool_results["write-1"]["content"],
            "is_error": False,
        },
        {
            "type": "tool_result",
            "tool_use_id": "write-foreign",
            "content": tool_results["write-foreign"]["content"],
            "is_error": True,
        },
    ]
    with factory() as session:
        song = session.get(Song, "s1")
        foreign_song = session.get(Song, "s-foreign")
        messages = session.query(ChatMessage).order_by(ChatMessage.created_at).all()
        job = session.query(Job).filter_by(type="chat").one()

        assert song is not None and song.latest_version is not None
        assert song.latest_version.lyrics == "API-written lyrics"
        assert foreign_song is not None and foreign_song.latest_version is None
        assert [message.role for message in messages] == ["user", "assistant"]
        assert [message.content for message in messages] == [
            "Please revise the lyrics.",
            "finished",
        ]
        assert job.status == "completed"


def test_grok_cli_route_status_is_ready_with_tools(
    admin_client, every_provider_is_configured,
):
    client, _ = admin_client
    refresh_provider_snapshots()

    response = client.get("/api/settings/cowriter")

    assert response.status_code == 200
    readiness = response.json()["provider_routes_status"]["grok"]["cli"]["readiness"]
    assert readiness["state"] == "ready"
    assert readiness["capability"] == "tools_available"
    assert readiness["reason"] is None


def test_cowriter_put_without_routes_preserves_the_stored_route_map(
    admin_client, every_provider_is_configured,
):
    client, factory = admin_client
    routes = {"claude": "cli", "grok": "api", "codex": "cli"}
    with factory() as session:
        set_provider_routes(session, routes)
        session.commit()

    saved = client.put(
        "/api/settings/cowriter",
        json={"provider": "grok", "model": "grok-4.6"},
    )

    assert saved.status_code == 200
    assert saved.json()["provider_routes"] == routes
    with factory() as session:
        audit = session.query(AuditLog).one()
    assert audit.detail.endswith("routes=claude=cli,codex=cli,grok=api")


def test_cowriter_put_requires_an_admin(admin_client):
    client, _ = admin_client
    client.app.dependency_overrides[get_current_user] = _fake_user("u-plain", "user")
    try:
        response = client.put(
            "/api/settings/cowriter",
            json={"provider": "grok", "model": "grok-4.6"},
        )
    finally:
        client.app.dependency_overrides[get_current_user] = _fake_user("u-test", "admin")

    assert response.status_code == 403


def test_each_saved_provider_calls_only_itself(admin_client, every_provider_is_configured):
    client, _ = admin_client
    captured: dict = {}

    async def _claude(**kwargs):
        captured["claude"] = kwargs
        yield FinalEvent(text="claude-ok")

    async def _oai(**kwargs):
        captured["oai"] = kwargs
        yield FinalEvent(text="oai-ok")

    cases = [
        ("claude", "claude-opus-4-6"),
        ("grok", "grok-4.6"),
        ("codex", "gpt-5.4"),
    ]
    for provider, model in cases:
        captured.clear()
        client.put("/api/settings/cowriter", json={"provider": provider, "model": model})
        with (
            patch("songmaker_cli.cowriter.dispatch.stream_claude_turn", _claude),
            patch(
                "songmaker_cli.cowriter.dispatch.stream_openai_compatible_turn",
                _oai,
            ),
            patch.dict("os.environ", {
                "XAI_API_KEY": "grok-key",
                "OPENAI_API_KEY": "openai-key",
            }, clear=False),
        ):
            from songmaker_cli.settings import get_settings
            get_settings.cache_clear()
            resp = client.post("/api/chat/turn", json={"message": "hello"})
        events = _stream_events(resp)
        assert any(event.get("type") == "final" for event in events)
        if provider == "claude":
            assert "claude" in captured
            assert "oai" not in captured
            ctx = captured["claude"]["messages"][-1]["content"]
        else:
            assert "oai" in captured
            assert captured["oai"]["provider"] == provider
            assert captured["oai"]["model"] == model
            assert "claude" not in captured
            ctx = captured["oai"]["messages"][-1]["content"]
        assert "<user_memory>" in ctx
        assert ctx.endswith("hello")


def test_missing_credentials_named_error_no_persist(
    admin_client, monkeypatch, every_provider_is_configured,
):
    client, factory = admin_client
    client.put("/api/settings/cowriter", json={"provider": "grok", "model": "grok-4.6"})
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    from songmaker_cli.settings import get_settings
    get_settings.cache_clear()
    called = {"claude": False, "oai": False}

    async def _claude(**_k):
        called["claude"] = True
        yield FinalEvent(text="no")

    async def _oai(**_k):
        called["oai"] = True
        yield FinalEvent(text="no")

    with (
        patch("songmaker_cli.cowriter.dispatch.stream_claude_turn", _claude),
        patch("songmaker_cli.cowriter.dispatch.stream_openai_compatible_turn", _oai),
    ):
        resp = client.post("/api/chat/turn", json={"message": "hi"})
    events = _stream_events(resp)
    err = next(event for event in events if event.get("type") == "error")
    assert err["status"] == 503
    assert err["provider"] == "grok"
    assert err["route"] == "api"
    assert err["reason"]["code"] == "api_key_not_set"
    assert called["claude"] is False
    assert called["oai"] is False
    with factory() as session:
        assert session.query(ChatMessage).count() == 0


def test_create_song_tool_hits_canonical_function(admin_client):
    _, factory = admin_client
    user = AuthenticatedUser(
        id="u-test", username="u-u-test", role="admin", is_active=True,
    )
    with factory() as session:
        via_catalog, err = execute_cowriter_tool(
            session, user, "create_song",
            {"album_id": "alb1", "title": "FromCatalog", "lyrics": "a"},
        )
        assert err is False
        canonical = tool_create_song(
            session, user, album_id="alb1", title="FromDirect", lyrics="b",
        )
        session.commit()
    assert "FromCatalog" in via_catalog
    assert canonical.song.title == "FromDirect"
    with factory() as session:
        titles = {song.title for song in session.query(Song).all()}
        assert "FromCatalog" in titles
        assert "FromDirect" in titles


def test_rename_song_tool_via_shared_session_pulls_slug_along(admin_client):
    """The catalog's rename_song runs on the same shared session a real
    co-writer turn holds open for the whole SSE response (unlike the
    isolated-session tool_rename_song coverage elsewhere) — pin that the
    slug still follows the title through execute_cowriter_tool's commit."""
    _, factory = admin_client
    user = AuthenticatedUser(
        id="u-test", username="u-u-test", role="admin", is_active=True,
    )
    with factory() as session:
        _, err = execute_cowriter_tool(
            session, user, "rename_song",
            {"song_id": "s1", "title": "Renamed Track"},
        )
        assert err is False
    with factory() as session:
        song = session.query(Song).filter_by(id="s1").one()
        assert song.title == "Renamed Track"
        assert song.slug == "renamed-track"


def test_suggest_album_cover_tool_hits_the_canonical_admission_owner(admin_client):
    _, factory = admin_client
    user = AuthenticatedUser(
        id="u-test", username="u-u-test", role="admin", is_active=True,
    )
    with factory() as session:
        via_catalog, err = execute_cowriter_tool(
            session, user, "suggest_album_cover", {"album_id": "alb1"},
        )
        assert err is False
        assert '"status": "queued"' in via_catalog

    with factory() as session:
        job = session.query(Job).filter_by(album_id="alb1").one()
        assert job.type == "cover"


def test_cowriter_provider_switch_keeps_scoring_model(
    admin_client, every_provider_is_configured,
):
    client, factory = admin_client
    with factory() as session:
        set_claude_model(
            session, SETTING_CLAUDE_SCORING_MODEL, "claude-haiku-4-5-20251001",
        )
        session.commit()
    client.put("/api/settings/cowriter", json={"provider": "codex", "model": "gpt-5.4"})
    models = client.get("/api/settings/claude-models").json()
    assert models["scoring_model"] == "claude-haiku-4-5-20251001"
    cowriter = client.get("/api/settings/cowriter").json()
    assert cowriter["provider"] == "codex"
    assert cowriter["allowed_models"] == LIVE_CATALOG["codex"]


def test_openai_adapter_emits_same_event_types(admin_client, every_provider_is_configured):
    client, _ = admin_client
    client.put("/api/settings/cowriter", json={"provider": "grok", "model": "grok-4.6"})

    class _Resp:
        status_code = 200

        def json(self):
            return {
                "choices": [{
                    "message": {"role": "assistant", "content": "from grok"},
                }],
            }

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def post(self, *_a, **_k):
            return _Resp()

    with (
        patch("songmaker_cli.cowriter.openai_adapter.httpx.AsyncClient", _Client),
        patch.dict("os.environ", {"XAI_API_KEY": "k"}, clear=False),
    ):
        from songmaker_cli.settings import get_settings
        get_settings.cache_clear()
        resp = client.post("/api/chat/turn", json={"message": "hi"})
    types = [event["type"] for event in _stream_events(resp)]
    assert types.count("final") == 1
    assert "error" not in types
    assert "assistant_text" in types


def test_openai_adapter_allows_final_response_after_last_tool_round(monkeypatch):
    responses = [
        {
            "choices": [{"message": {
                "content": "",
                "tool_calls": [{
                    "id": f"call-{index}",
                    "function": {"name": "list_albums", "arguments": "{}"},
                }],
            }}],
        }
        for index in range(COWRITER_MAX_TOOL_ROUNDS)
    ]
    responses.append({"choices": [{"message": {"content": "done"}}]})

    class _Response:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    class _Client:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return _Response(responses.pop(0))

    monkeypatch.setattr("songmaker_cli.cowriter.openai_adapter.httpx.AsyncClient", _Client)
    execute = MagicMock(return_value=("[]", False))
    monkeypatch.setattr(
        "songmaker_cli.cowriter.tools.execute_cowriter_tool", execute,
    )

    async def _collect_events():
        return [
            event
            async for event in stream_openai_compatible_turn(
                provider="grok",
                api_url="https://example.invalid/chat",
                api_key="secret",
                model="live-model",
                system="system",
                messages=[{"role": "user", "content": "hello"}],
                session=MagicMock(),
                user=AuthenticatedUser(
                    id="u", username="u", role="user", is_active=True,
                ),
            )
        ]

    events = asyncio.run(_collect_events())
    assert sum(isinstance(event, ToolCallEvent) for event in events) == 8
    assert isinstance(events[-1], FinalEvent)
    assert events[-1].text == "done"
    assert execute.call_count == 8


def _status(
    state: str,
    *,
    needs: str | None = None,
    setup_method: str | None = None,
    environment_key: str | None = None,
    missing_dependency: str | None = None,
) -> dict[str, str | None]:
    return {
        "state": state,
        "needs": needs,
        "setup_method": setup_method,
        "environment_key": environment_key,
        "missing_dependency": missing_dependency,
    }


def _stub_cli_runners(
    monkeypatch,
    *,
    claude: CliLogin = LOGGED_OUT,
    grok: GrokCliStatus | None = None,
    codex: CliLogin = LOGGED_OUT,
) -> dict[str, int]:
    calls = {"claude": 0, "grok": 0, "codex": 0}
    monkeypatch.setattr("songmaker_cli.claude.provider._find_claude_binary", lambda: "claude")

    def fake_claude_output(_binary: str) -> str:
        calls["claude"] += 1
        return json.dumps({"loggedIn": claude.logged_in, "authMethod": claude.auth_method})

    def fake_cli_output(binary: str, _args: tuple[str, ...]) -> str:
        if binary == "grok":
            calls["grok"] += 1
            status = grok or GrokCliStatus(login=LOGGED_OUT, model_names=())
            if not status.login.logged_in:
                return "You are not authenticated."
            models = "\n".join(f"  * {model}" for model in status.model_names)
            return (
                f"You are logged in with {status.login.auth_method or 'grok.com'}."
                f"\n\nAvailable models:\n{models}"
            )
        calls["codex"] += 1
        return "Logged in using ChatGPT" if codex.logged_in else "Not logged in"

    monkeypatch.setattr("songmaker_cli.agent_cli._claude_output", fake_claude_output)
    monkeypatch.setattr("songmaker_cli.agent_cli._cli_output", fake_cli_output)
    return calls


@pytest.mark.parametrize(
    ("keys", "claude_login", "grok_login", "codex_login", "sdk_available", "expected"),
    [
        (
            {},
            LOGGED_OUT,
            LOGGED_OUT,
            LOGGED_OUT,
            True,
            {
                "claude": (
                    _status("unconfigured", needs="cli_login"),
                    _status(
                        "unconfigured", needs="api_key", environment_key="ANTHROPIC_API_KEY"
                    ),
                ),
                "grok": (
                    _status("unconfigured", needs="api_key", environment_key="XAI_API_KEY"),
                ) * 2,
                "codex": (
                    _status("unconfigured", needs="api_key", environment_key="OPENAI_API_KEY"),
                ) * 2,
            },
        ),
        (
            {},
            CliLogin(logged_in=True, auth_method="claude.ai"),
            CliLogin(logged_in=True, auth_method="grok"),
            CliLogin(logged_in=True, auth_method="chatgpt"),
            True,
            {
                "claude": (_status("configured", setup_method="claude_cli"),) * 2,
                "grok": (
                    _status(
                        "configured",
                        setup_method="grok_cli",
                    ),
                    _status(
                        "cli_login_needs_api_key",
                        needs="api_key",
                        setup_method="grok_cli",
                        environment_key="XAI_API_KEY",
                    ),
                ),
                "codex": (
                    _status("configured", setup_method="codex_cli"),
                    _status(
                        "cli_login_needs_api_key",
                        needs="api_key",
                        setup_method="codex_cli",
                        environment_key="OPENAI_API_KEY",
                    ),
                ),
            },
        ),
        (
            {"ANTHROPIC_API_KEY": "ant", "XAI_API_KEY": "xai", "OPENAI_API_KEY": "oa"},
            LOGGED_OUT,
            LOGGED_OUT,
            LOGGED_OUT,
            True,
            {
                "claude": (
                    _status("api_key_needs_cli_login", needs="cli_login", setup_method="api_key"),
                    _status(
                        "configured", setup_method="api_key", environment_key="ANTHROPIC_API_KEY"
                    ),
                ),
                "grok": (
                    _status("configured", setup_method="api_key", environment_key="XAI_API_KEY"),
                ) * 2,
                "codex": (
                    _status("configured", setup_method="api_key", environment_key="OPENAI_API_KEY"),
                ) * 2,
            },
        ),
        (
            {"ANTHROPIC_API_KEY": "ant"},
            LOGGED_OUT,
            LOGGED_OUT,
            LOGGED_OUT,
            False,
            {
                "claude": (
                    _status("api_key_needs_cli_login", needs="cli_login", setup_method="api_key"),
                    _status("missing_dependency", missing_dependency="anthropic"),
                ),
                "grok": (
                    _status("unconfigured", needs="api_key", environment_key="XAI_API_KEY"),
                ) * 2,
                "codex": (
                    _status("unconfigured", needs="api_key", environment_key="OPENAI_API_KEY"),
                ) * 2,
            },
        ),
    ],
)
def test_provider_status_projects_the_catalog_contract(
    admin_client,
    monkeypatch,
    keys,
    claude_login,
    grok_login,
    codex_login,
    sdk_available,
    expected,
):
    for key in ("ANTHROPIC_API_KEY", "XAI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in keys.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.find_spec",
        lambda _name: object() if sdk_available else None,
    )
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.grok_cli_token_is_present",
        lambda: grok_login.logged_in,
    )
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.codex_cli_access_token_is_present",
        lambda: codex_login.logged_in,
    )
    grok = GrokCliStatus(login=grok_login, model_names=("grok-4.6",))
    calls = _stub_cli_runners(
        monkeypatch, claude=claude_login, grok=grok, codex=codex_login,
    )
    refresh_provider_snapshots()

    client, _ = admin_client
    response = client.get("/api/settings/providers")

    assert response.status_code == 200
    actual = {item["provider"]: item for item in response.json()}
    for provider, item in actual.items():
        assert item["judge"]["state"] == expected[provider][1]["state"]
        assert item["judge"]["probed_at"] is not None
        assert set(item["cowriter_routes"]) == {"cli", "api"}
        assert item["cowriter"]["probed_at"] is not None
    assert all(count <= 1 for count in calls.values())


def test_grok_cli_token_configures_the_cowriter_but_not_the_judge_without_an_api_key(
    admin_client, monkeypatch,
):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.grok_cli_token_is_present", lambda: True,
    )
    _stub_cli_runners(
        monkeypatch,
        grok=GrokCliStatus(
            login=CliLogin(logged_in=True, auth_method="grok"),
            model_names=("grok-4.6",),
        ),
    )
    refresh_provider_snapshots()

    client, factory = admin_client
    with factory() as session:
        set_provider_routes(
            session,
            {"claude": "cli", "grok": "cli", "codex": "api"},
        )
        session.commit()
    statuses = {
        item["provider"]: item for item in client.get("/api/settings/providers").json()
    }
    grok = statuses["grok"]["cowriter"]
    assert grok["state"] == "configured"
    assert grok["setup_method"] == "grok_cli"
    judge = statuses["grok"]["judge"]
    assert judge["state"] == "cli_login_needs_api_key"
    assert judge["needs"] == "api_key"
    assert judge["setup_method"] == "grok_cli"
    assert judge["environment_key"] == "XAI_API_KEY"

    settings = client.get("/api/settings/cowriter").json()
    assert settings["models_by_provider"]["grok"]
    saved = client.put(
        "/api/settings/cowriter",
        json={"provider": "grok", "model": "grok-4.6"},
    )

    assert saved.status_code == 200
    assert saved.json()["provider"] == "grok"

    judge_saved = client.put(
        "/api/settings/judge",
        json={"provider": "grok", "model": "grok-4.6"},
    )

    assert judge_saved.status_code == 422
    assert judge_saved.json()["detail"]["surface"] == "judge"
    assert judge_saved.json()["detail"]["status"]["state"] == "cli_login_needs_api_key"


@pytest.mark.parametrize("provider", ["claude", "grok", "codex"])
def test_refresh_records_unparseable_cli_output_as_unconfigured(
    admin_client, monkeypatch, provider,
):
    for key in ("ANTHROPIC_API_KEY", "XAI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    _stub_cli_runners(monkeypatch)

    if provider == "claude":
        monkeypatch.setattr("songmaker_cli.agent_cli._claude_output", lambda _binary: "not JSON")
    else:
        monkeypatch.setattr("songmaker_cli.agent_cli._cli_output", lambda *_args: "not status")
    refresh_provider_snapshots()
    from songmaker_cli.cowriter.catalog import UnconfiguredProvider, provider_snapshot

    snapshot = provider_snapshot(provider)
    assert snapshot is not None
    assert isinstance(snapshot.cowriter, UnconfiguredProvider)
    assert isinstance(snapshot.judge, UnconfiguredProvider)
    assert snapshot.probed_at is not None

    client, _ = admin_client
    response = client.get("/api/settings/providers")

    assert response.status_code == 200
    by_provider = {item["provider"]: item for item in response.json()}
    for surface in ("cowriter", "judge"):
        status = by_provider[provider][surface]
        assert status["state"] == "unconfigured"
        assert status["probed_at"] is not None


@pytest.mark.parametrize("provider", ["grok", "codex"])
def test_refresh_preserves_an_api_key_provider_when_its_cli_probe_fails(
    monkeypatch, provider,
):
    from songmaker_cli.agent_cli import AgentCliUnavailableError
    from songmaker_cli.cowriter.catalog import (
        ProviderRoute,
        ProviderRouteReadinessState,
        provider_snapshot,
        refresh_provider_snapshot,
    )

    def unavailable_cli(_provider: str) -> bool:
        raise AgentCliUnavailableError("unavailable")

    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog._cli_is_logged_in",
        unavailable_cli,
    )
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.list_provider_models",
        lambda name, _route: [f"{name}-model"],
    )

    snapshot = refresh_provider_snapshot(provider)

    assert snapshot == provider_snapshot(provider)
    assert snapshot.routes[ProviderRoute.CLI].readiness is ProviderRouteReadinessState.DISTURBED


def test_settings_responses_project_one_snapshot_generation_per_provider(
    admin_client, monkeypatch,
):
    from songmaker_cli.cowriter.catalog import ConfiguredProvider, ProviderSetupMethod

    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.get_provider_configuration",
        lambda provider, _surface: ConfiguredProvider(
            provider, ProviderSetupMethod.API_KEY, f"{provider.upper()}_API_KEY",
        ),
    )
    refresh_provider_snapshots()
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.provider_snapshot",
        lambda _provider: (_ for _ in ()).throw(AssertionError("individual snapshot read")),
    )

    client, _ = admin_client

    assert client.get("/api/settings/providers").status_code == 200
    assert client.get("/api/settings/cowriter").status_code == 200
    assert client.get("/api/settings/judge").status_code == 200


@pytest.mark.parametrize("provider", ["claude", "grok", "codex"])
def test_provider_status_treats_a_hanging_cli_as_logged_out(admin_client, monkeypatch, provider):
    from songmaker_cli import agent_cli

    for key in ("ANTHROPIC_API_KEY", "XAI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    _stub_cli_runners(monkeypatch)

    def timed_out():
        raise agent_cli.CliProbeBudgetExceeded("probe timed out")

    if provider == "claude":
        started = threading.Event()
        release = threading.Event()

        def _hanging_output(_binary: str) -> str | None:
            started.set()
            release.wait(timeout=1)
            return None

        monkeypatch.setattr("songmaker_cli.agent_cli._claude_output", _hanging_output)
        monkeypatch.setattr("songmaker_cli.agent_cli.CLI_PROBE_CALLER_TIMEOUT_SECONDS", 0.01)
    elif provider == "grok":
        monkeypatch.setattr(
            agent_cli._grok_status_probe,
            "get",
            timed_out,
        )
    else:
        monkeypatch.setattr(
            agent_cli._codex_login_probe,
            "get",
            timed_out,
        )

    client, _ = admin_client
    try:
        refresh_provider_snapshots()
        response = client.get("/api/settings/providers")
    finally:
        if provider == "claude":
            release.set()

    assert response.status_code == 200
    if provider == "claude":
        assert started.is_set()
    statuses = next(item for item in response.json() if item["provider"] == provider)
    assert statuses["cowriter"]["state"] != "configured"
    assert statuses["judge"]["state"] == "unconfigured"


def test_models_errors_cover_every_provider_not_only_the_saved_one(
    admin_client, monkeypatch, every_provider_is_configured,
):
    client, _ = admin_client
    client.put("/api/settings/cowriter", json={"provider": "codex", "model": "gpt-5.4"})

    def _list_provider_models(provider: str, _route: ProviderRoute) -> list[str]:
        if provider == "grok":
            raise ProviderUnavailableError(
                "grok", "grok is not configured: missing XAI_API_KEY",
            )
        return list(LIVE_CATALOG[provider])

    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.list_provider_models", _list_provider_models,
    )
    refresh_provider_snapshots()
    settings = client.get("/api/settings/cowriter").json()
    assert settings["provider"] == "codex"
    assert settings["models_by_provider"]["grok"] == []
    assert "codex" not in settings["models_errors"]
    assert settings["models_errors"]["grok"] == "Selected route failed."


def test_claude_cli_stderr_stays_out_of_model_catalog_settings_errors(
    admin_client, monkeypatch,
):
    import songmaker_cli.cowriter.catalog as catalog

    client, _ = admin_client
    secret_stderr = "/home/operator/.claude/credentials.json: permission denied"
    def _configured_catalog(provider, surface, settings):
        if provider == "claude":
            return catalog.ConfiguredProvider(
                provider, catalog.ProviderSetupMethod.CLAUDE_CLI,
            )
        return catalog.ConfiguredProvider(
            provider, catalog.ProviderSetupMethod.API_KEY,
            f"{provider.upper()}_API_KEY",
        )

    def _list_provider_models(provider, _route):
        if provider == "claude":
            return catalog._list_claude_cli_models()
        return list(LIVE_CATALOG[provider])

    monkeypatch.setattr(catalog, "_provider_configuration", _configured_catalog)
    monkeypatch.setattr(catalog, "list_provider_models", _list_provider_models)
    monkeypatch.setattr(catalog, "_cli_is_logged_in", lambda _provider: True)
    monkeypatch.setattr(
        "songmaker_cli.claude.provider._find_claude_binary",
        lambda: "/usr/bin/claude",
    )
    monkeypatch.setattr(
        "songmaker_cli.claude.provider.subprocess.run",
        lambda *args, **kwargs: MagicMock(
            stdout="", stderr=secret_stderr, returncode=1,
        ),
    )

    refresh_provider_snapshots()

    response = client.get("/api/settings/cowriter")
    assert response.status_code == 200
    assert secret_stderr not in response.json()["models_errors"]["claude"]
    assert response.json()["models_errors"]["claude"] == "Model catalogue response was invalid."

    response = client.put(
        "/api/settings/cowriter",
        json={"provider": "claude", "model": "sonnet"},
    )
    assert response.status_code == 422
    assert secret_stderr not in response.text


def test_provider_status_requires_admin(admin_client):
    client, _ = admin_client
    client.app.dependency_overrides[get_current_user] = _fake_user("u-plain", "user")
    try:
        resp = client.get("/api/settings/providers")
    finally:
        client.app.dependency_overrides[get_current_user] = _fake_user("u-test", "admin")

    assert resp.status_code == 403


def test_settings_requests_do_not_start_a_provider_probe_without_a_snapshot(
    admin_client, monkeypatch,
):
    calls = 0

    def _counting_popen(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("settings request started a process")

    monkeypatch.setattr("songmaker_cli.agent_cli.subprocess.Popen", _counting_popen)
    client, _ = admin_client

    cowriter = client.get("/api/settings/cowriter")
    judge = client.get("/api/settings/judge")
    providers = client.get("/api/settings/providers")

    assert cowriter.status_code == 200
    assert judge.status_code == 200
    assert providers.status_code == 200
    assert set(cowriter.json()["probed_at"].values()) == {None}
    assert set(judge.json()["probed_at"].values()) == {None}
    grok_cli = cowriter.json()["provider_routes_status"]["grok"]["cli"]["readiness"]
    assert grok_cli["state"] == "unverified"
    assert grok_cli["capability"] == "tools_available"
    assert grok_cli["reason"] is None
    for provider in providers.json():
        for surface in ("cowriter", "judge"):
            assert provider[surface]["state"] == "unverified"
            assert provider[surface]["probed_at"] is None
    response = client.put(
        "/api/settings/cowriter",
        json={"provider": "grok", "model": "grok-4.6"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Selected route is unverified"
    assert calls == 0


def test_cowriter_put_rejects_an_unready_selected_route(admin_client, monkeypatch):
    client, _ = admin_client
    from songmaker_cli.settings import get_settings

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    refresh_provider_snapshots()

    response = client.put(
        "/api/settings/cowriter",
        json={
            "provider": "claude",
            "model": "sonnet",
            "provider_routes": {"claude": "api", "grok": "api", "codex": "api"},
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "api_key_not_set"


def test_judge_models_errors_cover_every_provider_not_only_the_saved_one(
    admin_client, monkeypatch, every_provider_is_configured,
):
    client, _ = admin_client
    client.put("/api/settings/judge", json={"provider": "codex", "model": "gpt-5.4"})

    def _list_provider_models(provider: str, _route: ProviderRoute) -> list[str]:
        if provider == "grok":
            raise ProviderUnavailableError(
                "grok", "grok is not configured: missing XAI_API_KEY",
            )
        return list(LIVE_CATALOG[provider])

    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.list_provider_models", _list_provider_models,
    )
    refresh_provider_snapshots()
    settings = client.get("/api/settings/judge").json()
    assert settings["provider"] == "codex"
    assert settings["models_by_provider"]["grok"] == []
    assert "codex" not in settings["models_errors"]
    assert settings["models_errors"]["grok"] == "Selected route failed."


def test_cowriter_save_with_unchanged_provider_and_model_survives_a_down_catalog(
    admin_client, every_provider_is_configured,
):
    client, _ = admin_client
    saved = client.put(
        "/api/settings/cowriter",
        json={"provider": "grok", "model": "grok-4.6", "tail_token_budget": 20000},
    )
    assert saved.status_code == 200

    def _down(provider: str, _route: ProviderRoute) -> list[str]:
        raise ProviderModelCatalogUnavailableError(
            provider, f"could not list {provider} models",
        )

    with (
        patch("songmaker_cli.settings_api._surface_status", side_effect=AssertionError),
        patch("songmaker_cli.cowriter.catalog.list_provider_models", side_effect=_down),
    ):
        budget_only = client.put(
            "/api/settings/cowriter",
            json={"provider": "grok", "model": "grok-4.6", "tail_token_budget": 30000},
        )

    assert budget_only.status_code == 200
    assert budget_only.json()["tail_token_budget"] == 30000
    assert budget_only.json()["model"] == "grok-4.6"


def test_cowriter_budget_save_with_default_settings_requires_the_surface_check(admin_client):
    client, factory = admin_client
    with factory() as session:
        provider = get_cowriter_provider(session)
        model = get_cowriter_model(session, provider)
        original_state = _stored_cowriter_state(session)

    status = ProviderSurfaceStatus(
        state=ProviderSurfaceState.UNCONFIGURED,
        needs="api_key",
        environment_key="ANTHROPIC_API_KEY",
    )
    with patch("songmaker_cli.settings_api._surface_status", return_value=status):
        response = client.put(
            "/api/settings/cowriter",
            json={
                "provider": provider,
                "model": model,
                "tail_token_budget": 12000,
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Selected route is unverified"
    with factory() as session:
        assert _stored_cowriter_state(session) == original_state


def test_cowriter_save_with_an_incomplete_stored_pair_requires_the_surface_check(admin_client):
    client, factory = admin_client
    with factory() as session:
        set_claude_model(session, SETTING_COWRITER_PROVIDER, "claude")
        set_claude_model(session, SETTING_COWRITER_MODEL, "")
        session.commit()
    with factory() as session:
        original_state = _stored_cowriter_state(session)
    status = ProviderSurfaceStatus(
        state=ProviderSurfaceState.UNCONFIGURED,
        needs="api_key",
        environment_key="ANTHROPIC_API_KEY",
    )

    with patch("songmaker_cli.settings_api._surface_status", return_value=status):
        response = client.put(
            "/api/settings/cowriter",
            json={"provider": "claude", "model": "", "tail_token_budget": 12000},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Selected route is unverified"
    with factory() as session:
        assert _stored_cowriter_state(session) == original_state


def test_cowriter_save_that_actually_changes_the_model_still_needs_a_live_catalog(
    admin_client, every_provider_is_configured,
):
    client, factory = admin_client
    client.put(
        "/api/settings/cowriter",
        json={"provider": "grok", "model": "grok-4.6"},
    )
    with factory() as session:
        original_state = _stored_cowriter_state(session)

    def _down(provider: str, _route: ProviderRoute) -> list[str]:
        raise ProviderModelCatalogUnavailableError(
            provider, f"could not list {provider} models",
        )

    with patch("songmaker_cli.cowriter.catalog.list_provider_models", side_effect=_down):
        refresh_provider_snapshots()
        resp = client.put(
            "/api/settings/cowriter",
            json={"provider": "grok", "model": "grok-4.5"},
        )

    assert resp.status_code == 422
    with factory() as session:
        assert _stored_cowriter_state(session) == original_state


def test_invalid_cowriter_budget_does_not_persist_a_validated_provider_change(
    admin_client, every_provider_is_configured,
):
    client, factory = admin_client
    assert client.put(
        "/api/settings/cowriter",
        json={"provider": "grok", "model": "grok-4.6", "tail_token_budget": 20000},
    ).status_code == 200
    with factory() as session:
        original_state = _stored_cowriter_state(session)

    response = client.put(
        "/api/settings/cowriter",
        json={
            "provider": "codex",
            "model": "gpt-5.4",
            "tail_token_budget": 1_000_000,
        },
    )

    assert response.status_code == 422
    with factory() as session:
        assert _stored_cowriter_state(session) == original_state


def test_judge_save_with_default_settings_requires_the_surface_check(admin_client):
    client, factory = admin_client
    with factory() as session:
        provider = get_judge_provider(session)
        model = get_judge_model(session, provider)

    status = ProviderSurfaceStatus(
        state=ProviderSurfaceState.UNCONFIGURED,
        needs="api_key",
        environment_key="ANTHROPIC_API_KEY",
    )
    with patch("songmaker_cli.settings_api._surface_status", return_value=status):
        response = client.put(
            "/api/settings/judge",
            json={"provider": provider, "model": model},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "provider": provider,
        "surface": "judge",
        "status": status.model_dump(exclude_none=True),
    }
    with factory() as session:
        assert get_raw_stored_judge_settings(session).provider is None


def test_judge_save_with_a_persisted_pair_always_checks_surface_and_catalog(
    admin_client, every_provider_is_configured,
):
    client, factory = admin_client
    request = {"provider": "grok", "model": "grok-4.6"}
    assert client.put("/api/settings/judge", json=request).status_code == 200
    with factory() as session:
        original = get_raw_stored_judge_settings(session)
    unavailable = ProviderSurfaceStatus(
        state=ProviderSurfaceState.UNCONFIGURED,
        needs="api_key",
        environment_key="XAI_API_KEY",
    )

    with patch("songmaker_cli.settings_api._surface_status", return_value=unavailable):
        surface_response = client.put("/api/settings/judge", json=request)

    assert surface_response.status_code == 422
    assert surface_response.json()["detail"] == {
        "provider": "grok",
        "surface": "judge",
        "status": unavailable.model_dump(exclude_none=True),
    }
    with factory() as session:
        assert get_raw_stored_judge_settings(session) == original

    with (
        patch(
            "songmaker_cli.settings_api._surface_status",
            return_value=ProviderSurfaceStatus(state=ProviderSurfaceState.CONFIGURED),
        ),
        patch(
            "songmaker_cli.settings_api._models_for_provider",
            return_value=([], "could not list grok models"),
        ),
    ):
        catalog_response = client.put("/api/settings/judge", json=request)

    assert catalog_response.status_code == 503
    with factory() as session:
        assert get_raw_stored_judge_settings(session) == original


def test_openai_adapter_rejects_malformed_tool_arguments_without_calling_tool():
    with pytest.raises(ProviderUnavailableError) as raised:
        _parse_tool_call(
            {
                "id": "call-1",
                "function": {"name": "list_albums", "arguments": "not-json"},
            },
            "grok",
        )

    assert raised.value.reason.code.value == "tool_protocol_error"
