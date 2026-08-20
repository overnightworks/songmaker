"""Co-writer provider switch (#34). Models come from the live catalog."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import TEST_SECRET, make_fake_redis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from songmaker_cli.app_context import AppContext
from songmaker_cli.claude.provider import FinalEvent
from songmaker_cli.constants import SETTING_CLAUDE_SCORING_MODEL
from songmaker_cli.cowriter.tools import execute_cowriter_tool
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, AvailableModel, ChatMessage, Song, User
from songmaker_cli.db.queries.settings import set_claude_model
from songmaker_cli.mcp_server.tools import tool_create_song
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

LIVE_CATALOG = {
    "claude": ["claude-opus-4-6", "claude-sonnet-4-6"],
    "grok": ["grok-4.6", "grok-4.5"],
    "codex": ["gpt-5.4"],
}


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
        lambda provider: list(LIVE_CATALOG[provider]),
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


def test_model_must_be_in_the_live_catalog(admin_client):
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


def test_each_saved_provider_calls_only_itself(admin_client):
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


def test_missing_credentials_named_error_no_persist(admin_client, monkeypatch):
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
    assert "grok" in err["message"]
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


def test_cowriter_provider_switch_keeps_scoring_model(admin_client):
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


def test_openai_adapter_emits_same_event_types(admin_client):
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
