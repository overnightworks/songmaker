"""A person's own agent on ``/mcp`` and on the marked routes, against a fake Keycloak realm.

Every case drives the real app through the ASGI client; the relying party verifies the tokens
exactly as in production and only its key set is the fake issuer's. Matrix cells M1 to M26 of
the work item are named in the case ids.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from agent_runtime_client.mcp_wire import LATEST_PROTOCOL_VERSION as PROTOCOL_VERSION
from agent_runtime_client.mcp_wire import PROTOCOL_VERSION_HEADER as PROTOCOL_HEADER
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker
from starlette.types import ASGIApp, Receive, Scope, Send
from support.token_world import TokenWorld, make_token_world
from support.web_app import TEST_ORIGIN, seed_session, seed_user

from songmaker_cli.agent.mcp import collect_route_tools
from songmaker_cli.constants import OIDC_ADMIN_GROUP, OIDC_LOGIN_GROUP, OIDC_MCP_GROUP
from songmaker_cli.db.models import Album, Generation, Job, Song, Version
from songmaker_cli.settings import Settings, get_settings

AGENTS_CLIENT = "agents"
MCP_SCOPE = "songmaker:mcp"
RESOURCE_URL = "https://songmaker.test/mcp"
METADATA_URL = "https://songmaker.test/.well-known/oauth-protected-resource/mcp"
SIX_TOOLS = {
    "list_albums", "create_album", "list_songs", "create_song", "get_song", "generate_song",
}
_AGENT_ENVIRONMENT = {
    "AGENT__BACKEND": "litellm",
    "AGENT__GATEWAY__ORIGIN": "http://gateway.test:4000",
    "AGENT__GATEWAY__KEY_FILE": "/run/secrets/gateway_key",
    "AGENT__API_GROUP": "/apps/songmaker/api",
}
_MCP_ENVIRONMENT = {"AGENT__MCP_CLIENT_ID": AGENTS_CLIENT, "AGENT__MCP_SCOPE": MCP_SCOPE}


@dataclass(frozen=True)
class ToolReply:
    http_status: int
    is_error: bool
    text: str

    def json(self) -> object:
        return json.loads(self.text)


@dataclass
class McpWorld:
    """The token world with the MCP endpoint on, and an agent's header-exact requests."""

    world: TokenWorld

    def agent_token(
        self,
        subject: str = TokenWorld.ALICE,
        *,
        groups: tuple[str, ...] = (OIDC_LOGIN_GROUP, OIDC_MCP_GROUP),
        **claims: object,
    ) -> str:
        return self.world.token(
            subject,
            groups=groups,
            **{"aud": RESOURCE_URL, "azp": AGENTS_CLIENT, "scope": MCP_SCOPE, **claims},
        )

    def agent(self, subject: str = TokenWorld.ALICE, **options: object) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.agent_token(subject, **options)}"}

    def rpc(self, method: str, params: dict | None = None, *, headers: dict[str, str]):
        message = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        return self.world.client.post(
            "/mcp", json=message, headers={**headers, PROTOCOL_HEADER: str(PROTOCOL_VERSION)},
        )

    def tool_names(self, **options: object) -> set[str]:
        reply = self.rpc("tools/list", headers=self.agent(**options))
        return {tool["name"] for tool in reply.json()["result"]["tools"]}

    def call(self, tool: str, arguments: dict | None = None, **options: object) -> ToolReply:
        reply = self.rpc(
            "tools/call", {"name": tool, "arguments": arguments or {}},
            headers=self.agent(**options),
        )
        result = reply.json()["result"]
        return ToolReply(reply.status_code, result.get("isError", False),
                         result["content"][0]["text"])

    def seed_people(self, *, alice_role: str = "user") -> None:
        with self.world.factory() as session:
            seed_user(session, "alice", alice_role, user_id=TokenWorld.ALICE)
            seed_user(session, "bob", user_id=TokenWorld.BOB)
            session.commit()

    def seed_song_without_lyrics(self, owner: str) -> str:
        with self.world.factory() as session:
            session.add(Album(id="album-bare", title="Bare", artist="", created_by=owner))
            session.add(Song(id="song-bare", title="Bare", album_id="album-bare",
                             track_number=1, slug="song-bare"))
            session.add(Version(id="version-bare", song_id="song-bare", version_number=1,
                                lyrics="", prompt=""))
            session.commit()
        return "song-bare"

    def rows_of(self, model: type, *columns: str) -> list[tuple]:
        return self.world.rows(model, *columns)


def _build_world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    factory: sessionmaker,
    *,
    alice_role: str = "user",
    generation_limit: int = 30,
    mcp_environment: dict[str, str] | None = None,
) -> McpWorld:
    environment = {**_AGENT_ENVIRONMENT, **(_MCP_ENVIRONMENT if mcp_environment is None
                                           else mcp_environment)}
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("GENERATION_RATE_LIMIT_USER", str(generation_limit))
    mcp_world = McpWorld(make_token_world(tmp_path, factory=factory))
    mcp_world.seed_people(alice_role=alice_role)
    return mcp_world


@pytest.fixture
def mcp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory) -> McpWorld:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    return _build_world(tmp_path, monkeypatch, pg_factory)


@contextmanager
def _worker_ready():
    pool = AsyncMock()
    with (
        patch("songmaker_cli.generation_api.get_arq_pool", return_value=pool),
        patch("songmaker_cli.generation_api.is_music_worker_healthy", AsyncMock(return_value=True)),
        patch("songmaker_cli.generation_api.is_scoring_worker_healthy",
              AsyncMock(return_value=True)),
        patch("songmaker_cli.generation_api._has_online_acestep_worker",
              AsyncMock(return_value=True)),
    ):
        yield pool


# -- M1: exactly the six tools ---------------------------------------------------------


def test_m1_a_members_agent_is_offered_exactly_the_six_tools(mcp: McpWorld) -> None:
    assert mcp.tool_names() == SIX_TOOLS


def test_m1_the_description_of_generate_names_the_valid_models(mcp: McpWorld) -> None:
    reply = mcp.rpc("tools/list", headers=mcp.agent())
    generate = next(
        tool for tool in reply.json()["result"]["tools"] if tool["name"] == "generate_song"
    )

    assert all(model in generate["description"] for model in ("turbo", "sft", "xl-base"))


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
) -> None:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    world = _build_world(tmp_path, monkeypatch, pg_factory, alice_role="admin")
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
) -> None:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    world = _build_world(tmp_path, monkeypatch, pg_factory, alice_role="admin")
    world.world.seed_take(TokenWorld.BOB, "bobs")
    groups = (OIDC_LOGIN_GROUP, OIDC_ADMIN_GROUP, OIDC_MCP_GROUP)

    with _worker_ready() as pool:
        into = world.call("create_song", {"title": "x", "album_id": "album-bobs"}, groups=groups)
        generated = world.call(
            "generate_song", {"song_id": "song-bobs", "model": "sft"}, groups=groups,
        )

    assert (into.is_error, generated.is_error) == (True, True)
    assert "Not Found" in into.text
    assert "Not Found" in generated.text
    assert world.rows_of(Job, "id") == []
    pool.enqueue_job.assert_not_called()


# -- M6: what the agent's token cannot reach ------------------------------------------

_UNMARKED_ROUTES = [
    ("POST", "/api/generations/bulk-delete", {"generation_ids": ["take-alices"]}),
    ("DELETE", "/api/generations/take-alices", None),
    ("POST", "/api/albums/album-alices/share", None),
    ("POST", "/api/songs/song-alices/repaint", None),
    ("DELETE", "/api/playlists/any", None),
    ("DELETE", "/api/albums/album-alices", None),
]


@pytest.mark.parametrize(
    ("method", "path", "body"), _UNMARKED_ROUTES,
    ids=["bulk-delete", "take-delete", "share", "repaint", "playlist-delete", "album-delete"],
)
def test_m6_the_agent_token_is_refused_on_every_unmarked_route_and_nothing_changes(
    mcp: McpWorld, method: str, path: str, body: dict | None,
) -> None:
    mcp.world.seed_take(TokenWorld.ALICE, "alices")

    reply = mcp.world.client.request(method, path, json=body, headers=mcp.agent())

    assert reply.status_code in {401, 403}
    assert mcp.rows_of(Generation, "id") == [("take-alices",)]
    assert [row[0] for row in mcp.rows_of(Album, "deleted_at")] == [None]


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
    assert mcp.tool_names(groups=(OIDC_MCP_GROUP,)) == SIX_TOOLS


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
) -> None:
    world = _build_world(tmp_path, monkeypatch, pg_factory, mcp_environment={})

    posted = world.world.client.post("/mcp", headers=world.agent())
    fetched = world.world.client.get("/mcp", headers=world.agent())
    metadata = world.world.client.get("/.well-known/oauth-protected-resource/mcp")

    assert (posted.status_code, posted.json()) == (403, {"detail": "Missing Origin header"})
    for page in (fetched, metadata):
        assert page.headers["content-type"].startswith("text/html")
    assert "www-authenticate" not in {*posted.headers, *fetched.headers, *metadata.headers}


@pytest.mark.parametrize("name", list(_MCP_ENVIRONMENT))
def test_m13_one_mcp_value_without_the_other_stops_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory: sessionmaker, name: str,
) -> None:
    for key, value in {**_AGENT_ENVIRONMENT, name: _MCP_ENVIRONMENT[name]}.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()

    with pytest.raises(ValidationError, match="agent"):
        Settings()
    with pytest.raises(ValidationError, match="agent"):
        make_token_world(tmp_path, factory=pg_factory)


# -- M14: the browser is unchanged -------------------------------------------------------


def test_m14_a_cookie_session_still_works_on_marked_routes_and_csrf_still_refuses_forgery(
    mcp: McpWorld,
) -> None:
    mcp.world.seed_take(TokenWorld.ALICE, "alices")
    seed_session(mcp.world.client, "alice")
    same_origin = {"Sec-Fetch-Site": "same-origin", "Origin": TEST_ORIGIN}
    forged = {"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.test"}

    listed = mcp.world.client.get("/api/songs", headers=same_origin)
    created = mcp.world.client.post(
        "/api/songs", json={"title": "Browser", "album_id": "album-alices"}, headers=same_origin,
    )
    forged_create = mcp.world.client.post(
        "/api/songs", json={"title": "Forged", "album_id": "album-alices"}, headers=forged,
    )
    forged_archive = mcp.world.client.post("/api/albums/album-alices/archive", headers=forged)

    assert (listed.status_code, created.status_code) == (200, 200)
    assert (forged_create.status_code, forged_archive.status_code) == (403, 403)
    assert sorted(title for _, title in mcp.rows_of(Song, "id", "title")) == [
        "Browser", "Song alices",
    ]


# -- M15, M16, M17: generation ------------------------------------------------------------


def test_m15_generate_queues_a_job_for_the_person_as_the_api_queues_it(mcp: McpWorld) -> None:
    mcp.world.seed_take(TokenWorld.ALICE, "alices")

    with _worker_ready() as pool:
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

    with _worker_ready() as pool:
        others = mcp.call("generate_song", {"song_id": "song-bobs", "model": "sft"})
        empty = mcp.call("generate_song", {"song_id": bare, "model": "sft"})

    assert "Not Found" in others.text
    assert "lyrics" in empty.text
    assert (others.is_error, empty.is_error) == (True, True)
    assert mcp.rows_of(Job, "id") == []
    pool.enqueue_job.assert_not_called()


def test_m17_generate_past_the_persons_limit_gets_the_apis_refusal_and_no_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory: sessionmaker,
) -> None:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    world = _build_world(tmp_path, monkeypatch, pg_factory, generation_limit=1)
    world.world.seed_take(TokenWorld.ALICE, "alices")

    with _worker_ready():
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
) -> None:
    monkeypatch.delenv("TOKEN_CLIENTS", raising=False)
    world = _build_world(tmp_path, monkeypatch, pg_factory)
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
    assert len(marks) == len(SIX_TOOLS)
    assert {(method, path) for method, path, _ in resolved} == expected.keys()
    for method, path, endpoint_name in resolved:
        assert expected[(method, path)].startswith(f"{endpoint_name}_")
