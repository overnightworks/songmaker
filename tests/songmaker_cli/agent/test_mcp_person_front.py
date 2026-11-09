"""A person's own agent on ``/mcp`` and on the marked routes, against a fake Keycloak realm.

Every case drives the real app through the ASGI client; the relying party verifies the tokens
exactly as in production and only its key set is the fake issuer's.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker
from starlette.routing import Match
from starlette.types import ASGIApp, Receive, Scope, Send
from support.mcp_world import (
    AGENT_ENVIRONMENT,
    MCP_CLIENT_ENVIRONMENT,
    MCP_SCOPE,
    METADATA_URL,
    PROTOCOL_HEADER,
    PROTOCOL_VERSION,
    RESOURCE_URL,
    McpWorld,
    build_mcp_world,
    worker_ready,
)
from support.token_world import TokenWorld, make_token_world
from support.web_app import TEST_ORIGIN, seed_session

from songmaker_cli.agent.mcp import Exclusion, collect_route_tools
from songmaker_cli.constants import (
    MODEL_AVAILABLE_MODES,
    OIDC_ADMIN_GROUP,
    OIDC_LOGIN_GROUP,
    OIDC_MCP_GROUP,
)
from songmaker_cli.db.models import Album, Generation, Job, Song
from songmaker_cli.settings import Settings, get_settings

MARKED_TOOLS = {
    "list_albums", "create_album", "list_songs", "create_song", "get_song", "generate_song",
    "get_active_generation", "get_last_failed_generation", "get_album",
    "list_cover_suggestions", "get_account",
    "get_take", "get_job", "get_library_listen", "get_library_write", "search_library",
    "get_library_pool_queue", "list_loras", "list_playlists", "get_playlist",
    "list_references", "list_reference_uses", "get_release", "get_cowriter_settings",
    "get_default_config", "get_generation_builtins", "get_generation_defaults", "list_models",
    "list_presets", "get_theme", "list_song_versions", "archive_album", "restore_album",
    "unarchive_album", "cover_take", "keep_take", "rate_take",
    "repaint_take", "score_take", "unarchive_take", "cancel_job", "create_lora",
    "add_lora_sample_from_take", "create_playlist", "add_album_to_playlist",
    "add_take_to_playlist", "add_song_to_playlist", "keep_reference", "create_preset",
    "set_default_preset", "restore_song", "list_own_playable_takes", "get_lora",
    "update_album", "update_playlist", "move_playlist_entry", "remove_playlist_entry",
    "update_preset", "set_theme", "set_default_config", "rename_song", "move_song",
    "update_lora_sample", "write_user_memory", "write_song_memory", "write_album_memory",
    "unshare_album", "unshare_song", "unshare_take", "unshare_playlist", "delete_album",
    "delete_song", "update_song", "pick_take", "unpick_take", "unkeep_take",
    "unkeep_reference",
}
LIFECYCLE_TOOL_ROUTES = {
    "unshare_album": ("DELETE", "/api/albums/{album_id}/share"),
    "unshare_song": ("DELETE", "/api/songs/{song_id}/share"),
    "unshare_take": ("DELETE", "/api/generations/{gen_id}/share"),
    "unshare_playlist": ("DELETE", "/api/playlists/{playlist_id}/share"),
    "delete_album": ("DELETE", "/api/albums/{album_id}"),
    "delete_song": ("DELETE", "/api/songs/{song_id}"),
    "update_song": ("PUT", "/api/songs/{song_id}"),
    "pick_take": ("POST", "/api/generations/{gen_id}/pick"),
    "unpick_take": ("POST", "/api/generations/{gen_id}/unpick"),
    "unkeep_take": ("POST", "/api/generations/{gen_id}/unkeep"),
    "unkeep_reference": ("POST", "/api/references/{reference_id}/unkeep"),
}
NEW_MARKED_ROUTES = {
    ("PUT", "/api/albums/{album_id}"), ("PUT", "/api/playlists/{playlist_id}"),
    ("PATCH", "/api/playlists/{playlist_id}/entries/{entry_id}/position"),
    ("DELETE", "/api/playlists/{playlist_id}/entries/{entry_id}"),
    ("PUT", "/api/settings/presets/{preset_id}"), ("PUT", "/api/settings/theme"),
    ("PUT", "/api/settings/default-config"), ("PUT", "/api/songs/{song_id}/title"),
    ("PUT", "/api/songs/{song_id}/album"),
    ("PATCH", "/api/loras/{lora_id}/samples/{sample_id}"), ("PUT", "/api/memory/user"),
    ("PUT", "/api/memory/songs/{song_id}"), ("PUT", "/api/memory/albums/{album_id}"),
}


# -- M1: exactly the marked tools ---------------------------------------------------------


def test_m1_a_members_agent_is_offered_exactly_the_marked_tools(mcp: McpWorld) -> None:
    assert mcp.tool_names() == MARKED_TOOLS


def test_m1_the_new_put_patch_and_delete_routes_are_among_the_marks(mcp: McpWorld) -> None:
    marks = collect_route_tools(mcp.world.client.app).marks

    assert NEW_MARKED_ROUTES <= {(mark.method, mark.template) for mark in marks}


@pytest.mark.parametrize(("name", "route"), LIFECYCLE_TOOL_ROUTES.items(),
                         ids=list(LIFECYCLE_TOOL_ROUTES))
def test_m1_each_lifecycle_route_is_a_side_effecting_tool_with_a_description(
    mcp: McpWorld, name: str, route: tuple[str, str],
) -> None:
    method, template = route
    operation = mcp.world.client.app.openapi()["paths"][template][method.lower()]

    assert operation["x-agent-tool"] == {"name": name, "effect": "side_effecting"}
    assert operation.get("description")


def test_m1_every_operation_carries_a_decision_and_an_exclusion_names_a_reason_of_the_enum(
    mcp: McpWorld,
) -> None:
    operations = [
        operation for item in mcp.world.client.app.openapi()["paths"].values()
        for method, operation in item.items() if method != "parameters"
    ]

    decisions = [operation.get("x-agent-tool") for operation in operations]
    assert None not in decisions
    reasons = {d["excluded"] for d in decisions if "excluded" in d}
    assert reasons <= {reason.value for reason in Exclusion}


def test_m1_the_description_of_generate_names_the_valid_models(mcp: McpWorld) -> None:
    reply = mcp.rpc("tools/list", headers=mcp.agent())
    generate = next(
        tool for tool in reply.json()["result"]["tools"] if tool["name"] == "generate_song"
    )

    assert all(model in generate["description"] for model in MODEL_AVAILABLE_MODES)


# -- M2, M3: only the person's own content -------------------------------------------


def test_m2_the_read_tools_give_the_persons_own_content_as_the_api_does(mcp: McpWorld) -> None:
    mcp.world.seed_take(TokenWorld.ALICE, "alices")
    mcp.world.seed_take(TokenWorld.BOB, "bobs")
    headers = mcp.agent()
    api = mcp.world.client

    albums = mcp.call("list_albums")
    songs = mcp.call("list_songs")
    song = mcp.call("get_song", {"song_id": "song-alices"})
    others = mcp.call("get_song", {"song_id": "song-bobs"})

    assert albums.json() == api.get("/api/albums", headers=headers).json()
    assert [item["title"] for item in albums.json()["items"]] == ["Album alices"]
    assert songs.json() == api.get("/api/songs", headers=headers).json()
    assert [item["title"] for item in songs.json()["items"]] == ["Song alices"]
    assert song.json() == api.get("/api/songs/song-alices", headers=headers).json()
    assert (others.is_error, others.text) != (False, song.text)
    assert "Not Found" in others.text


def test_m3_an_admins_agent_sees_only_the_admins_own_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory: sessionmaker,
    lifespans: ExitStack,
) -> None:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    world = build_mcp_world(tmp_path, monkeypatch, pg_factory, lifespans, alice_role="admin")
    world.world.seed_take(TokenWorld.ALICE, "alices")
    world.world.seed_take(TokenWorld.BOB, "bobs")
    groups = (OIDC_LOGIN_GROUP, OIDC_ADMIN_GROUP, OIDC_MCP_GROUP)

    songs = world.call("list_songs", groups=groups)
    albums = world.call("list_albums", groups=groups)
    others = world.call("get_song", {"song_id": "song-bobs"}, groups=groups)

    assert [item["title"] for item in songs.json()["items"]] == ["Song alices"]
    assert [item["title"] for item in albums.json()["items"]] == ["Album alices"]
    assert others.is_error


# -- M4, M5, M18, M24: writing as the person -------------------------------------------


def test_m4_create_song_into_the_persons_album_is_audited_as_that_person(mcp: McpWorld) -> None:
    mcp.world.seed_take(TokenWorld.ALICE, "alices")

    reply = mcp.call("create_song", {"title": "Fresh", "album_id": "album-alices"})

    created = reply.json()
    assert (reply.is_error, created["title"]) == (False, "Fresh")
    assert mcp.rows_of(Song, "id", "title").count((created["id"], "Fresh")) == 1
    assert (TokenWorld.ALICE, "create", "song", created["id"]) in mcp.world.audits()


def test_m5_create_song_into_another_persons_album_is_not_found_and_creates_nothing(
    mcp: McpWorld,
) -> None:
    mcp.world.seed_take(TokenWorld.BOB, "bobs")

    reply = mcp.call("create_song", {"title": "Sneaky", "album_id": "album-bobs"})

    assert reply.is_error
    assert mcp.rows_of(Song, "title") == [("Song bobs",)]


def test_m18_create_album_makes_an_album_owned_and_audited_as_the_person(mcp: McpWorld) -> None:
    reply = mcp.call("create_album", {"title": "Agent Album"})

    created = reply.json()
    assert (reply.is_error, created["title"]) == (False, "Agent Album")
    assert mcp.world.albums() == [("Agent Album", TokenWorld.ALICE)]
    assert (TokenWorld.ALICE, "create", "album", created["id"]) in mcp.world.audits()


def test_m24_an_admins_agent_cannot_write_into_or_generate_for_another_persons_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory: sessionmaker,
    lifespans: ExitStack,
) -> None:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    world = build_mcp_world(tmp_path, monkeypatch, pg_factory, lifespans, alice_role="admin")
    world.world.seed_take(TokenWorld.BOB, "bobs")
    groups = (OIDC_LOGIN_GROUP, OIDC_ADMIN_GROUP, OIDC_MCP_GROUP)

    with worker_ready() as pool:
        into = world.call("create_song", {"title": "x", "album_id": "album-bobs"}, groups=groups)
        generated = world.call(
            "generate_song", {"song_id": "song-bobs", "model": "sft"}, groups=groups,
        )

    assert (into.is_error, generated.is_error) == (True, True)
    assert "Not Found" in into.text
    assert "Not Found" in generated.text
    assert world.rows_of(Job, "id") == []
    pool.enqueue_job.assert_not_called()


_PROGRESS_TOOLS = {
    "get_active_generation": "/api/songs/{song_id}/active-generation",
    "get_last_failed_generation": "/api/songs/{song_id}/last-failed-generation",
}


@pytest.mark.parametrize("tool", _PROGRESS_TOOLS)
def test_m27_a_progress_tool_answers_for_the_persons_own_song_as_the_api_does(
    mcp: McpWorld, tool: str,
) -> None:
    mcp.world.seed_take(TokenWorld.ALICE, "alices")
    with worker_ready():
        mcp.call("generate_song", {"song_id": "song-alices", "model": "sft"})

    reply = mcp.call(tool, {"song_id": "song-alices"})

    api = mcp.world.client.get(
        _PROGRESS_TOOLS[tool].format(song_id="song-alices"), headers=mcp.agent(),
    )
    assert (reply.is_error, reply.json()) == (False, api.json())


def test_m27_the_active_generation_tool_names_the_queued_job_and_none_without_one(
    mcp: McpWorld,
) -> None:
    mcp.world.seed_take(TokenWorld.ALICE, "alices")
    idle = mcp.call("get_active_generation", {"song_id": "song-alices"})
    with worker_ready():
        queued = mcp.call("generate_song", {"song_id": "song-alices", "model": "sft"})

    active = mcp.call("get_active_generation", {"song_id": "song-alices"})

    assert (idle.is_error, idle.json()) == (False, None)
    assert active.json()["id"] == queued.json()["id"]


def test_m27_the_last_failed_generation_tool_names_the_failed_job_until_a_newer_attempt(
    mcp: McpWorld,
) -> None:
    mcp.world.seed_take(TokenWorld.ALICE, "alices")
    path = _PROGRESS_TOOLS["get_last_failed_generation"].format(song_id="song-alices")
    with mcp.world.factory() as session:
        session.query(Generation).update({"is_archived": True})
        session.add(Job(
            id="job-failed", type="generate", status="failed", song_id="song-alices",
            error="out of memory", error_type="gpu_out_of_memory",
            started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            completed_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        ))
        session.commit()

    failed = mcp.call("get_last_failed_generation", {"song_id": "song-alices"})
    failed_api = mcp.world.client.get(path, headers=mcp.agent())
    with mcp.world.factory() as session:
        session.add(Job(
            id="job-newer", type="generate", status="queued", song_id="song-alices",
            started_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        ))
        session.commit()
    hidden = mcp.call("get_last_failed_generation", {"song_id": "song-alices"})
    hidden_api = mcp.world.client.get(path, headers=mcp.agent())

    assert failed.json()["job"] is not None
    assert (failed.is_error, failed.json()) == (False, failed_api.json())
    assert (hidden.is_error, hidden.json()) == (False, hidden_api.json())
    assert hidden.json()["job"] is None


@pytest.mark.parametrize("tool", _PROGRESS_TOOLS)
def test_m28_a_progress_tool_for_another_persons_song_is_not_found_and_reveals_nothing(
    mcp: McpWorld, tool: str,
) -> None:
    mcp.world.seed_take(TokenWorld.BOB, "bobs")
    bobs = mcp.agent(TokenWorld.BOB)
    with worker_ready():
        mcp.world.client.post(
            "/api/songs/song-bobs/generate", json={"model": "sft"}, headers=bobs,
        )

    others = mcp.call(tool, {"song_id": "song-bobs"})

    assert others.is_error
    assert "Not Found" in others.text
    assert "generate" not in others.text


# -- M6: what the agent's token cannot reach ------------------------------------------

_UNMARKED_ROUTES = [
    ("POST", "/api/generations/bulk-delete", {"generation_ids": ["take-alices"]}),
    ("DELETE", "/api/generations/take-alices", None),
    ("POST", "/api/albums/album-alices/share", None),
    ("POST", "/api/loras/lora-alices/train", None),
    ("DELETE", "/api/playlists/any", None),
    ("GET", "/api/admin/voices", None),
    ("GET", "/api/albums/album-alices/cover", None),
    ("PUT", "/api/albums/album-alices/cover", {"suggestion_id": "any"}),
    ("GET", "/api/conversations", None),
    ("POST", "/api/songs/song-alices/listen", None),
    ("PUT", "/api/settings/rate-limits", {"limits": []}),
]


@pytest.mark.parametrize(
    ("method", "path", "body"), _UNMARKED_ROUTES,
    ids=["bulk-delete", "take-delete", "share", "train", "playlist-delete", "admin",
         "browser-only", "album-cover-choice", "conversations", "listen", "admin-settings"],
)
def test_m6_the_agent_token_is_refused_on_every_unmarked_route_and_nothing_changes(
    mcp: McpWorld, method: str, path: str, body: dict | None,
) -> None:
    mcp.world.seed_take(TokenWorld.ALICE, "alices")

    reply = mcp.world.client.request(method, path, json=body, headers=mcp.agent())

    assert reply.status_code in {401, 403}
    assert mcp.rows_of(Generation, "id") == [("take-alices",)]
    assert [row[0] for row in mcp.rows_of(Album, "deleted_at")] == [None]


def test_m6_a_public_view_answers_the_agent_token_as_it_answers_a_visitor(mcp: McpWorld) -> None:
    mcp.world.seed_take(TokenWorld.ALICE, "alices")
    seed_session(mcp.world.client, "alice")
    shared = mcp.world.client.post("/api/albums/album-alices/share", headers=_SAME_ORIGIN)
    mcp.world.client.cookies.clear()
    path = f"/shared/{shared.json()['share_slug']}"

    visitor = mcp.world.client.get(path)
    agent = mcp.world.client.get(path, headers=mcp.agent(TokenWorld.BOB))

    assert (agent.status_code, agent.json()) == (visitor.status_code, visitor.json())


def test_m6_every_unmarked_route_of_the_list_is_a_real_route_of_the_app(mcp: McpWorld) -> None:
    app = mcp.world.client.app

    def is_routed(method: str, path: str) -> bool:
        scope = {"type": "http", "method": method, "path": path}
        return any(route.matches(scope)[0] == Match.FULL for route in app.routes)

    unrouted = [(method, path) for method, path, _ in _UNMARKED_ROUTES
                if not is_routed(method, path)]
    assert unrouted == []


# -- the own-playable-takes list and a single LoRA ----------------------------------------


def test_an_admins_agent_asking_for_another_persons_lora_gets_not_found_and_nothing_of_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory: sessionmaker,
    lifespans: ExitStack,
) -> None:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    world = build_mcp_world(tmp_path, monkeypatch, pg_factory, lifespans, alice_role="admin")
    world.seed_household(TokenWorld.BOB, "bobs")
    groups = (OIDC_LOGIN_GROUP, OIDC_ADMIN_GROUP, OIDC_MCP_GROUP)

    reply = world.call("get_lora", {"lora_id": "lora-bobs"}, groups=groups)

    assert reply.is_error
    assert "Not Found" in reply.text
    assert "bobs" not in reply.text.replace("lora-bobs", "")


def test_the_old_own_takes_path_is_read_as_a_lora_id_and_not_found_for_cookie_and_token(
    mcp: McpWorld,
) -> None:
    mcp.seed_household(TokenWorld.ALICE, "alices")
    seed_session(mcp.world.client, "alice")

    cookie = mcp.world.client.get("/api/loras/own-takes", headers=_SAME_ORIGIN)
    token = mcp.world.client.get("/api/loras/own-takes", headers=mcp.agent())

    assert (cookie.status_code, token.status_code) == (404, 404)
    assert "take-alices" not in cookie.text + token.text


# -- M7, M8, M9, M10, M22, M23: which tokens count ----------------------------------


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "songmaker-test", "azp": TokenWorld.HAL},
        {"azp": "another-client"},
        {"aud": "https://elsewhere.test/mcp"},
    ],
    ids=["person-token-with-the-app-audience", "another-azp", "another-resource"],
)
def test_m7_a_token_of_another_audience_or_party_is_refused_at_mcp(
    mcp: McpWorld, claims: dict[str, str],
) -> None:
    reply = mcp.rpc("tools/list", headers=mcp.agent(**claims))

    assert reply.status_code == 401


def test_m8_a_token_of_a_non_member_of_the_mcp_group_is_refused(mcp: McpWorld) -> None:
    reply = mcp.rpc("tools/list", headers=mcp.agent(groups=(OIDC_LOGIN_GROUP,)))

    assert reply.status_code == 403


def test_m9_a_member_of_the_mcp_group_alone_is_admitted_as_an_app_member(mcp: McpWorld) -> None:
    assert mcp.tool_names(groups=(OIDC_MCP_GROUP,)) == MARKED_TOOLS


def test_m10_an_expired_token_is_refused(mcp: McpWorld) -> None:
    issued = int(mcp.world.issuer.now) - 2 * TokenWorld.TOKEN_LIFETIME_SECONDS

    reply = mcp.rpc("tools/list", headers=mcp.agent(iat=issued, exp=issued + 60))

    assert reply.status_code == 401


def test_m10_a_person_who_never_signed_in_is_refused_and_no_account_is_made(
    mcp: McpWorld,
) -> None:
    stranger = "11111111-2222-4333-8444-555555555555"

    reply = mcp.rpc("tools/list", headers=mcp.agent(stranger))

    assert reply.status_code == 403
    assert [row[0] for row in mcp.world.users()].count(stranger) == 0


def test_m22_a_token_naming_two_audiences_is_refused(mcp: McpWorld) -> None:
    reply = mcp.rpc("tools/list", headers=mcp.agent(aud=[RESOURCE_URL, "songmaker-test"]))

    assert reply.status_code == 401


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/api/songs"), ("DELETE", "/api/albums/album-alices")],
    ids=["marked-route", "unmarked-route"],
)
def test_m23_the_agent_client_with_the_app_audience_is_refused_everywhere(
    mcp: McpWorld, method: str, path: str,
) -> None:
    mcp.world.seed_take(TokenWorld.ALICE, "alices")

    reply = mcp.world.client.request(method, path, headers=mcp.agent(aud="songmaker-test"))

    assert reply.status_code in {401, 403}
    assert mcp.rows_of(Album, "deleted_at") == [(None,)]


# -- M11, M12: the endpoint's own answers -----------------------------------------------


def test_m11_get_with_a_valid_bearer_is_405_and_an_origin_is_403(mcp: McpWorld) -> None:
    refused_method = mcp.world.client.get("/mcp", headers=mcp.agent())
    with_origin = mcp.world.client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={**mcp.agent(), "Origin": "https://evil.test"},
    )

    assert (refused_method.status_code, with_origin.status_code) == (405, 403)


def test_m11_without_a_bearer_or_with_only_a_cookie_the_answer_is_the_401_challenge(
    mcp: McpWorld,
) -> None:
    bare = mcp.rpc("tools/list", headers={})
    seed_session(mcp.world.client, "alice")
    cookie_only = mcp.rpc("tools/list", headers={})

    for reply in (bare, cookie_only):
        assert reply.status_code == 401
        challenge = reply.headers["www-authenticate"]
        assert f'resource_metadata="{METADATA_URL}"' in challenge
        assert f'scope="{MCP_SCOPE}"' in challenge


@pytest.mark.parametrize(
    "revision_headers",
    [pytest.param({}, id="absent"), pytest.param({PROTOCOL_HEADER: "2025-11-25"}, id="older")],
)
def test_m11_a_request_without_the_served_revision_is_refused_and_lists_the_served_one(
    mcp: McpWorld, revision_headers: dict[str, str],
) -> None:
    reply = mcp.world.client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={**mcp.agent(), **revision_headers},
    )

    assert reply.status_code == 400
    assert reply.json()["error"]["code"] == -32022
    assert reply.json()["error"]["data"]["supported"] == [PROTOCOL_VERSION]


def test_m12_the_resource_metadata_names_the_derived_url_and_the_issuer(mcp: McpWorld) -> None:
    reply = mcp.world.client.get("/.well-known/oauth-protected-resource/mcp")

    assert reply.status_code == 200
    assert reply.json() == {
        "resource": RESOURCE_URL,
        "authorization_servers": [mcp.world.issuer.issuer],
        "scopes_supported": [MCP_SCOPE],
    }


# -- M13: configuration -----------------------------------------------------------------


def test_m13_with_the_mcp_values_unset_mcp_and_its_metadata_answer_as_they_did(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory: sessionmaker,
    lifespans: ExitStack,
) -> None:
    world = build_mcp_world(tmp_path, monkeypatch, pg_factory, lifespans, mcp_environment={})

    posted = world.world.client.post("/mcp", headers=world.agent())
    fetched = world.world.client.get("/mcp", headers=world.agent())
    metadata = world.world.client.get("/.well-known/oauth-protected-resource/mcp")

    assert (posted.status_code, posted.json()) == (403, {"detail": "Missing Origin header"})
    for page in (fetched, metadata):
        assert page.headers["content-type"].startswith("text/html")
    assert "www-authenticate" not in {*posted.headers, *fetched.headers, *metadata.headers}


@pytest.mark.parametrize("name", list(MCP_CLIENT_ENVIRONMENT))
def test_m13_one_mcp_value_without_the_other_stops_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory: sessionmaker, name: str,
) -> None:
    for key, value in {**AGENT_ENVIRONMENT, name: MCP_CLIENT_ENVIRONMENT[name]}.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()

    with pytest.raises(ValidationError, match="agent"):
        Settings()
    with pytest.raises(ValidationError, match="agent"):
        make_token_world(tmp_path, factory=pg_factory)


def test_m13_mcp_on_without_the_agent_group_stops_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory: sessionmaker,
) -> None:
    for key, value in {**AGENT_ENVIRONMENT, **MCP_CLIENT_ENVIRONMENT}.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()

    with pytest.raises(ValidationError, match="mcp_agent_group"):
        Settings()
    with pytest.raises(ValidationError, match="mcp_agent_group"):
        make_token_world(tmp_path, factory=pg_factory)


# -- M14: the browser is unchanged -------------------------------------------------------


_SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin", "Origin": TEST_ORIGIN}
_FORGED = {"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.test"}
_MARKED_ROUTES = [
    ("GET", "/api/albums", None),
    ("POST", "/api/albums", {"title": "Browser"}),
    ("GET", "/api/songs", None),
    ("POST", "/api/songs", {"title": "Browser", "album_id": "album-alices"}),
    ("GET", "/api/songs/song-alices", None),
    ("POST", "/api/songs/song-alices/generate", {"model": "sft"}),
]
_MARKED_IDS = ["list_albums", "create_album", "list_songs", "create_song", "get_song",
               "generate_song"]


@pytest.mark.parametrize(("method", "path", "body"), _MARKED_ROUTES, ids=_MARKED_IDS)
def test_m14_a_cookie_session_with_csrf_still_succeeds_on_each_marked_route(
    mcp: McpWorld, method: str, path: str, body: dict | None,
) -> None:
    mcp.world.seed_take(TokenWorld.ALICE, "alices")
    seed_session(mcp.world.client, "alice")

    with worker_ready():
        reply = mcp.world.client.request(method, path, json=body, headers=_SAME_ORIGIN)

    assert reply.status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "body"), [route for route in _MARKED_ROUTES if route[0] == "POST"],
    ids=[name for name, route in zip(_MARKED_IDS, _MARKED_ROUTES, strict=True)
         if route[0] == "POST"],
)
def test_m14_a_cookie_request_without_csrf_is_refused_on_each_state_changing_marked_route(
    mcp: McpWorld, method: str, path: str, body: dict | None,
) -> None:
    mcp.world.seed_take(TokenWorld.ALICE, "alices")
    seed_session(mcp.world.client, "alice")

    with worker_ready() as pool:
        reply = mcp.world.client.request(method, path, json=body, headers=_FORGED)

    assert reply.status_code == 403
    assert mcp.rows_of(Album, "id") == [("album-alices",)]
    assert mcp.rows_of(Song, "id") == [("song-alices",)]
    assert mcp.rows_of(Job, "id") == []
    pool.enqueue_job.assert_not_called()


def test_m14_an_unmarked_route_keeps_working_with_the_cookie(mcp: McpWorld) -> None:
    mcp.world.seed_take(TokenWorld.ALICE, "alices")
    seed_session(mcp.world.client, "alice")

    reply = mcp.world.client.post("/api/generations/take-alices/pick", headers=_SAME_ORIGIN)

    assert reply.status_code == 200


def test_the_browser_lists_its_own_takes_and_reads_its_lora_at_the_new_paths_with_the_cookie(
    mcp: McpWorld,
) -> None:
    mcp.seed_household(TokenWorld.ALICE, "alices")
    seed_session(mcp.world.client, "alice")

    takes = mcp.world.client.get("/api/own-playable-takes", headers=_SAME_ORIGIN)
    lora = mcp.world.client.get("/api/loras/lora-alices", headers=_SAME_ORIGIN)

    assert (takes.status_code, lora.status_code) == (200, 200)
    assert [take["generation_id"] for take in takes.json()["takes"]] == ["take-alices"]
    assert lora.json()["id"] == "lora-alices"


# -- M15, M16, M17: generation ------------------------------------------------------------


def test_m15_generate_queues_a_job_for_the_person_as_the_api_queues_it(mcp: McpWorld) -> None:
    mcp.world.seed_take(TokenWorld.ALICE, "alices")

    with worker_ready() as pool:
        reply = mcp.call("generate_song", {"song_id": "song-alices", "model": "sft"})

    assert (reply.is_error, reply.json()["type"]) == (False, "generate")
    assert mcp.rows_of(Job, "user_id", "song_id", "type") == [
        (TokenWorld.ALICE, "song-alices", "generate"),
    ]
    pool.enqueue_job.assert_called_once()


def test_m16_generate_for_another_persons_song_or_a_song_without_lyrics_queues_nothing(
    mcp: McpWorld,
) -> None:
    mcp.world.seed_take(TokenWorld.BOB, "bobs")
    bare = mcp.seed_song_without_lyrics(TokenWorld.ALICE)

    with worker_ready() as pool:
        others = mcp.call("generate_song", {"song_id": "song-bobs", "model": "sft"})
        empty = mcp.call("generate_song", {"song_id": bare, "model": "sft"})

    assert "Not Found" in others.text
    assert "lyrics" in empty.text
    assert (others.is_error, empty.is_error) == (True, True)
    assert mcp.rows_of(Job, "id") == []
    pool.enqueue_job.assert_not_called()


def test_m17_generate_past_the_persons_limit_gets_the_apis_refusal_and_no_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory: sessionmaker,
    lifespans: ExitStack,
) -> None:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    world = build_mcp_world(tmp_path, monkeypatch, pg_factory, lifespans, generation_limit=1)
    world.world.seed_take(TokenWorld.ALICE, "alices")

    with worker_ready():
        first = world.call("generate_song", {"song_id": "song-alices", "model": "sft"})
        second = world.call("generate_song", {"song_id": "song-alices", "model": "sft"})
        api = world.world.client.post(
            "/api/songs/song-alices/generate", json={"model": "sft"}, headers=world.agent(),
        )

    assert first.is_error is False
    assert second.is_error is True
    assert second.json() == api.json()
    assert len(world.rows_of(Job, "id")) == 1


# -- M19, M20, M21, M26: the marked routes and the other gates --------------------------


def test_m19_the_agent_token_on_a_marked_route_without_mcp_is_the_person(mcp: McpWorld) -> None:
    mcp.world.seed_take(TokenWorld.ALICE, "alices")
    mcp.world.seed_take(TokenWorld.BOB, "bobs")

    reply = mcp.world.client.get("/api/songs", headers=mcp.agent())

    assert [item["title"] for item in reply.json()["items"]] == ["Song alices"]


def test_m20_a_hal_person_token_on_a_marked_route_works_as_before(mcp: McpWorld) -> None:
    mcp.world.seed_take(TokenWorld.ALICE, "alices")

    reply = mcp.world.client.get("/api/songs", headers=mcp.world.bearer(TokenWorld.ALICE))

    assert [item["title"] for item in reply.json()["items"]] == ["Song alices"]


def test_m21_a_valid_cookie_beside_an_invalid_bearer_is_401_and_creates_nothing(
    mcp: McpWorld,
) -> None:
    mcp.world.seed_take(TokenWorld.ALICE, "alices")
    seed_session(mcp.world.client, "alice")

    reply = mcp.world.client.post(
        "/api/songs", json={"title": "Nope", "album_id": "album-alices"},
        headers={"Authorization": "Bearer not.a.token", "Sec-Fetch-Site": "same-origin"},
    )

    assert reply.status_code == 401
    assert mcp.rows_of(Song, "title") == [("Song alices",)]


def test_m26_with_no_token_client_the_resource_still_admits_and_person_paths_refuse_a_bearer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory: sessionmaker,
    lifespans: ExitStack,
) -> None:
    monkeypatch.delenv("TOKEN_CLIENTS", raising=False)
    world = build_mcp_world(tmp_path, monkeypatch, pg_factory, lifespans)
    world.world.seed_take(TokenWorld.ALICE, "alices")

    listed = world.call("list_songs")
    person_token = world.world.client.get("/api/songs", headers=world.world.bearer())
    media = world.world.client.get(
        f"/audio/{TokenWorld.ALICE}/alices.mp3", headers=world.world.bearer(),
    )

    assert [item["title"] for item in listed.json()["items"]] == ["Song alices"]
    assert person_token.status_code == 401
    assert media.status_code == 401


# -- M25: the gate's marks resolve to the marked operations -------------------------------


class _EndpointRecorder:
    """Outermost middleware that notes which endpoint the router resolved for each request."""

    def __init__(self, app: ASGIApp, resolved: list[tuple[str, str, str]]) -> None:
        self.app = app
        self.resolved = resolved

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)
        endpoint = scope.get("endpoint")
        self.resolved.append(
            (scope["method"], scope["path"], getattr(endpoint, "__name__", "unrouted")),
        )


def test_m25_each_marked_method_and_template_resolves_to_its_marked_endpoint(
    mcp: McpWorld,
) -> None:
    app = mcp.world.client.app
    resolved: list[tuple[str, str, str]] = []
    # The lifespan has already built the stack; the next request builds it again with the recorder.
    app.middleware_stack = None
    app.add_middleware(_EndpointRecorder, resolved=resolved)
    marks = collect_route_tools(app).marks
    operations = app.openapi()["paths"]

    for mark in marks:
        path = mark.template.replace("{song_id}", "some-id")
        mcp.world.client.request(mark.method, path, json={}, headers=mcp.agent())

    expected = {
        (mark.method, mark.template.replace("{song_id}", "some-id")): operations[mark.template][
            mark.method.lower()
        ]["operationId"]
        for mark in marks
    }
    assert len(marks) == len(MARKED_TOOLS)
    assert {(method, path) for method, path, _ in resolved} == expected.keys()
    for method, path, endpoint_name in resolved:
        assert expected[(method, path)].startswith(f"{endpoint_name}_")
