"""v2 co-writer @-mention resolution (#36)."""

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
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, AvailableModel, Song, User, Version
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
    session.add(Song(id="s1", title="Thunder", album_id="alb1", track_number=1))
    session.add(Song(id="s2", title="Rain", album_id="alb1", track_number=2))
    session.add(Version(
        id="v1", song_id="s1", version_number=1,
        lyrics="thunder lyrics", prompt="rock", bpm=120, key_scale="Am",
        audio_duration=180,
    ))
    session.add(Version(
        id="v1b", song_id="s1", version_number=2,
        lyrics="thunder v2 lyrics", prompt="rocker", bpm=130, key_scale="Em",
        audio_duration=190,
    ))
    session.add(Version(
        id="v2", song_id="s2", version_number=1,
        lyrics="rain lyrics", prompt="ballad", bpm=80, key_scale="C",
        audio_duration=200,
    ))
    session.query(AvailableModel).filter(
        AvailableModel.id.in_(["turbo", "sft"]),
    ).update({"is_active": True}, synchronize_session=False)
    session.commit()


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    factory = init_db(tmp_path / "mentions.db")
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
    yield TestClient(app)


@pytest.fixture()
def stranger_client(tmp_path: Path) -> TestClient:
    factory = init_db(tmp_path / "mentions_spy.db")
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
    yield TestClient(app)


async def _capture(*_args, **kwargs):
    _capture.called = True
    _capture.kwargs = kwargs
    yield AssistantTextEvent(text="ok")
    yield FinalEvent(text="ok")


def _turn(client: TestClient, payload: dict):
    _capture.called = False
    with patch(
        "songmaker_cli.conversation_api.acall_claude_with_mcp_stream",
        _capture,
    ):
        return client.post("/api/chat/turn", json=payload)


def test_mentioned_song_snapshot_is_server_loaded(client):
    resp = _turn(client, {
        "message": "compare",
        "current_song_id": "s1",
        "mentioned_song_ids": ["s2"],
    })
    assert resp.status_code == 200
    _stream_events(resp)
    content = _capture.kwargs["messages"][-1]["content"]
    assert "<mentioned_songs>" in content
    assert content.count("title: Rain") == 1
    assert "rain lyrics" in content
    assert "title: Thunder" in content
    assert "lyrics:\nrain lyrics" in content


def test_album_mention_loads_tracks_from_album_id_only(client):
    resp = _turn(client, {
        "message": "album vibe",
        "current_song_id": "s1",
        "mentioned_album_id": "alb1",
    })
    assert resp.status_code == 200
    _stream_events(resp)
    content = _capture.kwargs["messages"][-1]["content"]
    assert "<mentioned_album>" in content
    assert "title: Rock" in content
    assert "title: Thunder" in content
    assert "title: Rain" in content


def test_version_mention_uses_the_selected_version(client):
    resp = _turn(client, {
        "message": "old take on lyrics",
        "current_song_id": "s1",
        "mentioned_version_ids": ["v1"],
    })
    assert resp.status_code == 200
    _stream_events(resp)
    content = _capture.kwargs["messages"][-1]["content"]
    assert "<mentioned_versions>" in content
    assert "version_number: 1" in content
    assert "thunder lyrics" in content
    assert "thunder v2 lyrics" not in content.split("<mentioned_versions>")[1]


def test_duplicate_song_ids_emit_one_block(client):
    resp = _turn(client, {
        "message": "dup",
        "current_song_id": "s1",
        "mentioned_song_ids": ["s2", "s2"],
    })
    assert resp.status_code == 200
    _stream_events(resp)
    content = _capture.kwargs["messages"][-1]["content"]
    assert content.count("<mentioned_songs>") == 1
    assert content.count("title: Rain") == 1


def test_unknown_or_foreign_mention_is_404_before_provider(client, stranger_client):
    resp = _turn(client, {
        "message": "x",
        "current_song_id": "s1",
        "mentioned_song_ids": ["missing"],
    })
    assert resp.status_code == 404
    assert _capture.called is False

    resp = _turn(client, {
        "message": "x",
        "current_song_id": "s1",
        "mentioned_version_ids": ["v2"],
    })
    assert resp.status_code == 404
    assert _capture.called is False

    resp = _turn(client, {
        "message": "x",
        "current_song_id": "s1",
        "mentioned_album_id": "other",
    })
    assert resp.status_code == 404
    assert _capture.called is False

    resp = _turn(stranger_client, {
        "message": "x",
        "current_song_id": "s1",
        "mentioned_song_ids": ["s2"],
    })
    assert resp.status_code == 404
    assert _capture.called is False


def test_schema_accepts_current_generation_id_field(client):
    resp = _turn(client, {
        "message": "look at this take",
        "current_song_id": "s1",
        "current_generation_id": None,
    })
    assert resp.status_code == 200
    _stream_events(resp)
    assert _capture.called is True
