"""Co-writer provider switch (#34). Models come from the live catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agent_providers.catalog import ProviderRoute
from agent_providers.process import LOGGED_OUT, CliLogin, GrokCliStatus
from support.admin_client import build_admin_client
from support.cowriter_gateway import attach_cowriter_gateway
from support.provider_runtime import override_provider_runtime, refresh_provider_snapshots
from support.setting_rows import store_setting_row
from support.web_app import make_authenticated_user, make_test_app, seed_user

from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.constants import COWRITER_DEFAULT_TAIL_TOKEN_BUDGET
from songmaker_cli.cowriter.tools import execute_cowriter_tool
from songmaker_cli.db.models import (
    Album,
    AuditLog,
    AvailableModel,
    Generation,
    Job,
    RateLimitSetting,
    Song,
    Version,
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
    seed_user(session, f"user-{user_id}", "admin", user_id=user_id)
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
    return build_admin_client(
        tmp_path,
        lambda session: _seed(session, "u-test"),
        user_id="u-test",
        username="u-u-test",
        database_name="cowriter.db",
    )


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
        store_setting_row(session, "cowriter_provider", "grok")
        store_setting_row(session, "cowriter_model", "grok-4.6")
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
        store_setting_row(session, "cowriter_provider", "retired-provider")
        store_setting_row(session, "cowriter_model_grok", "grok-4.6")
        session.commit()
    rows_before = _stored_choice_rows(factory)

    assert client.get("/api/settings/cowriter").status_code == 200
    assert client.put("/api/settings/cowriter", json={"tail_token_budget": 6000}).status_code == 200

    assert _stored_choice_rows(factory) == rows_before


def test_c15_put_cowriter_settings_refuses_a_budget_out_of_range(admin_client):
    client, _ = admin_client

    response = client.put("/api/settings/cowriter", json={"tail_token_budget": 1_000_000})

    assert response.status_code == 422


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


def test_chat_turns_beyond_the_chat_rate_limit_are_refused(admin_client, monkeypatch, tmp_path):
    client, factory = admin_client
    monkeypatch.setenv("CHAT_RATE_LIMIT_USER", "2")
    get_settings.cache_clear()
    attach_cowriter_gateway(client, factory, tmp_path, "u-test")

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
            {"album_id": "alb1", "title": "FromCatalog", "lyrics": "a"}, session_id=None,
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
            {"song_id": "s1", "title": "Renamed Track"}, session_id=None,
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
            {"song_id": "s1", "lyrics": "new lyrics"}, session_id=None,
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


def test_suggest_album_cover_tool_hits_the_canonical_admission_owner(admin_client, tmp_path):
    client, factory = admin_client
    user = make_authenticated_user("u-test", role="admin", username="u-u-test")
    stack = attach_cowriter_gateway(client, factory, tmp_path, "u-test")
    with factory() as session:
        outcome = execute_cowriter_tool(
            session, user, "suggest_album_cover", {"album_id": "alb1"},
            session_id=stack.session_id,
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

    from songmaker_cli.provider_status import provider_snapshots

    snapshot = provider_snapshots()[provider]
    expected_cli_state = (
        ProviderRouteReadinessState.NOT_CONFIGURED
        if provider == "claude" else ProviderRouteReadinessState.DISTURBED
    )
    assert snapshot.routes[ProviderRoute.CLI].readiness is expected_cli_state
    assert (
        snapshot.routes[ProviderRoute.API].readiness is ProviderRouteReadinessState.NOT_CONFIGURED
    )
    assert snapshot.probed_at is not None


@pytest.mark.parametrize("provider", ["grok", "codex"])
def test_refresh_preserves_an_api_key_provider_when_its_cli_probe_fails(
    monkeypatch, provider,
):
    from agent_providers.catalog import ProviderRoute, ProviderRouteReadinessState
    from agent_providers.process import AgentCliUnavailableError

    from songmaker_cli.provider_status import provider_snapshots, refresh_provider_snapshot

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

    assert snapshot == provider_snapshots()[provider]
    assert snapshot.routes[ProviderRoute.CLI].readiness is ProviderRouteReadinessState.DISTURBED


_STORED_COVER_ROWS = {"cover_provider": "claude", "cover_route": "api", "cover_model": "x"}


def test_the_cover_settings_are_gone_and_their_stored_rows_stay_unread(admin_client):
    client, factory = admin_client
    with factory() as session:
        for key, value in _STORED_COVER_ROWS.items():
            store_setting_row(session, key, value)
        session.commit()

    assert client.get("/api/settings/cover").status_code == 404
    assert client.put(
        "/api/settings/cover", json={"provider": "codex", "route": "cli", "model": ""},
    ).status_code == 404

    with factory() as session:
        stored = {
            row.setting_key: row.value_text
            for row in session.query(RateLimitSetting).filter(
                RateLimitSetting.setting_key.in_(_STORED_COVER_ROWS),
            )
        }
    assert stored == _STORED_COVER_ROWS


@pytest.mark.parametrize("role", ["admin", "user"])
@pytest.mark.parametrize("path", ["/api/capabilities", "/api/settings/providers"])
def test_removed_provider_routes_answer_ordinary_not_found(tmp_path, mock_arq_pool, path, role):
    overrides = (client := make_test_app(tmp_path)[0]).app.dependency_overrides
    overrides[get_current_user] = lambda: make_authenticated_user("u", role=role)
    with client:
        unknown, removed = client.get("/api/nope"), client.get(path)
    assert removed.status_code == unknown.status_code == 404
    assert removed.content == unknown.content


@pytest.mark.parametrize("role", ["admin", "user"])
@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_removed_judge_endpoint_answers_ordinary_not_found(tmp_path, mock_arq_pool, method, role):
    overrides = (client := make_test_app(tmp_path)[0]).app.dependency_overrides
    overrides[get_current_user] = lambda: make_authenticated_user("u", role=role)
    with client:
        unknown, removed = [client.request(method, f"/api/settings/{n}") for n in ("nope", "judge")]
    assert removed.status_code == unknown.status_code == 404
    assert removed.content == unknown.content


_LEFTOVER_JUDGE_ROWS = {
    "judge_provider": "grok",
    "judge_route": "bogus",
    "judge_model": "x",
    "claude_scoring_model": "y",
}


def _leftover_judge_rows(factory) -> dict[str, str | None]:
    with factory() as session:
        return {
            row.setting_key: row.value_text
            for row in session.query(RateLimitSetting).filter(
                RateLimitSetting.setting_key.in_(list(_LEFTOVER_JUDGE_ROWS)),
            )
        }


def test_startup_writes_no_judge_row_on_a_fresh_database(tmp_path, mock_arq_pool):
    client, factory = make_test_app(tmp_path)

    with client:
        pass

    assert _leftover_judge_rows(factory) == {}


def test_startup_and_settings_reads_leave_stored_judge_rows_unread_and_unchanged(
    tmp_path, mock_arq_pool,
):
    def seed_leftover_rows(session) -> None:
        for key, value in _LEFTOVER_JUDGE_ROWS.items():
            store_setting_row(session, key, value)

    client, factory = make_test_app(tmp_path, seed_db=seed_leftover_rows)
    client.app.dependency_overrides[get_current_user] = lambda: make_authenticated_user(
        "u-admin", role="admin", username="admin",
    )

    with client:
        for path in ("/api/settings/cowriter", "/api/settings/models"):
            assert client.get(path).status_code == 200

    assert _leftover_judge_rows(factory) == _LEFTOVER_JUDGE_ROWS
