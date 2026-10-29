"""Co-writer take context: whisper, pick, keep, scores (#37)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from support.fake_agent_service import CowriterStack, attach_cowriter_service
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

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

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


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
        id=user_id, username=f"user-{user_id}", role="user",
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
        id="scA", generation_id="gA", scorer="batch",
        value={"text_accuracy": 81.0, "lyrical_coherence": 8, "bpm_detected": 96.0},
    ))
    session.query(AvailableModel).filter(
        AvailableModel.id.in_(["turbo", "sft"]),
    ).update({"is_active": True}, synchronize_session=False)
    session.commit()


@pytest.fixture
def client(tmp_path: Path):
    factory = init_db(tmp_path / "takes.db")
    with factory() as session:
        _seed(session, "u-test")
    app = make_router_app(
        make_router_ctx(tmp_path, db=factory),
        user=make_authenticated_user("u-test", username="u-u-test"),
    )
    return web_client(app), factory


@pytest.fixture
def stranger_client(tmp_path: Path, monkeypatch):
    factory = init_db(tmp_path / "takes_spy.db")
    with factory() as session:
        _seed(session, "u-owner")
        session.add(User(id="u-spy", username="spy", role="user"))
        session.commit()
    app = make_router_app(
        make_router_ctx(tmp_path, db=factory),
        user=make_authenticated_user("u-spy", username="u-u-spy"),
    )
    web = web_client(app)
    return web, attach_cowriter_service(web, factory, monkeypatch, "u-spy")


@pytest.fixture
def service(client, monkeypatch) -> CowriterStack:
    c, factory = client
    return attach_cowriter_service(c, factory, monkeypatch, "u-test")


def _turn(client, payload: dict):
    return client.post("/api/chat/turn", json=payload)


def _content(service: CowriterStack) -> str:
    return service.agent.last_run.messages[-1]["text"]


def test_playing_take_wins_over_pick(client, service):
    c, _ = client
    resp = _turn(c, {
        "message": "how did this take sing",
        "current_song_id": "s1",
        "current_generation_id": "gB",
    })
    assert resp.status_code == 200
    _stream_events(resp)
    body = _content(service)
    assert "<current_take>" in body
    assert "generation_id: gB" in body
    assert "whisper_text:\nsung B" in body
    assert "is_picked: false" in body
    assert "generation_id: gA" not in body.split("<current_take>")[1]


def test_without_player_uses_playable_pick(client, service):
    c, _ = client
    resp = _turn(c, {"message": "x", "current_song_id": "s1"})
    assert resp.status_code == 200
    _stream_events(resp)
    body = _content(service)
    assert "generation_id: gA" in body
    assert "whisper_text:\nsung A" in body
    assert "is_picked: true" in body
    assert "is_kept: true" in body
    assert "scores:\nbpm_detected: 96.0\nlyrical_coherence: 8\ntext_accuracy: 81.0" in body
    assert "batch:" not in body


def test_without_pick_uses_newest_playable(client, service):
    c, factory = client
    with factory() as session:
        session.query(Generation).filter_by(id="gA").update({"is_picked": False})
        session.commit()
    resp = _turn(c, {"message": "x", "current_song_id": "s1"})
    _stream_events(resp)
    assert "generation_id: gEmpty" in _content(service)


def test_no_playable_take_is_named_empty_state(client, service):
    c, factory = client
    with factory() as session:
        session.query(Generation).filter(Generation.song_id == "s1").update({
            "is_archived": True,
        })
        session.commit()
    resp = _turn(c, {"message": "x", "current_song_id": "s1"})
    _stream_events(resp)
    body = _content(service)
    assert "<no_take>" in body
    assert "no playable take" in body
    assert "<current_take>" not in body


def test_missing_whisper_and_scores_stay_empty(client, service):
    c, _ = client
    resp = _turn(c, {
        "message": "x",
        "current_song_id": "s1",
        "current_generation_id": "gEmpty",
    })
    _stream_events(resp)
    take = _content(service).split("<current_take>")[1]
    assert "whisper_text:\n" in take
    assert "sung" not in take.split("whisper_text:")[1].split("is_picked")[0]
    assert "written" not in take
    assert "scores:" not in take


def test_explicit_unknown_or_foreign_generation_is_404(client, service, stranger_client):
    stranger, stranger_service = stranger_client
    resp = _turn(client[0], {
        "message": "x",
        "current_song_id": "s1",
        "current_generation_id": "missing",
    })
    assert resp.status_code == 404
    assert service.agent.runs == []

    resp = _turn(stranger, {
        "message": "x",
        "current_song_id": "s1",
        "current_generation_id": "gA",
    })
    assert resp.status_code == 404
    assert stranger_service.agent.runs == []


def test_wrong_song_or_unplayable_is_422(client, service):
    c, _ = client
    resp = _turn(c, {
        "message": "x",
        "current_song_id": "s1",
        "current_generation_id": "g2",
    })
    assert resp.status_code == 422
    assert service.agent.runs == []

    resp = _turn(c, {
        "message": "x",
        "current_song_id": "s1",
        "current_generation_id": "gArch",
    })
    assert resp.status_code == 422
    assert service.agent.runs == []


def test_chat_turn_does_not_enqueue_scoring(client, service):
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
