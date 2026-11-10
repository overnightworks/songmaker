"""1301-F2: owner-only authorization through both public tool dispatchers."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from agents.backend.fake_gateway import completion
from agents.tools import Principal
from support.cowriter_gateway import attach_cowriter_gateway
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.agent.tools import CallingTurn, bound_to_turn, cowriter_hand_tools
from songmaker_cli.auth_stores import DatabaseSessionRecordStore
from songmaker_cli.cowriter.tools import COWRITER_TOOLS, execute_cowriter_tool
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
from songmaker_cli.mcp_server import auth


@pytest.fixture
def ownership_factory(pg_factory):
    factory = pg_factory
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
USER_TOOL_NAMES = sorted(tool.name for tool in COWRITER_TOOLS if tool.name != VERDICT_TOOL)


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


def test_ownership_matrix_covers_every_registered_tool():
    """1301-F2-TOOLS, 1301-F2-ENTRY: adding a tool requires an ownership row."""
    assert set(_ownership_arguments("actor")) == {tool.name for tool in COWRITER_TOOLS}


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


@pytest.mark.parametrize("name", USER_TOOL_NAMES)
@pytest.mark.parametrize("role", ["user", "admin"])
@pytest.mark.parametrize("identity", ["actor", "foreign"])
@pytest.mark.parametrize("route", ["in-process", "hand-tool"])
def test_tools_only_reach_owned_resources(
    ownership_factory, monkeypatch, name, role, identity, route,
):
    """Spec: REQ-COWRITER-12 -- 1301-F2-TOOLS, 1301-F2-ENTRY: enforce ownership before work."""
    with ownership_factory() as session:
        session.get(User, "actor").role = role
        session.commit()
    is_error, payload = _dispatch_ownership_tool(
        ownership_factory, monkeypatch, route, name, _ownership_arguments(identity)[name],
    )
    denied = identity == "foreign" and name not in {"list_albums", "search_songs"}
    assert is_error is denied
    if denied:
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
        cover = own_write and name == "suggest_album_cover"
        created = own_write and name == "create_song"
        edited = own_write and not cover
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
@pytest.mark.parametrize("route", ["in-process", "hand-tool"])
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


def _turn_client(ownership_factory, tmp_path, role):
    with ownership_factory() as session:
        session.get(User, "actor").role = role
        session.add(Song(
            id="song-actor-second", title="Second track", album_id="album-actor",
            track_number=2, slug="second",
        ))
        session.add(Version(
            id="version-actor-second", song_id="song-actor-second", version_number=1,
            lyrics="second words", prompt="folk",
        ))
        session.commit()
    user = make_authenticated_user("actor", role=role)
    app = make_router_app(make_router_ctx(tmp_path, db=ownership_factory), user=user)
    client = web_client(app)
    stack = attach_cowriter_gateway(client, ownership_factory, tmp_path, "actor")
    stack.replies(completion("Done"))
    return client, stack


@pytest.mark.parametrize("role", ["user", "admin"])
def test_a_turn_with_the_persons_own_song_mentions_and_take_carries_their_context(
    ownership_factory, tmp_path, role,
):
    client, stack = _turn_client(ownership_factory, tmp_path, role)

    response = client.post("/api/chat/turn", json={
        "message": "go on",
        "current_song_id": "song-actor",
        "mentioned_song_ids": ["song-actor-second"],
        "mentioned_album_id": "album-actor",
        "current_generation_id": "generation-actor",
    })

    assert response.status_code == 200
    context = stack.last_turn.messages[-1]["text"]
    assert "Track actor" in context
    assert "Second track" in context
    assert "sung words" in context
    assert "<mentioned_album>" in context


@pytest.mark.parametrize("turn", [
    {"current_song_id": "song-foreign"},
    {"current_song_id": "song-actor", "mentioned_song_ids": ["song-foreign"]},
    {"current_song_id": "song-actor", "current_generation_id": "generation-foreign"},
], ids=["current-song", "mentioned-song", "take"])
def test_an_admins_turn_with_another_persons_content_answers_404_and_creates_no_job(
    ownership_factory, tmp_path, turn,
):
    client, stack = _turn_client(ownership_factory, tmp_path, "admin")

    response = client.post("/api/chat/turn", json={"message": "edit this", **turn})

    assert response.status_code == 404
    with ownership_factory() as session:
        assert session.query(Job).count() == 0
    assert stack.gateway_requests == []


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
