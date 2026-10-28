"""Co-writer provider switch (#34). Models come from the live catalog."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from agent_providers.catalog import ProviderRoute
from agent_providers.errors import (
    ProviderModelCatalogUnavailableError,
    ProviderUnavailableError,
    SafeRouteReasonCode,
    normalize_route_failure,
)
from agent_providers.process import LOGGED_OUT, CliLogin, GrokCliStatus
from conftest import (
    TEST_SECRET,
    make_authenticated_user,
    make_router_app,
    make_router_ctx,
    override_provider_runtime,
    refresh_provider_snapshots,
    seed_judge_route,
    web_client,
)
from fake_agent_service import attach_cowriter_service

from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.constants import (
    COWRITER_DEFAULT_TAIL_TOKEN_BUDGET,
    SETTING_COVER_MODEL,
    SETTING_COVER_PROVIDER,
    SETTING_COVER_ROUTE,
    SETTING_JUDGE_MODEL,
    SETTING_JUDGE_PROVIDER,
    SETTING_JUDGE_ROUTE,
)
from songmaker_cli.cowriter.tools import execute_cowriter_tool
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import (
    Album,
    AuditLog,
    AvailableModel,
    Generation,
    Job,
    RateLimitSetting,
    Song,
    User,
    Version,
)
from songmaker_cli.db.queries.settings import (
    get_cover_settings,
    get_judge_model,
    get_judge_provider,
    get_raw_stored_judge_settings,
    set_claude_model,
)
from songmaker_cli.mcp_server.tools import tool_create_song
from songmaker_cli.settings import get_settings

LIVE_CATALOG = {
    "claude": ["claude-opus-4-6", "claude-sonnet-4-6"],
    "grok": ["grok-4.6", "grok-4.5"],
    "codex": ["gpt-5.4"],
}


@pytest.fixture(autouse=True)
def _clear_agent_cli_caches(monkeypatch):
    from agent_providers.process import clear_agent_cli_caches

    from songmaker_cli import provider_status

    monkeypatch.setattr(provider_status, "_provider_snapshots", {})

    clear_agent_cli_caches()
    yield
    clear_agent_cli_caches()


def _stream_events(response) -> list[dict]:
    events: list[dict] = []
    for line in response.iter_lines():
        if not line:
            continue
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def _seed(session, user_id: str) -> None:
    seed_judge_route(session)
    session.add(User(
        id=user_id, username=f"user-{user_id}", role="admin",
    ))
    session.flush()
    session.add(Album(id="alb1", title="Rock", artist="B", created_by=user_id))
    session.add(Song(id="s1", title="Thunder", album_id="alb1", track_number=1))
    session.query(AvailableModel).filter(
        AvailableModel.id.in_(["turbo", "sft"]),
    ).update({"is_active": True}, synchronize_session=False)
    session.commit()


@pytest.fixture
def admin_client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "agent_providers.catalog.list_provider_models",
        lambda provider, _route: list(LIVE_CATALOG[provider]),
    )
    factory = init_db(tmp_path / "cowriter.db")
    with factory() as session:
        _seed(session, "u-test")
    app = make_router_app(
        make_router_ctx(tmp_path, db=factory),
        user=make_authenticated_user("u-test", role="admin", username="u-u-test"),
    )
    return web_client(app), factory


def _stored_choice_rows(factory) -> dict[str, str | None]:
    with factory() as session:
        return {
            row.setting_key: row.value_text
            for row in session.query(RateLimitSetting).filter(
                RateLimitSetting.setting_key.in_(
                    [
                        "cowriter_provider",
                        "cowriter_model",
                        "cowriter_model_grok",
                        "provider_routes",
                    ],
                ),
            )
        }


def test_c15_get_cowriter_settings_answers_the_budget_alone(admin_client):
    client, _ = admin_client

    response = client.get("/api/settings/cowriter")

    assert response.status_code == 200
    assert response.json() == {
        "tail_token_budget": COWRITER_DEFAULT_TAIL_TOKEN_BUDGET,
    }


def test_c15_put_cowriter_settings_saves_the_budget_and_records_the_audit_line(admin_client):
    client, factory = admin_client

    response = client.put("/api/settings/cowriter", json={"tail_token_budget": 6000})

    assert response.status_code == 200
    assert response.json()["tail_token_budget"] == 6000
    assert client.get("/api/settings/cowriter").json()["tail_token_budget"] == 6000
    with factory() as session:
        assert session.query(AuditLog).one().detail == "tail_token_budget=6000"


@pytest.mark.parametrize(
    "extra",
    [
        {"provider": "grok"},
        {"model": "grok-4.6"},
        {"provider_routes": {"claude": "cli", "grok": "cli", "codex": "cli"}},
    ],
)
def test_c15_put_cowriter_settings_refuses_a_choice_field_and_saves_nothing(admin_client, extra):
    client, factory = admin_client
    with factory() as session:
        set_claude_model(session, "cowriter_provider", "grok")
        set_claude_model(session, "cowriter_model", "grok-4.6")
        session.commit()
    rows_before = _stored_choice_rows(factory)

    response = client.put(
        "/api/settings/cowriter", json={"tail_token_budget": 6000, **extra},
    )

    assert response.status_code == 422
    assert client.get("/api/settings/cowriter").json()["tail_token_budget"] == (
        COWRITER_DEFAULT_TAIL_TOKEN_BUDGET
    )
    assert _stored_choice_rows(factory) == rows_before


def test_c15_put_cowriter_settings_leaves_the_stored_choice_rows_unread_and_unchanged(admin_client):
    client, factory = admin_client
    with factory() as session:
        set_claude_model(session, "cowriter_provider", "retired-provider")
        set_claude_model(session, "cowriter_model_grok", "grok-4.6")
        session.commit()
    rows_before = _stored_choice_rows(factory)

    assert client.get("/api/settings/cowriter").status_code == 200
    assert client.put("/api/settings/cowriter", json={"tail_token_budget": 6000}).status_code == 200

    assert _stored_choice_rows(factory) == rows_before


def test_c15_put_cowriter_settings_refuses_a_budget_out_of_range(admin_client):
    client, _ = admin_client

    response = client.put("/api/settings/cowriter", json={"tail_token_budget": 1_000_000})

    assert response.status_code == 422


def _save_removed_judge_provider(factory) -> None:
    with factory() as session:
        set_claude_model(session, SETTING_JUDGE_PROVIDER, "retired-provider")
        set_claude_model(session, SETTING_JUDGE_MODEL, "retired-model")
        session.commit()


def test_raw_stored_judge_settings_preserve_the_unresolved_pair(admin_client):
    _, factory = admin_client
    _save_removed_judge_provider(factory)

    with factory() as session:
        stored = get_raw_stored_judge_settings(session)

    assert stored.provider == "retired-provider"
    assert stored.model == "retired-model"


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


def test_judge_put_keeps_a_replacement_whose_provider_is_not_configured(admin_client):
    """Ruled line 8: the unusable choice is stored, the row names the reason."""
    client, factory = admin_client
    _save_removed_judge_provider(factory)
    override_provider_runtime(xai_api_key=None)
    refresh_provider_snapshots()

    response = client.put("/api/settings/judge", json={"provider": "grok", "model": ""})

    assert response.status_code == 200
    assert response.json()["provider"] == "grok"
    assert response.json()["models_by_provider"]["grok"] == []
    with factory() as session:
        stored = get_raw_stored_judge_settings(session)
    assert (stored.provider, stored.model) == ("grok", "")


def test_claude_api_catalog_is_ready_for_the_judge(
    admin_client, every_provider_is_configured,
):
    client, _ = admin_client

    refresh_provider_snapshots()
    judge = client.get("/api/settings/judge").json()
    claude_api = judge["provider_routes_status"]["claude"]["api"]
    assert claude_api["models"] == LIVE_CATALOG["claude"]
    assert claude_api["readiness"]["state"] == "ready"
    assert claude_api["readiness"]["capability"] == "tools_available"
    assert claude_api["readiness"]["reason"] is None
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
    assert providers["claude"]["cowriter_routes"]["api"]["readiness"]["state"] == "ready"


def test_cowriter_put_requires_an_admin(admin_client):
    client, _ = admin_client
    client.app.dependency_overrides[get_current_user] = lambda: make_authenticated_user(
        "u-plain", username="u-u-plain"
    )
    try:
        response = client.put(
            "/api/settings/cowriter",
            json={"tail_token_budget": 6000},
        )
    finally:
        client.app.dependency_overrides[get_current_user] = lambda: make_authenticated_user(
            "u-test", role="admin", username="u-u-test"
        )

    assert response.status_code == 403


def test_chat_turns_beyond_the_chat_rate_limit_are_refused(admin_client, monkeypatch):
    client, factory = admin_client
    monkeypatch.setenv("CHAT_RATE_LIMIT_USER", "2")
    get_settings.cache_clear()
    attach_cowriter_service(client, factory, monkeypatch, "u-test")

    statuses = [
        client.post("/api/chat/turn", json={"message": "hi"}).status_code for _ in range(3)
    ]

    assert statuses == [200, 200, 429]


def test_create_song_tool_hits_canonical_function(admin_client):
    _, factory = admin_client
    user = make_authenticated_user("u-test", role="admin", username="u-u-test")
    with factory() as session:
        outcome = execute_cowriter_tool(
            session, user, "create_song",
            {"album_id": "alb1", "title": "FromCatalog", "lyrics": "a"},
        )
        via_catalog = outcome.content
        assert outcome.is_error is False
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
    user = make_authenticated_user("u-test", role="admin", username="u-u-test")
    with factory() as session:
        outcome = execute_cowriter_tool(
            session, user, "rename_song",
            {"song_id": "s1", "title": "Renamed Track"},
        )
        assert outcome.is_error is False
    with factory() as session:
        song = session.query(Song).filter_by(id="s1").one()
        assert song.title == "Renamed Track"
        assert song.slug == "renamed-track"


def test_shared_cowriter_tool_executor_creates_an_immutable_song_version(admin_client):
    """The Grok and Codex executor takes the same version-writing path as MCP."""
    _, factory = admin_client
    user = make_authenticated_user("u-test", role="admin", username="u-u-test")
    with factory() as session:
        original = Version(
            id="v1", song_id="s1", version_number=1, lyrics="old lyrics",
        )
        session.add(original)
        session.flush()
        session.add(Generation(
            id="g1", song_id="s1", version_id=original.id, generation_number=1,
            mp3_path="u-test/g1.mp3",
        ))
        session.commit()

    with factory() as session:
        outcome = execute_cowriter_tool(
            session, user, "update_song_lyrics",
            {"song_id": "s1", "lyrics": "new lyrics"},
        )

    assert outcome.is_error is False
    assert "Updated lyrics in v2" in outcome.content
    with factory() as session:
        song = session.query(Song).filter_by(id="s1").one()
        assert [(version.version_number, version.lyrics) for version in song.versions] == [
            (1, "old lyrics"),
            (2, "new lyrics"),
        ]
        assert session.query(Generation).filter_by(id="g1").one().version_id == "v1"


def test_suggest_album_cover_tool_hits_the_canonical_admission_owner(admin_client):
    _, factory = admin_client
    user = make_authenticated_user("u-test", role="admin", username="u-u-test")
    with factory() as session:
        outcome = execute_cowriter_tool(
            session, user, "suggest_album_cover", {"album_id": "alb1"},
        )
        assert outcome.is_error is False
        assert '"status": "queued"' in outcome.content

    with factory() as session:
        job = session.query(Job).filter_by(album_id="alb1").one()
        assert job.type == "cover"


_API_KEY_FIELD_BY_ENVIRONMENT = {
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "XAI_API_KEY": "xai_api_key",
    "OPENAI_API_KEY": "openai_api_key",
}


def _configure_only_these_api_keys(**keys_by_environment: str) -> None:
    """Leave the named provider API keys configured and every other one unset."""
    override_provider_runtime(**{
        field: keys_by_environment.get(environment)
        for environment, field in _API_KEY_FIELD_BY_ENVIRONMENT.items()
    })


def _route_states(cli: str, api: str) -> dict[str, str]:
    return {"cli": cli, "api": api}


def _route_readiness(provider_status: dict) -> dict[str, dict]:
    return {
        route: status["readiness"]
        for route, status in provider_status["cowriter_routes"].items()
    }


def _stub_cli_runners(
    monkeypatch,
    *,
    claude: CliLogin = LOGGED_OUT,
    grok: GrokCliStatus | None = None,
    codex: CliLogin = LOGGED_OUT,
) -> dict[str, int]:
    calls = {"claude": 0, "grok": 0, "codex": 0}
    monkeypatch.setattr("agent_providers.claude.provider._find_claude_binary", lambda: "claude")

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

    monkeypatch.setattr("agent_providers.process._claude_output", fake_claude_output)
    monkeypatch.setattr("agent_providers.process._cli_output", fake_cli_output)
    return calls


@pytest.mark.parametrize(
    ("keys", "claude_login", "grok_login", "codex_login", "sdk_available", "expected_states"),
    [
        (
            {},
            LOGGED_OUT,
            LOGGED_OUT,
            LOGGED_OUT,
            True,
            {
                "claude": _route_states(cli="not_configured", api="not_configured"),
                "grok": _route_states(cli="not_configured", api="not_configured"),
                "codex": _route_states(cli="not_configured", api="not_configured"),
            },
        ),
        (
            {},
            CliLogin(logged_in=True, auth_method="claude.ai"),
            CliLogin(logged_in=True, auth_method="grok"),
            CliLogin(logged_in=True, auth_method="chatgpt"),
            True,
            {
                "claude": _route_states(cli="ready", api="not_configured"),
                "grok": _route_states(cli="ready", api="not_configured"),
                "codex": _route_states(cli="ready", api="not_configured"),
            },
        ),
        (
            {"ANTHROPIC_API_KEY": "ant", "XAI_API_KEY": "xai", "OPENAI_API_KEY": "oa"},
            LOGGED_OUT,
            LOGGED_OUT,
            LOGGED_OUT,
            True,
            {
                "claude": _route_states(cli="not_configured", api="ready"),
                "grok": _route_states(cli="not_configured", api="ready"),
                "codex": _route_states(cli="not_configured", api="ready"),
            },
        ),
        (
            {"ANTHROPIC_API_KEY": "ant"},
            LOGGED_OUT,
            LOGGED_OUT,
            LOGGED_OUT,
            False,
            {
                "claude": _route_states(cli="not_configured", api="disturbed"),
                "grok": _route_states(cli="not_configured", api="not_configured"),
                "codex": _route_states(cli="not_configured", api="not_configured"),
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
    expected_states,
):
    _configure_only_these_api_keys(**keys)
    monkeypatch.setattr(
        "agent_providers.catalog.find_spec",
        lambda _name: object() if sdk_available else None,
    )
    monkeypatch.setattr(
        "agent_providers.catalog.grok_cli_token_is_present",
        lambda: grok_login.logged_in,
    )
    monkeypatch.setattr(
        "agent_providers.catalog.codex_cli_access_token_is_present",
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
        readiness = _route_readiness(item)
        assert {route: state["state"] for route, state in readiness.items()} == (
            expected_states[provider]
        )
        assert all(state["probed_at"] is not None for state in readiness.values())
    assert all(count <= 1 for count in calls.values())


def test_grok_cli_token_readies_the_cli_route_but_not_the_api_route_without_an_api_key(
    admin_client, monkeypatch,
):
    override_provider_runtime(xai_api_key=None)
    monkeypatch.setattr(
        "agent_providers.catalog.grok_cli_token_is_present", lambda: True,
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
    grok_routes = statuses["grok"]["cowriter_routes"]
    assert grok_routes["cli"]["readiness"]["state"] == "ready"
    assert grok_routes["api"]["readiness"]["state"] == "not_configured"
    assert grok_routes["api"]["readiness"]["reason"]["code"] == "api_key_not_set"

    judge_saved = client.put(
        "/api/settings/judge",
        json={"provider": "grok", "model": ""},
    )

    assert judge_saved.status_code == 200
    assert judge_saved.json()["models_by_provider"]["grok"] == []
    assert judge_saved.json()["provider_routes_status"]["grok"]["api"]["readiness"]["reason"] == {
        "code": "api_key_not_set", "message": "API key is not set.",
    }
    cli_saved = client.put(
        "/api/settings/judge",
        json={"provider": "grok", "route": "cli", "model": "grok-4.6"},
    )
    assert cli_saved.status_code == 200
    assert cli_saved.json()["route"] == "cli"
    grok_cli = cli_saved.json()["provider_routes_status"]["grok"]["cli"]
    assert grok_cli["readiness"]["state"] == "ready"


@pytest.mark.parametrize("provider", ["claude", "grok", "codex"])
def test_refresh_records_unparseable_cli_output_without_claiming_readiness(
    admin_client, monkeypatch, provider,
):
    _configure_only_these_api_keys()
    _stub_cli_runners(monkeypatch)

    if provider == "claude":
        monkeypatch.setattr("agent_providers.process._claude_output", lambda _binary: "not JSON")
    else:
        monkeypatch.setattr("agent_providers.process._cli_output", lambda *_args: "not status")
    refresh_provider_snapshots()
    from agent_providers.catalog import ProviderRouteReadinessState

    from songmaker_cli.provider_status import provider_snapshot

    snapshot = provider_snapshot(provider)
    assert snapshot is not None
    expected_cli_state = (
        ProviderRouteReadinessState.NOT_CONFIGURED
        if provider == "claude" else ProviderRouteReadinessState.DISTURBED
    )
    assert snapshot.routes[ProviderRoute.CLI].readiness is expected_cli_state
    assert (
        snapshot.routes[ProviderRoute.API].readiness is ProviderRouteReadinessState.NOT_CONFIGURED
    )
    assert snapshot.probed_at is not None

    client, _ = admin_client
    response = client.get("/api/settings/providers")

    assert response.status_code == 200
    by_provider = {item["provider"]: item for item in response.json()}
    readiness = _route_readiness(by_provider[provider])
    assert readiness["cli"]["state"] == expected_cli_state.value
    assert readiness["api"]["state"] == "not_configured"
    assert all(state["probed_at"] is not None for state in readiness.values())


@pytest.mark.parametrize("provider", ["grok", "codex"])
def test_refresh_preserves_an_api_key_provider_when_its_cli_probe_fails(
    monkeypatch, provider,
):
    from agent_providers.catalog import ProviderRoute, ProviderRouteReadinessState
    from agent_providers.process import AgentCliUnavailableError

    from songmaker_cli.provider_status import provider_snapshot, refresh_provider_snapshot

    def unavailable_cli(_provider: str) -> bool:
        raise AgentCliUnavailableError("unavailable")

    monkeypatch.setattr(
        "agent_providers.catalog._cli_is_logged_in",
        unavailable_cli,
    )
    monkeypatch.setattr(
        "agent_providers.catalog.list_provider_models",
        lambda name, _route: [f"{name}-model"],
    )

    snapshot = refresh_provider_snapshot(provider)

    assert snapshot == provider_snapshot(provider)
    assert snapshot.routes[ProviderRoute.CLI].readiness is ProviderRouteReadinessState.DISTURBED


def test_settings_responses_project_one_snapshot_generation_per_provider(
    admin_client, monkeypatch,
):
    refresh_provider_snapshots()
    monkeypatch.setattr(
        "songmaker_cli.provider_status.provider_snapshot",
        lambda _provider: (_ for _ in ()).throw(AssertionError("individual snapshot read")),
    )

    client, _ = admin_client

    assert client.get("/api/settings/providers").status_code == 200
    assert client.get("/api/settings/judge").status_code == 200


@pytest.mark.parametrize("provider", ["claude", "grok", "codex"])
def test_provider_status_treats_a_hanging_cli_as_logged_out(admin_client, monkeypatch, provider):
    from agent_providers import process

    _configure_only_these_api_keys()
    _stub_cli_runners(monkeypatch)

    def timed_out():
        raise process.CliProbeBudgetExceeded("probe timed out")

    if provider == "claude":
        started = threading.Event()
        release = threading.Event()

        def _hanging_output(_binary: str) -> str | None:
            started.set()
            release.wait(timeout=1)
            return None

        monkeypatch.setattr("agent_providers.process._claude_output", _hanging_output)
        monkeypatch.setattr("agent_providers.process.CLI_PROBE_CALLER_TIMEOUT_SECONDS", 0.01)
    elif provider == "grok":
        monkeypatch.setattr(
            process._grok_status_probe,
            "get",
            timed_out,
        )
    else:
        monkeypatch.setattr(
            process._codex_login_probe,
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
    readiness = _route_readiness(
        next(item for item in response.json() if item["provider"] == provider),
    )
    assert readiness["cli"]["state"] != "ready"
    assert readiness["api"]["state"] == "not_configured"


def test_provider_status_requires_admin(admin_client):
    client, _ = admin_client
    client.app.dependency_overrides[get_current_user] = lambda: make_authenticated_user(
        "u-plain", username="u-u-plain"
    )
    try:
        resp = client.get("/api/settings/providers")
    finally:
        client.app.dependency_overrides[get_current_user] = lambda: make_authenticated_user(
            "u-test", role="admin", username="u-u-test"
        )

    assert resp.status_code == 403


def test_cover_settings_are_admin_only(admin_client):
    client, _ = admin_client
    client.app.dependency_overrides[get_current_user] = lambda: make_authenticated_user(
        "u-plain", username="u-u-plain"
    )
    try:
        assert client.get("/api/settings/cover").status_code == 403
        assert client.put(
            "/api/settings/cover",
            json={"provider": "claude", "route": "api", "model": "claude-sonnet-4-6"},
        ).status_code == 403
    finally:
        client.app.dependency_overrides[get_current_user] = lambda: make_authenticated_user(
            "u-test", role="admin", username="u-u-test"
        )


def test_cover_settings_keep_an_unusable_combination_without_exposing_secrets(
    admin_client,
):
    client, factory = admin_client
    override_provider_runtime(anthropic_api_key=TEST_SECRET.decode())

    assert client.get("/api/settings/cover").json() == {
        "provider": "codex", "route": "cli", "model": "",
    }
    response = client.put(
        "/api/settings/cover",
        json={"provider": "claude", "route": "api", "model": "claude-sonnet-4-6"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "provider": "claude", "route": "api", "model": "claude-sonnet-4-6",
    }
    assert TEST_SECRET.decode() not in response.text
    with factory() as session:
        assert get_cover_settings(session).provider == "claude"
        assert get_cover_settings(session).route == "api"
        assert get_cover_settings(session).model == "claude-sonnet-4-6"
        stored = {
            setting.setting_key: setting.value_text
            for setting in session.query(RateLimitSetting).filter(
                RateLimitSetting.setting_key.in_(
                    {SETTING_COVER_PROVIDER, SETTING_COVER_ROUTE, SETTING_COVER_MODEL},
                ),
            )
        }
    assert stored == {
        SETTING_COVER_PROVIDER: "claude",
        SETTING_COVER_ROUTE: "api",
        SETTING_COVER_MODEL: "claude-sonnet-4-6",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"provider": "openai", "route": "cli", "model": ""},
        {"provider": "codex", "route": "grpc", "model": ""},
    ],
)
def test_cover_settings_reject_an_unknown_provider_or_route(admin_client, payload):
    client, factory = admin_client

    assert client.put("/api/settings/cover", json=payload).status_code == 422

    with factory() as session:
        assert get_cover_settings(session).provider == "codex"
        assert get_cover_settings(session).route == "cli"


def test_cover_settings_accept_an_empty_model(admin_client):
    client, factory = admin_client

    response = client.put(
        "/api/settings/cover", json={"provider": "codex", "route": "cli", "model": ""},
    )

    assert response.status_code == 200
    assert response.json()["model"] == ""
    with factory() as session:
        assert get_cover_settings(session).model == ""


def _cover_routes(client) -> dict[str, dict]:
    return {
        item["provider"]: item["cover_routes"]
        for item in client.get("/api/settings/providers").json()
    }


def test_provider_status_grants_the_image_tool_only_to_a_ready_codex_cli(
    admin_client, monkeypatch,
):
    client, _ = admin_client
    monkeypatch.setattr(
        "agent_providers.dispatch.codex_cover_image_capability_is_available", lambda: True,
    )
    monkeypatch.setattr(
        "agent_providers.dispatch.codex_cli_access_token_is_present", lambda: True,
    )

    cover_routes = _cover_routes(client)

    assert cover_routes["codex"]["cli"] == {
        "state": "ready",
        "capability": "tools_available",
        "reason": None,
        "probed_at": None,
        "setup_label": "CLI login",
    }
    for provider, routes in cover_routes.items():
        for route, readiness in routes.items():
            if (provider, route) == ("codex", "cli"):
                continue
            assert readiness["state"] == "not_configured"
            assert readiness["capability"] == "text_only"
            assert readiness["reason"] == {
                "code": "no_image_tool", "message": "no image tool",
            }


def test_provider_status_names_a_codex_cover_route_that_is_not_signed_in(
    admin_client, monkeypatch,
):
    client, _ = admin_client
    monkeypatch.setattr(
        "agent_providers.dispatch.codex_cover_image_capability_is_available", lambda: True,
    )
    monkeypatch.setattr(
        "agent_providers.dispatch.codex_cli_access_token_is_present", lambda: False,
    )

    codex_cli = _cover_routes(client)["codex"]["cli"]

    assert codex_cli["state"] == "not_configured"
    assert codex_cli["capability"] == "tools_available"
    assert codex_cli["reason"]["code"] == "cli_login_not_configured"


def test_settings_requests_do_not_start_a_provider_probe_without_a_snapshot(
    admin_client, monkeypatch,
):
    calls = 0

    def _counting_popen(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("settings request started a process")

    monkeypatch.setattr("agent_providers.process.subprocess.Popen", _counting_popen)
    client, _ = admin_client

    judge = client.get("/api/settings/judge")
    providers = client.get("/api/settings/providers")

    assert judge.status_code == 200
    assert providers.status_code == 200
    assert set(judge.json()["probed_at"].values()) == {None}
    grok_cli = judge.json()["provider_routes_status"]["grok"]["cli"]["readiness"]
    assert grok_cli["state"] == "unverified"
    assert grok_cli["capability"] == "tools_available"
    assert grok_cli["reason"] is None
    for provider in providers.json():
        for route_status in provider["cowriter_routes"].values():
            assert route_status["readiness"]["state"] == "unverified"
            assert route_status["readiness"]["probed_at"] is None
    response = client.put(
        "/api/settings/judge",
        json={"provider": "grok", "model": ""},
    )

    assert response.status_code == 200
    assert response.json()["model"] == ""
    assert calls == 0


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
        "agent_providers.catalog.list_provider_models", _list_provider_models,
    )
    refresh_provider_snapshots()
    settings = client.get("/api/settings/judge").json()
    assert settings["provider"] == "codex"
    assert settings["models_by_provider"]["grok"] == []
    assert "codex" not in settings["models_errors"]
    assert settings["models_errors"]["grok"] == "Selected route failed."


def test_judge_save_keeps_its_default_pair_while_nothing_is_probed(admin_client):
    client, factory = admin_client
    with factory() as session:
        provider = get_judge_provider(session)
        model = get_judge_model(session, provider)

    response = client.put(
        "/api/settings/judge",
        json={"provider": provider, "model": model},
    )

    assert response.status_code == 200
    assert response.json()["model"] == model
    with factory() as session:
        stored = get_raw_stored_judge_settings(session)
    assert (stored.provider, stored.model) == (provider, model)


def test_judge_save_keeps_its_persisted_model_while_the_catalogue_is_down(
    admin_client, every_provider_is_configured,
):
    client, factory = admin_client
    request = {"provider": "grok", "model": "grok-4.6"}
    assert client.put("/api/settings/judge", json=request).status_code == 200

    def _down(provider: str, _route: ProviderRoute) -> list[str]:
        raise ProviderModelCatalogUnavailableError(
            provider, f"could not list {provider} models",
        )

    with patch("agent_providers.catalog.list_provider_models", side_effect=_down):
        refresh_provider_snapshots()
        again = client.put("/api/settings/judge", json=request)
        unknown = client.put("/api/settings/judge", json={"provider": "grok", "model": "grok-4.5"})

    assert again.status_code == 200
    assert unknown.status_code == 422
    assert unknown.json()["detail"] == "Unknown grok model 'grok-4.5'"
    with factory() as session:
        assert get_raw_stored_judge_settings(session).model == "grok-4.6"


# ── Provider-status response pin (A9, #873) ─────────────────────────
#
# ``GET /api/settings/providers`` feeds the admin "Models" table.  The pin
# drives it from one fixed snapshot set so the whole response body — not a
# field the assertion happens to name — is compared byte for byte.

_PINNED_PROBED_AT = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _pinned_route_snapshot(
    *,
    models: tuple[str, ...] = (),
    catalogue_failure: SafeRouteReasonCode | None = None,
    catalog_source: str | None = None,
    readiness: str,
    reason: SafeRouteReasonCode | None = None,
    setup_label: str,
):
    from agent_providers.catalog import (
        ProviderRouteCapability,
        ProviderRouteReadinessState,
        ProviderRouteSnapshot,
    )

    return ProviderRouteSnapshot(
        models,
        normalize_route_failure(catalogue_failure) if catalogue_failure else None,
        catalog_source,
        None,
        ProviderRouteReadinessState(readiness),
        ProviderRouteCapability.TOOLS_AVAILABLE,
        normalize_route_failure(reason) if reason else None,
        _PINNED_PROBED_AT,
        setup_label,
    )


def _pinned_snapshots(case: str):
    from songmaker_cli.provider_status import ProviderSnapshot

    routes = {
        "claude": {
            ProviderRoute.CLI: _pinned_route_snapshot(
                models=("claude-opus-4-6",), catalog_source="provider CLI",
                readiness="ready", setup_label="CLI login",
            ),
            ProviderRoute.API: _pinned_route_snapshot(
                readiness="ready" if case == "ready" else "disturbed",
                reason=None if case == "ready" else SafeRouteReasonCode.API_HTTP_ERROR,
                setup_label="API key",
            ),
        },
        "grok": {
            ProviderRoute.CLI: _pinned_route_snapshot(
                readiness="not_configured",
                reason=SafeRouteReasonCode.CLI_LOGIN_NOT_CONFIGURED,
                setup_label="CLI login",
            ),
            ProviderRoute.API: _pinned_route_snapshot(
                models=("grok-4.6",), catalog_source="provider API",
                readiness="ready", setup_label="API key",
            ),
        },
        "codex": {
            ProviderRoute.CLI: _pinned_route_snapshot(
                catalogue_failure=SafeRouteReasonCode.CATALOGUE_HTTP_ERROR,
                readiness="disturbed",
                reason=SafeRouteReasonCode.CATALOGUE_HTTP_ERROR,
                setup_label="CLI login",
            ),
            ProviderRoute.API: _pinned_route_snapshot(
                models=("gpt-5.4",), catalog_source="provider API",
                readiness="ready", setup_label="API key",
            ),
        },
    }
    return {
        provider: ProviderSnapshot(
            probed_at=_PINNED_PROBED_AT,
            routes=routes[provider],
        )
        for provider in sorted(LIVE_CATALOG)
    }


def _pinned_cover_capability(provider: str, route):
    from agent_providers.catalog import ProviderRoute
    from agent_providers.dispatch import CoverImageCapability

    if provider == "codex" and route is ProviderRoute.CLI:
        return CoverImageCapability(carries_image_tool=True, failure=None)
    return CoverImageCapability(
        carries_image_tool=False,
        failure=normalize_route_failure(SafeRouteReasonCode.NO_IMAGE_TOOL),
    )


def _pinned_response_body(case: str) -> bytes:
    return (
        Path(__file__).with_name("fixtures") / f"provider_status_{case}.json"
    ).read_bytes()


@pytest.mark.parametrize("case", ["ready", "capability_missing"])
def test_provider_status_response_is_byte_identical_for_a_fixed_snapshot(
    admin_client, monkeypatch, case: str,
) -> None:
    client, _ = admin_client
    snapshots = _pinned_snapshots(case)
    monkeypatch.setattr(
        "songmaker_cli.provider_status.provider_snapshots", lambda: snapshots,
    )
    monkeypatch.setattr(
        "agent_providers.dispatch.cover_image_capability", _pinned_cover_capability,
    )

    response = client.get("/api/settings/providers")

    assert response.status_code == 200
    assert response.content == _pinned_response_body(case)


@pytest.mark.parametrize("provider", ["claude", "grok", "codex"])
@pytest.mark.parametrize("route,other_route", [("cli", "api"), ("api", "cli")])
def test_judge_saves_only_models_from_its_selected_route(
    admin_client, monkeypatch, every_provider_is_configured, provider, route, other_route,
):
    client, factory = admin_client
    monkeypatch.setattr(
        "agent_providers.catalog.list_provider_models",
        lambda name, selected: [f"{name}-{selected.value}-model"],
    )
    refresh_provider_snapshots()
    request = {"provider": provider, "route": route, "model": f"{provider}-{route}-model"}
    rejected = client.put(
        "/api/settings/judge", json={**request, "model": f"{provider}-{other_route}-model"},
    )
    assert rejected.status_code == 422
    saved = client.put("/api/settings/judge", json=request)
    assert saved.status_code == 200
    body = saved.json()
    assert {key: body[key] for key in request} == request
    assert body["allowed_models"] == [request["model"]]
    assert body["models_by_provider"] == {
        name: [f"{name}-{route}-model"] for name in LIVE_CATALOG
    }
    assert body["provider_routes_status"][provider][other_route]["retained_model_id"] == request[
        "model"
    ]
    assert client.get("/api/settings/judge").json() == body
    with factory() as session:
        audit = session.query(AuditLog).filter_by(resource_type="judge").one()
        assert f"route={route}" in audit.detail

    retained = client.put("/api/settings/judge", json={**request, "route": other_route})
    assert retained.status_code == 200
    assert retained.json()["provider_routes_status"][provider][other_route][
        "retained_model_id"
    ] == request["model"]


@pytest.mark.parametrize("route", ["cli", "api"])
@pytest.mark.parametrize("route_field", [{}, {"route": None}])
def test_judge_save_without_route_preserves_its_saved_route(
    admin_client, every_provider_is_configured, route, route_field,
):
    client, _ = admin_client
    request = {"provider": "grok", "route": route, "model": "grok-4.6"}
    assert client.put("/api/settings/judge", json=request).status_code == 200
    saved = client.put(
        "/api/settings/judge", json={"provider": "grok", "model": "grok-4.5", **route_field},
    )
    assert saved.status_code == 200
    assert saved.json()["route"] == route


@pytest.mark.parametrize("route", ["cli", "api"])
@pytest.mark.parametrize("provider", ["claude", "grok", "codex"])
def test_judge_saves_an_empty_model_on_an_unavailable_route(admin_client, route, provider):
    client, _ = admin_client
    default = client.get("/api/settings/judge").json()["model"]
    request = {"provider": provider, "route": route, "model": ""}
    response = client.put("/api/settings/judge", json=request)
    assert response.status_code == 200
    body = client.get("/api/settings/judge").json()
    assert {key: body[key] for key in request} == {
        **request, "model": default if provider == "claude" else "",
    }
    assert body["allowed_models"] == []
    assert body["provider_routes_status"][provider][route]["readiness"]["state"] == "unverified"


@pytest.mark.parametrize("method", ["get", "put"])
def test_judge_settings_require_an_admin(admin_client, method):
    client, _ = admin_client
    client.app.dependency_overrides[get_current_user] = lambda: make_authenticated_user(
        "u-test", username="u-u-test"
    )
    response = client.request(
        method, "/api/settings/judge", json={"provider": "grok", "route": "api", "model": ""},
    )
    assert response.status_code == 403


MISSING_OR_INVALID_JUDGE_ROUTES = [None, "unknown", ""]


def _store_judge_route(factory, route: str | None) -> None:
    with factory() as session:
        session.query(RateLimitSetting).filter_by(setting_key=SETTING_JUDGE_ROUTE).delete()
        if route is not None:
            set_claude_model(session, SETTING_JUDGE_ROUTE, route)
        session.commit()


@pytest.mark.parametrize("route", MISSING_OR_INVALID_JUDGE_ROUTES)
@pytest.mark.parametrize("path,method", [
    ("/api/settings/judge", "get"),
    ("/api/settings/judge", "put"),
])
def test_missing_or_invalid_judge_route_is_rejected_without_a_default(
    admin_client, route, path, method,
):
    client, factory = admin_client
    _store_judge_route(factory, route)

    response = client.request(method, path, json={"provider": "grok", "model": ""})

    assert response.status_code == 422
    assert "Judge route" in response.json()["detail"]


@pytest.mark.parametrize("route", MISSING_OR_INVALID_JUDGE_ROUTES)
def test_provider_status_is_served_whatever_judge_route_is_stored(admin_client, route):
    client, factory = admin_client
    _store_judge_route(factory, route)

    response = client.get("/api/settings/providers")

    assert response.status_code == 200
    assert {item["provider"] for item in response.json()} == set(LIVE_CATALOG)


def test_unknown_judge_route_leaves_the_selection_unchanged(admin_client):
    client, _ = admin_client
    before = client.get("/api/settings/judge").json()
    rejected = client.put(
        "/api/settings/judge", json={"provider": "codex", "route": "automatic", "model": ""},
    )
    assert rejected.status_code == 422
    assert client.get("/api/settings/judge").json() == before
