"""1301-F2: owner-only authorization through both public tool dispatchers."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from agent_runtime_client.backend.fake_gateway import completion, tool_call, tool_round
from agent_runtime_client.tools import Principal
from mcp.server.mcpserver.exceptions import ToolError
from support.cowriter_gateway import attach_cowriter_gateway
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.agent.tools import CallingTurn, bound_to_turn, cowriter_hand_tools
from songmaker_cli.auth_stores import DatabaseSessionRecordStore
from songmaker_cli.cowriter.mcp_spec import MCP_TOOL_NAMES
from songmaker_cli.cowriter.tools import COWRITER_TOOLS, execute_cowriter_tool
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import (
    Album,
    Generation,
    Job,
    Score,
    Song,
    User,
    UserSession,
    UserSongWork,
    Version,
)
from songmaker_cli.mcp_server import auth, server


@pytest.fixture
def ownership_factory(tmp_path):
    factory = init_test_db(tmp_path / "ownership.db")
    with factory() as session:
        for identity in ("actor", "foreign"):
            session.add(User(id=identity, username=identity, role="user"))
            session.flush()
            session.add(Album(
                id=f"album-{identity}", title=identity, artist=identity, created_by=identity,
            ))
            session.add(Song(
                id=f"song-{identity}", title=f"Track {identity}",
                album_id=f"album-{identity}", track_number=1,
            ))
            session.add(Version(
                id=f"version-{identity}", song_id=f"song-{identity}",
                version_number=1, lyrics="original", prompt="rock",
            ))
            session.add(Generation(
                id=f"generation-{identity}", song_id=f"song-{identity}",
                version_id=f"version-{identity}", generation_number=1,
                mp3_path=f"{identity}/take.mp3", whisper_text="sung words",
            ))
            session.add(Score(
                generation_id=f"generation-{identity}", scorer="batch",
                value={"bpm_detected": 96.0},
            ))
        now = datetime.now(timezone.utc)
        DatabaseSessionRecordStore(session).create(
            "actor", now=now, expires_at=now + timedelta(hours=1),
            refresh_token=None, id_token=None,
        )
        session.commit()
    return factory


def _actor_session_id(factory) -> str:
    with factory() as session:
        return session.query(UserSession).filter_by(user_id="actor").one().id


VERDICT_TOOL = "save_coherence_verdict"


def _ownership_arguments(identity):
    song = {"song_id": f"song-{identity}"}
    album = {"album_id": f"album-{identity}"}
    return {
        "list_albums": {},
        "list_songs": album,
        "search_songs": {"query": identity},
        "get_song": song,
        "get_version": {**song, "version_id": f"version-{identity}"},
        "get_generation": {"generation_id": f"generation-{identity}"},
        "create_song": {**album, "title": "New track"},
        "update_song_lyrics": {**song, "lyrics": "changed"},
        "update_song_prompt": {**song, "prompt": "jazz"},
        "update_song_style": {**song, "bpm": 90},
        "rename_song": {**song, "title": "Renamed"},
        "suggest_album_cover": album,
        VERDICT_TOOL: {
            "generation_id": f"generation-{identity}", "score": 8, "summary": "Coherent.",
        },
    }


def _dispatch_ownership_tool(factory, monkeypatch, route, name, arguments):
    if route == "mcp":
        monkeypatch.setenv(auth.USER_ID_ENV, "actor")
        srv = server.build_server(session_factory=factory)
        try:
            result = asyncio.run(srv.call_tool(name, arguments))
        except ToolError as exc:
            return True, str(exc)
        payload = result.structured_content
        if payload is None:
            payload = json.loads(result.content[0].text)
        if isinstance(payload, dict) and set(payload) == {"result"}:
            payload = payload["result"]
        return False, payload
    if route == "hand-tool":
        hand_tool = next(t for t in cowriter_hand_tools(factory) if t.declaration.name == name)
        principal = Principal(iss="issuer.test", sub="actor")
        with bound_to_turn(CallingTurn(_actor_session_id(factory))):
            result = asyncio.run(hand_tool.handler(principal, arguments))
        return result.is_error, result.content if result.is_error else json.loads(result.content)
    with factory() as session:
        result = execute_cowriter_tool(
            session, auth.load_user(session, "actor"), name, arguments,
            session_id=_actor_session_id(factory),
        )
    return result.is_error, result.content if result.is_error else json.loads(result.content)


def test_ownership_matrix_covers_every_registered_tool(ownership_factory):
    """1301-F2-TOOLS, 1301-F2-ENTRY: adding a tool requires an ownership row."""
    registered = asyncio.run(server.build_server(session_factory=ownership_factory).list_tools())
    catalog = {tool.name for tool in COWRITER_TOOLS}
    assert catalog == MCP_TOOL_NAMES | {VERDICT_TOOL}
    assert set(_ownership_arguments("actor")) == catalog
    assert {tool.name for tool in registered} == MCP_TOOL_NAMES


def _assert_owned_answer(name, identity, payload):
    if name == "list_albums":
        assert [album["id"] for album in payload] == ["album-actor"]
    elif name in {"list_songs", "search_songs"}:
        assert [song["id"] for song in payload] == (
            [] if identity == "foreign" else ["song-actor"]
        )
    elif name in {"get_song", "get_version", "get_generation"}:
        expected_id = _ownership_arguments(identity)[name][
            {
                "get_song": "song_id", "get_version": "version_id",
                "get_generation": "generation_id",
            }[name]
        ]
        assert payload["id"] == expected_id
    elif name == "suggest_album_cover":
        assert payload["status"] == "queued"
    else:
        assert payload["ok"] is True


@pytest.mark.parametrize("name", sorted(MCP_TOOL_NAMES))
@pytest.mark.parametrize("role", ["user", "admin"])
@pytest.mark.parametrize("identity", ["actor", "foreign"])
@pytest.mark.parametrize("route", ["mcp", "in-process", "hand-tool"])
def test_tools_only_reach_owned_resources(
    ownership_factory, monkeypatch, name, role, identity, route,
):
    """1301-F2-TOOLS, 1301-F2-ENTRY: enforce ownership before work."""
    with ownership_factory() as session:
        session.get(User, "actor").role = role
        session.commit()
    is_error, payload = _dispatch_ownership_tool(
        ownership_factory, monkeypatch, route, name, _ownership_arguments(identity)[name],
    )
    browser_only = route == "mcp" and name == "suggest_album_cover"
    denied = identity == "foreign" and name not in {"list_albums", "search_songs"}
    assert is_error is (denied or browser_only)
    if browser_only:
        assert "need a browser login" in payload
    elif denied:
        assert "not found" in payload
    else:
        _assert_owned_answer(name, identity, payload)

    with ownership_factory() as session:
        foreign = session.get(Song, "song-foreign")
        assert foreign.title == "Track foreign"
        assert foreign.latest_version.lyrics == "original"
        assert foreign.latest_version.prompt == "rock"
        assert len(foreign.versions) == 1
        own_write = identity == "actor" and name in {
            tool.name for tool in COWRITER_TOOLS if tool.write
        }
        cover = own_write and name == "suggest_album_cover" and not browser_only
        created = own_write and name == "create_song"
        edited = own_write and name != "suggest_album_cover"
        assert session.query(Song).count() == 2 + created
        assert session.query(Version).count() == 2 + edited
        assert session.query(UserSongWork).count() == int(edited)
        assert session.query(Job).count() == int(cover)
        if edited:
            work = session.query(UserSongWork).one()
            assert work.user_id == "actor"
            assert session.get(Song, work.song_id).album_id == "album-actor"
        if cover:
            job = session.query(Job).one()
            assert (job.album_id, job.user_id) == ("album-actor", "actor")


@pytest.mark.parametrize("role", ["user", "admin"])
@pytest.mark.parametrize("route", ["mcp", "in-process", "hand-tool"])
def test_unfiltered_song_listing_still_filters_by_owner(
    ownership_factory, monkeypatch, role, route,
):
    """1301-F2-TOOLS, 1301-F2-ENTRY: omitting album_id never broadens access."""
    with ownership_factory() as session:
        session.get(User, "actor").role = role
        session.commit()
    is_error, payload = _dispatch_ownership_tool(
        ownership_factory, monkeypatch, route, "list_songs", {},
    )
    assert is_error is False
    assert [song["id"] for song in payload] == ["song-actor"]


def test_admin_foreign_context_loads_but_tool_access_is_denied(ownership_factory, tmp_path):
    """1301-F2-BOUNDARY: user-selected foreign context retains HTTP admin access."""
    with ownership_factory() as session:
        session.get(User, "actor").role = "admin"
        session.commit()
    user = make_authenticated_user("actor", role="admin")
    app = make_router_app(make_router_ctx(tmp_path, db=ownership_factory), user=user)
    client = web_client(app)
    stack = attach_cowriter_gateway(client, ownership_factory, tmp_path, "actor")
    stack.replies(
        tool_round(tool_call("call-1", "get_song", {"song_id": "song-foreign"})),
        completion("Cannot edit this song"),
    )

    response = client.post(
        "/api/chat/turn",
        json={"message": "edit this", "current_song_id": "song-foreign"},
    )

    assert response.status_code == 200
    context = stack.last_turn.messages[-1]["text"]
    assert "<current_song>" in context
    assert "Track foreign" in context
    assert "original" in context
    frames = [
        json.loads(line[len("data: "):])
        for line in response.iter_lines()
        if line.startswith("data: ")
    ]
    result = next(frame for frame in frames if frame["type"] == "tool_result")
    assert result["is_error"] is True
    assert result["content"] == "Song not found"


@pytest.mark.parametrize("role", ["user", "admin"])
@pytest.mark.parametrize("identity", ["actor", "foreign"])
@pytest.mark.parametrize("route", ["in-process", "hand-tool"])
def test_the_coherence_verdict_is_stored_only_on_the_actors_own_take(
    ownership_factory, monkeypatch, role, identity, route,
):
    """REQ-COWRITER-34: the verdict reaches the owner's take and nothing else."""
    with ownership_factory() as session:
        session.get(User, "actor").role = role
        session.commit()
    is_error, payload = _dispatch_ownership_tool(
        ownership_factory, monkeypatch, route, VERDICT_TOOL,
        _ownership_arguments(identity)[VERDICT_TOOL],
    )

    own = identity == "actor"
    assert is_error is not own
    if not own:
        assert payload == "Generation not found"
    with ownership_factory() as session:
        stored = {
            row.generation_id: dict(row.value) for row in session.query(Score).all()
        }
        assert stored["generation-foreign"] == {"bpm_detected": 96.0}
        assert stored["generation-actor"] == (
            {"bpm_detected": 96.0, "lyrical_coherence": 8, "lyrical_summary": "Coherent."}
            if own else {"bpm_detected": 96.0}
        )
        assert session.query(Version).count() == 2
        assert session.query(UserSongWork).count() == 0
        assert session.query(Job).count() == 0
        assert session.query(Song).count() == 2
