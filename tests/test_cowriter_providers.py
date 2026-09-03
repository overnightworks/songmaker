"""Co-writer provider switch (#34). Models come from the live catalog."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from conftest import TEST_SECRET, make_fake_redis, refresh_provider_snapshots
from fastapi import FastAPI
from fastapi.testclient import TestClient

from songmaker_cli.agent_cli import LOGGED_OUT, CliLogin, GrokCliStatus
from songmaker_cli.api_models.settings import ProviderSurfaceState, ProviderSurfaceStatus
from songmaker_cli.app_context import AppContext
from songmaker_cli.claude.provider import (
    CLAUDE_CLI_MODEL_CATALOG_ERROR,
    FinalEvent,
    ToolCallEvent,
)
from songmaker_cli.constants import (
    COWRITER_MAX_TOOL_ROUNDS,
    SETTING_CLAUDE_SCORING_MODEL,
    SETTING_COWRITER_MODEL,
    SETTING_COWRITER_PROVIDER,
    SETTING_JUDGE_MODEL,
    SETTING_JUDGE_PROVIDER,
)
from songmaker_cli.cowriter.catalog import ProviderSurface
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
from songmaker_cli.db.models import Album, AvailableModel, ChatMessage, Job, Song, User
from songmaker_cli.db.queries.settings import (
    get_cowriter_model,
    get_cowriter_provider,
    get_cowriter_tail_token_budget,
    get_judge_model,
    get_judge_provider,
    get_raw_stored_cowriter_settings,
    get_raw_stored_judge_settings,
    set_claude_model,
)
from songmaker_cli.mcp_server.tools import tool_create_song
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

LIVE_CATALOG = {
    "claude": ["claude-opus-4-6", "claude-sonnet-4-6"],
    "grok": ["grok-4.6", "grok-4.5"],
    "codex": ["gpt-5.4"],
}


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
        lambda provider: aliases[provider],
    )
    refresh_provider_snapshots()

    settings = client.get("/api/settings/cowriter")

    assert settings.status_code == 200
    assert settings.json()["model"] == "claude-opus-4-6"
    assert settings.json()["models_by_provider"]["claude"] == [
        "haiku", "opus", "sonnet", "claude-opus-4-6",
    ]
    saved = client.put(
        "/api/settings/cowriter",
        json={"provider": "claude", "model": "claude-opus-4-6"},
    )
    assert saved.status_code == 200


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
    actual = {item["provider"]: (item["cowriter"], item["judge"]) for item in response.json()}
    for statuses in actual.values():
        for status in statuses:
            assert status.pop("probed_at") is not None
    assert actual == expected
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

    client, _ = admin_client
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
        ConfiguredProvider,
        ProviderSetupMethod,
        provider_snapshot,
        refresh_provider_snapshot,
    )

    def unavailable_cli(_provider: str) -> None:
        raise AgentCliUnavailableError("unavailable")

    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog._refresh_cli_login",
        unavailable_cli,
    )
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.get_provider_configuration",
        lambda name, _surface: ConfiguredProvider(
            name, ProviderSetupMethod.API_KEY, f"{name.upper()}_API_KEY",
        ),
    )
    monkeypatch.setattr(
        "songmaker_cli.cowriter.catalog.list_provider_models",
        lambda name: [f"{name}-model"],
    )

    snapshot = refresh_provider_snapshot(provider)

    assert snapshot == provider_snapshot(provider)
    assert snapshot.cowriter == ConfiguredProvider(
        provider, ProviderSetupMethod.API_KEY, f"{provider.upper()}_API_KEY",
    )
    assert snapshot.models == (f"{provider}-model",)


def test_settings_responses_project_one_snapshot_generation_per_provider(
    admin_client, monkeypatch,
):
    from songmaker_cli.cowriter.catalog import ConfiguredProvider, ProviderSetupMethod

    monkeypatch.setattr("songmaker_cli.cowriter.catalog._refresh_cli_login", lambda _provider: None)
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
    assert {
        surface["state"] for surface in statuses.values() if isinstance(surface, dict)
    } == {"unconfigured"}


def test_models_errors_cover_every_provider_not_only_the_saved_one(
    admin_client, monkeypatch, every_provider_is_configured,
):
    client, _ = admin_client
    client.put("/api/settings/cowriter", json={"provider": "codex", "model": "gpt-5.4"})

    def _list_provider_models(provider: str) -> list[str]:
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
    assert "XAI_API_KEY" in settings["models_errors"]["grok"]


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

    def _list_provider_models(provider):
        if provider == "claude":
            return catalog._list_claude_cli_models()
        return list(LIVE_CATALOG[provider])

    monkeypatch.setattr(catalog, "_provider_configuration", _configured_catalog)
    monkeypatch.setattr(catalog, "list_provider_models", _list_provider_models)
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

    for path in ("/api/settings/cowriter", "/api/settings/judge"):
        response = client.get(path)
        assert response.status_code == 200
        assert secret_stderr not in response.json()["models_errors"]["claude"]
        assert response.json()["models_errors"]["claude"] == CLAUDE_CLI_MODEL_CATALOG_ERROR

    response = client.put(
        "/api/settings/cowriter",
        json={"provider": "claude", "model": "sonnet"},
    )
    assert response.status_code == 503
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
    for provider in providers.json():
        for surface in ("cowriter", "judge"):
            assert provider[surface]["state"] == "unverified"
            assert provider[surface]["probed_at"] is None
    response = client.put(
        "/api/settings/cowriter",
        json={"provider": "grok", "model": "grok-4.6"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["status"]["state"] == "unverified"
    assert calls == 0


@pytest.mark.parametrize(
    ("path", "surface"),
    [
        ("/api/settings/cowriter", ProviderSurface.CO_WRITER),
        ("/api/settings/judge", ProviderSurface.JUDGE),
    ],
)
@pytest.mark.parametrize(
    "status",
    [
        ProviderSurfaceStatus(state=ProviderSurfaceState.CONFIGURED),
        ProviderSurfaceStatus(
            state=ProviderSurfaceState.CLI_LOGIN_NEEDS_API_KEY,
            needs="api_key",
            environment_key="XAI_API_KEY",
        ),
        ProviderSurfaceStatus(
            state=ProviderSurfaceState.API_KEY_NEEDS_CLI_LOGIN,
            needs="cli_login",
        ),
        ProviderSurfaceStatus(
            state=ProviderSurfaceState.MISSING_DEPENDENCY,
            missing_dependency="anthropic",
        ),
        ProviderSurfaceStatus(
            state=ProviderSurfaceState.UNCONFIGURED,
            needs="api_key",
            environment_key="XAI_API_KEY",
        ),
    ],
)
def test_provider_change_requires_a_configured_surface(
    admin_client,
    monkeypatch,
    path,
    surface,
    status,
):
    calls = []

    def _surface_status(provider, actual_surface):
        calls.append((provider, actual_surface))
        return status

    monkeypatch.setattr("songmaker_cli.settings_api._surface_status", _surface_status)
    monkeypatch.setattr(
        "songmaker_cli.settings_api._models_for_provider",
        lambda provider, _active_model: (list(LIVE_CATALOG[provider]), None),
    )
    client, factory = admin_client
    with factory() as session:
        original_cowriter_state = _stored_cowriter_state(session)

    response = client.put(path, json={"provider": "grok", "model": "grok-4.6"})

    assert calls == [("grok", surface)]
    if status.state is ProviderSurfaceState.CONFIGURED:
        assert response.status_code == 200
    else:
        assert response.status_code == 422
        assert response.json()["detail"] == {
            "provider": "grok",
            "surface": surface.value,
            "status": status.model_dump(exclude_none=True),
        }
        if path == "/api/settings/cowriter":
            with factory() as session:
                assert _stored_cowriter_state(session) == original_cowriter_state


@pytest.mark.parametrize(
    ("path", "surface"),
    [
        ("/api/settings/cowriter", ProviderSurface.CO_WRITER),
        ("/api/settings/judge", ProviderSurface.JUDGE),
    ],
)
def test_model_change_requires_a_configured_surface(
    admin_client,
    monkeypatch,
    path,
    surface,
):
    calls = []
    statuses = iter([
        ProviderSurfaceStatus(state=ProviderSurfaceState.CONFIGURED),
        ProviderSurfaceStatus(
            state=ProviderSurfaceState.UNCONFIGURED,
            needs="api_key",
            environment_key="XAI_API_KEY",
        ),
    ])

    def _surface_status(provider, actual_surface):
        calls.append((provider, actual_surface))
        return next(statuses)

    monkeypatch.setattr("songmaker_cli.settings_api._surface_status", _surface_status)
    monkeypatch.setattr(
        "songmaker_cli.settings_api._models_for_provider",
        lambda provider, _active_model: (list(LIVE_CATALOG[provider]), None),
    )
    client, factory = admin_client

    first = client.put(path, json={"provider": "grok", "model": "grok-4.6"})
    with factory() as session:
        original_cowriter_state = _stored_cowriter_state(session)
    response = client.put(path, json={"provider": "grok", "model": "grok-4.5"})

    assert first.status_code == 200
    assert response.status_code == 422
    assert calls == [("grok", surface)] * 2
    assert response.json()["detail"] == {
        "provider": "grok",
        "surface": surface.value,
        "status": {
            "state": "unconfigured",
            "needs": "api_key",
            "environment_key": "XAI_API_KEY",
        },
    }
    if path == "/api/settings/cowriter":
        with factory() as session:
            assert _stored_cowriter_state(session) == original_cowriter_state


def test_judge_models_errors_cover_every_provider_not_only_the_saved_one(
    admin_client, monkeypatch, every_provider_is_configured,
):
    client, _ = admin_client
    client.put("/api/settings/judge", json={"provider": "codex", "model": "gpt-5.4"})

    def _list_provider_models(provider: str) -> list[str]:
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
    assert "XAI_API_KEY" in settings["models_errors"]["grok"]


def test_cowriter_save_with_unchanged_provider_and_model_survives_a_down_catalog(
    admin_client, every_provider_is_configured,
):
    client, _ = admin_client
    saved = client.put(
        "/api/settings/cowriter",
        json={"provider": "grok", "model": "grok-4.6", "tail_token_budget": 20000},
    )
    assert saved.status_code == 200

    def _down(provider: str) -> list[str]:
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
    assert response.json()["detail"] == {
        "provider": provider,
        "surface": "cowriter",
        "status": status.model_dump(exclude_none=True),
    }
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
    assert response.json()["detail"] == {
        "provider": "claude",
        "surface": "cowriter",
        "status": status.model_dump(exclude_none=True),
    }
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

    def _down(provider: str) -> list[str]:
        raise ProviderModelCatalogUnavailableError(
            provider, f"could not list {provider} models",
        )

    with patch("songmaker_cli.cowriter.catalog.list_provider_models", side_effect=_down):
        refresh_provider_snapshots()
        resp = client.put(
            "/api/settings/cowriter",
            json={"provider": "grok", "model": "grok-4.5"},
        )

    assert resp.status_code == 503
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
    with pytest.raises(ProviderUnavailableError, match="invalid tool arguments"):
        _parse_tool_call(
            {
                "id": "call-1",
                "function": {"name": "list_albums", "arguments": "not-json"},
            },
            "grok",
        )
