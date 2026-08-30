"""Co-writer take context: whisper, pick, keep, scores (#37)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import TEST_SECRET, make_fake_redis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from songmaker_cli.app_context import AppContext
from songmaker_cli.claude.provider import AssistantTextEvent, FinalEvent
from songmaker_cli.constants import JobType
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import (
    Album,
    AvailableModel,
    Generation,
    Job,
    Score,
    Song,
    User,
    Version,
)
from songmaker_cli.middleware import AuthenticatedUser, get_current_user

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


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
    session.add(Version(id="v1", song_id="s1", version_number=1, lyrics="written"))
    session.add(Version(id="v2", song_id="s2", version_number=1, lyrics="rain"))
    session.add(Generation(
        id="gA", song_id="s1", version_id="v1", generation_number=1,
        mp3_path="u/gA.mp3", is_picked=True, is_kept=True,
        whisper_text="sung A", created_at=T0,
    ))
    session.add(Generation(
        id="gB", song_id="s1", version_id="v1", generation_number=2,
        mp3_path="u/gB.mp3", is_picked=False, is_kept=False,
        whisper_text="sung B", created_at=T0 + timedelta(hours=1),
    ))
    session.add(Generation(
        id="gEmpty", song_id="s1", version_id="v1", generation_number=3,
        mp3_path="u/gEmpty.mp3", is_picked=False, whisper_text=None,
        created_at=T0 + timedelta(hours=2),
    ))
    session.add(Generation(
        id="gArch", song_id="s1", version_id="v1", generation_number=4,
        mp3_path="u/gArch.mp3", is_archived=True, created_at=T0,
    ))
    session.add(Generation(
        id="g2", song_id="s2", version_id="v2", generation_number=1,
        mp3_path="u/g2.mp3", is_picked=True, whisper_text="other song",
    ))
    session.add(Score(
        id="scA", generation_id="gA", scorer="text_accuracy",
        value={"score": 81.0},
    ))
    session.query(AvailableModel).filter(
        AvailableModel.id.in_(["turbo", "sft"]),
    ).update({"is_active": True}, synchronize_session=False)
    session.commit()


@pytest.fixture()
def client(tmp_path: Path):
    factory = init_db(tmp_path / "takes.db")
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
def stranger_client(tmp_path: Path):
    factory = init_db(tmp_path / "takes_spy.db")
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
        "songmaker_cli.conversation_api.stream_cowriter_turn",
        _capture,
    ):
        return client.post("/api/chat/turn", json=payload)


def _content() -> str:
    return _capture.kwargs["messages"][-1]["content"]


def test_playing_take_wins_over_pick(client):
    c, _ = client
    resp = _turn(c, {
        "message": "how did this take sing",
        "current_song_id": "s1",
        "current_generation_id": "gB",
    })
    assert resp.status_code == 200
    _stream_events(resp)
    body = _content()
    assert "<current_take>" in body
    assert "generation_id: gB" in body
    assert "whisper_text:\nsung B" in body
    assert "is_picked: false" in body
    assert "generation_id: gA" not in body.split("<current_take>")[1]


def test_without_player_uses_playable_pick(client):
    c, _ = client
    resp = _turn(c, {"message": "x", "current_song_id": "s1"})
    assert resp.status_code == 200
    _stream_events(resp)
    body = _content()
    assert "generation_id: gA" in body
    assert "whisper_text:\nsung A" in body
    assert "is_picked: true" in body
    assert "is_kept: true" in body
    assert "text_accuracy: 81.0" in body


def test_without_pick_uses_newest_playable(client):
    c, factory = client
    with factory() as session:
        session.query(Generation).filter_by(id="gA").update({"is_picked": False})
        session.commit()
    resp = _turn(c, {"message": "x", "current_song_id": "s1"})
    _stream_events(resp)
    assert "generation_id: gEmpty" in _content()


def test_no_playable_take_is_named_empty_state(client):
    c, factory = client
    with factory() as session:
        session.query(Generation).filter(Generation.song_id == "s1").update({
            "is_archived": True,
        })
        session.commit()
    resp = _turn(c, {"message": "x", "current_song_id": "s1"})
    _stream_events(resp)
    body = _content()
    assert "<no_take>" in body
    assert "no playable take" in body
    assert "<current_take>" not in body


def test_missing_whisper_and_scores_stay_empty(client):
    c, _ = client
    resp = _turn(c, {
        "message": "x",
        "current_song_id": "s1",
        "current_generation_id": "gEmpty",
    })
    _stream_events(resp)
    take = _content().split("<current_take>")[1]
    assert "whisper_text:\n" in take
    assert "sung" not in take.split("whisper_text:")[1].split("is_picked")[0]
    assert "written" not in take
    assert "scores:" not in take


def test_explicit_unknown_or_foreign_generation_is_404(client, stranger_client):
    resp = _turn(client[0], {
        "message": "x",
        "current_song_id": "s1",
        "current_generation_id": "missing",
    })
    assert resp.status_code == 404
    assert _capture.called is False

    resp = _turn(stranger_client, {
        "message": "x",
        "current_song_id": "s1",
        "current_generation_id": "gA",
    })
    assert resp.status_code == 404
    assert _capture.called is False


def test_wrong_song_or_unplayable_is_422(client):
    c, _ = client
    resp = _turn(c, {
        "message": "x",
        "current_song_id": "s1",
        "current_generation_id": "g2",
    })
    assert resp.status_code == 422
    assert _capture.called is False

    resp = _turn(c, {
        "message": "x",
        "current_song_id": "s1",
        "current_generation_id": "gArch",
    })
    assert resp.status_code == 422
    assert _capture.called is False


def test_chat_turn_does_not_enqueue_scoring(client):
    c, factory = client
    with patch("songmaker_cli.generation_api.api_score_generation") as score_ep, patch(
        "songmaker_cli.scoring.pipeline.run_pipeline", create=True,
    ) as pipeline:
        resp = _turn(c, {
            "message": "x",
            "current_song_id": "s1",
            "current_generation_id": "gB",
        })
    assert resp.status_code == 200
    _stream_events(resp)
    score_ep.assert_not_called()
    pipeline.assert_not_called()
    with factory() as session:
        assert session.query(Job).filter_by(type=JobType.SCORE).count() == 0
