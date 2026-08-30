"""Durable co-writer memory + turn-context envelope."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import TEST_SECRET, make_fake_redis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from songmaker_cli.app_context import AppContext
from songmaker_cli.claude.provider import AssistantTextEvent, FinalEvent
from songmaker_cli.constants import (
    TURN_BLOCK_ALBUM_NOTES,
    TURN_BLOCK_CURRENT_SONG,
    TURN_BLOCK_SONG_MEMORY,
    TURN_BLOCK_USER_MEMORY,
)
from songmaker_cli.conversation_api import compose_turn_context
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import (
    Album,
    AvailableModel,
    Song,
    User,
    Version,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user


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
        id=user_id, username=f"user-{user_id}", password_hash="x", role="user",
    ))
    session.flush()
    session.add(Album(id="alb1", title="Rock", artist="B", created_by=user_id))
    session.add(
        Song(id="s1", title="Thunder", album_id="alb1", track_number=1, slug="thunder"),
    )
    session.add(
        Song(id="s2", title="Rain", album_id="alb1", track_number=2, slug="rain"),
    )
    session.add(Version(
        id="v1", song_id="s1", version_number=1,
        lyrics="verse of thunder", prompt="rock", bpm=120, key_scale="Am",
        audio_duration=180,
    ))
    session.add(Version(
        id="v2", song_id="s2", version_number=1,
        lyrics="verse of rain", prompt="ballad", bpm=80, key_scale="C",
        audio_duration=200,
    ))
    session.query(AvailableModel).filter(
        AvailableModel.id.in_(["turbo", "sft"]),
    ).update({"is_active": True}, synchronize_session=False)
    session.commit()


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    factory = init_db(tmp_path / "memory.db")
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
    app.dependency_overrides[get_current_user] = _fake_user("u-test")
    app.include_router(router)
    yield TestClient(app), factory


@pytest.fixture()
def stranger_client(tmp_path: Path) -> TestClient:
    factory = init_db(tmp_path / "memory_spy.db")
    with factory() as session:
        _seed(session, "u-owner")
        session.add(User(id="u-spy", username="spy", password_hash="x", role="user"))
        session.commit()
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
    app.dependency_overrides[get_current_user] = _fake_user("u-spy")
    app.include_router(router)
    yield TestClient(app), factory


async def _capture_stream(*_args, **kwargs):
    _capture_stream.captured = kwargs
    yield AssistantTextEvent(text="ok")
    yield FinalEvent(text="ok")


def _last_user_content() -> str:
    messages = _capture_stream.captured["messages"]
    return messages[-1]["content"]


def test_compose_turn_context_keeps_named_scopes_once():
    song = Song(id="s1", title="Thunder", album_id="alb1")
    song.album = Album(id="alb1", title="Rock", artist="B")
    envelope = compose_turn_context(
        current_song=song,
        user_memory_body="prefer German",
        song_memory_body="locked chorus",
        album_notes_body="concept album",
    )
    names = envelope.names()
    assert names.count(TURN_BLOCK_USER_MEMORY) == 1
    assert names.count(TURN_BLOCK_SONG_MEMORY) == 1
    assert names.count(TURN_BLOCK_ALBUM_NOTES) == 1
    assert names.count(TURN_BLOCK_CURRENT_SONG) == 1
    wrapped = envelope.wrap_user_message("hello")
    assert "<user_memory>\nprefer German\n</user_memory>" in wrapped
    assert "lyrics:" not in envelope.body_for(TURN_BLOCK_USER_MEMORY)
    assert "lyrics:" not in envelope.body_for(TURN_BLOCK_SONG_MEMORY)


def test_compose_omits_empty_album_notes():
    song = Song(id="s1", title="Thunder", album_id="alb1")
    song.album = Album(id="alb1", title="Rock", artist="B")
    envelope = compose_turn_context(
        current_song=song,
        user_memory_body="",
        song_memory_body="",
        album_notes_body=None,
    )
    assert TURN_BLOCK_ALBUM_NOTES not in envelope.names()
    assert TURN_BLOCK_USER_MEMORY in envelope.names()
    assert TURN_BLOCK_SONG_MEMORY in envelope.names()


def test_put_and_get_memory_roundtrip(client):
    c, _ = client
    assert c.put("/api/memory/user", json={"body": "prefer German"}).status_code == 200
    assert c.put("/api/memory/songs/s1", json={"body": "locked chorus"}).status_code == 200
    assert c.put("/api/memory/albums/alb1", json={"body": "night city"}).status_code == 200
    bundle = c.get("/api/memory", params={"song_id": "s1"}).json()
    assert bundle["user"]["body"] == "prefer German"
    assert bundle["song"]["body"] == "locked chorus"
    assert bundle["album"]["body"] == "night city"


def test_memory_put_does_not_change_lyrics(client):
    c, factory = client
    c.put("/api/memory/songs/s1", json={"body": "do not copy lyrics"})
    with factory() as session:
        version = session.get(Version, "v1")
        assert version.lyrics == "verse of thunder"


def test_stranger_memory_is_404(stranger_client):
    c, _ = stranger_client
    assert c.get("/api/memory", params={"song_id": "s1"}).status_code == 404
    assert c.put("/api/memory/songs/s1", json={"body": "nope"}).status_code == 404
    assert c.put("/api/memory/albums/alb1", json={"body": "nope"}).status_code == 404
    assert c.get("/api/memory").json()["user"]["body"] == ""


def test_new_conversation_keeps_memory(client):
    c, _ = client
    c.put("/api/memory/user", json={"body": "standing rule"})
    c.put("/api/memory/songs/s1", json={"body": "open bridge"})
    c.post("/api/conversations/new")
    with patch(
        "songmaker_cli.conversation_api.stream_cowriter_turn",
        _capture_stream,
    ):
        resp = c.post(
            "/api/chat/turn",
            json={"message": "go", "current_song_id": "s1"},
        )
    assert resp.status_code == 200
    _stream_events(resp)
    content = _last_user_content()
    assert "<user_memory>\nstanding rule\n</user_memory>" in content
    assert "<song_memory>\nopen bridge\n</song_memory>" in content


def test_song_switch_swaps_song_memory_keeps_user_memory(client):
    c, _ = client
    c.put("/api/memory/user", json={"body": "taste"})
    c.put("/api/memory/songs/s1", json={"body": "memory A"})
    c.put("/api/memory/songs/s2", json={"body": "memory B"})
    with patch(
        "songmaker_cli.conversation_api.stream_cowriter_turn",
        _capture_stream,
    ):
        resp = c.post(
            "/api/chat/turn",
            json={"message": "work on rain", "current_song_id": "s2"},
        )
    _stream_events(resp)
    content = _last_user_content()
    assert "<user_memory>\ntaste\n</user_memory>" in content
    assert "<song_memory>\nmemory B\n</song_memory>" in content
    assert "memory A" not in content
    assert "Thunder" not in content


def test_proposal_in_assistant_text_does_not_write_memory(client):
    c, _ = client
    c.put("/api/memory/user", json={"body": "old"})
    proposal = (
        '<memory_proposal scope="user">\n'
        "<current>\nold\n</current>\n"
        "<proposed>\nnew standing rule\n</proposed>\n"
        "</memory_proposal>"
    )

    async def _with_proposal(*_a, **_k):
        yield AssistantTextEvent(text=proposal)
        yield FinalEvent(text=proposal)

    with patch(
        "songmaker_cli.conversation_api.stream_cowriter_turn",
        _with_proposal,
    ):
        resp = c.post("/api/chat/turn", json={"message": "remember this"})
    assert resp.status_code == 200
    _stream_events(resp)
    bundle = c.get("/api/memory").json()
    assert bundle["user"]["body"] == "old"
    saved = c.put("/api/memory/user", json={"body": "new standing rule"})
    assert saved.status_code == 200
    assert c.get("/api/memory").json()["user"]["body"] == "new standing rule"
