"""v2 co-writer @-mention resolution (#36)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from support.cowriter_gateway import CowriterStack, attach_cowriter_gateway
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.api_models import ChatTurnV2Request
from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.models import Album, AvailableModel, Song, User, Version


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
    session.add(User(id="u-other", username="other", role="user"))
    session.flush()
    session.add(Album(id="alb-foreign", title="Elsewhere", artist="C", created_by="u-other"))
    session.add(Song(id="s-foreign", title="Offshore", album_id="alb-foreign", track_number=1))
    session.query(AvailableModel).filter(
        AvailableModel.id.in_(["turbo", "sft"]),
    ).update({"is_active": True}, synchronize_session=False)
    session.commit()


@dataclass
class Musician:
    """A signed-in musician whose turns reach the fake gateway."""

    client: TestClient
    stack: CowriterStack

    def turn(self, payload: dict):
        return self.client.post("/api/chat/turn", json=payload)

    @property
    def run_started(self) -> bool:
        return bool(self.stack.turns)

    @property
    def content(self) -> str:
        return self.stack.last_turn.messages[-1]["text"]


@pytest.fixture
def client(tmp_path: Path, pg_factory) -> Musician:
    with pg_factory() as session:
        _seed(session, "u-test")
    app = make_router_app(
        make_router_ctx(tmp_path, db=pg_factory),
        user=make_authenticated_user("u-test", username="u-u-test"),
    )
    web = web_client(app)
    return Musician(web, attach_cowriter_gateway(web, pg_factory, tmp_path, "u-test"))


@pytest.fixture
def stranger_client(tmp_path: Path) -> Musician:
    factory = init_db(tmp_path / "mentions_spy.db")
    with factory() as session:
        _seed(session, "u-owner")
        session.add(User(id="u-spy", username="spy", role="user"))
        session.commit()
    app = make_router_app(
        make_router_ctx(tmp_path, db=factory),
        user=make_authenticated_user("u-spy", username="u-u-spy"),
    )
    web = web_client(app)
    return Musician(web, attach_cowriter_gateway(web, factory, tmp_path, "u-spy"))


def test_mentioned_song_snapshot_is_server_loaded(client):
    """Spec: REQ-COWRITER-19 -- a mentioned song's lyrics come from the stored song, named only
    by its id in the request."""
    resp = client.turn({
        "message": "compare",
        "current_song_id": "s1",
        "mentioned_song_ids": ["s2"],
    })
    assert resp.status_code == 200
    _stream_events(resp)
    content = client.content
    assert "<mentioned_songs>" in content
    assert content.count("title: Rain") == 1
    assert "rain lyrics" in content
    assert "title: Thunder" in content
    assert "lyrics:\nrain lyrics" in content


def test_album_mention_loads_tracks_from_album_id_only(client):
    """Spec: REQ-COWRITER-22 -- an album mention carries the tracks of the musician's album."""
    resp = client.turn({
        "message": "album vibe",
        "current_song_id": "s1",
        "mentioned_album_id": "alb1",
    })
    assert resp.status_code == 200
    _stream_events(resp)
    content = client.content
    assert "<mentioned_album>" in content
    assert "title: Rock" in content
    assert "title: Thunder" in content
    assert "title: Rain" in content
    assert "Offshore" not in content


def test_version_mention_uses_the_selected_version(client):
    """Spec: REQ-COWRITER-23 -- a version mention carries the chosen version, not the latest."""
    resp = client.turn({
        "message": "old take on lyrics",
        "current_song_id": "s1",
        "mentioned_version_ids": ["v1"],
    })
    assert resp.status_code == 200
    _stream_events(resp)
    content = client.content
    assert "<mentioned_versions>" in content
    assert "version_number: 1" in content
    assert "thunder lyrics" in content
    assert "thunder v2 lyrics" not in content.split("<mentioned_versions>")[1]


def test_a_foreign_album_mention_is_404_and_its_tracks_stay_out(client):
    """Spec: REQ-COWRITER-22 -- an album the musician cannot access is refused, not expanded."""
    resp = client.turn({
        "message": "x",
        "current_song_id": "s1",
        "mentioned_album_id": "alb-foreign",
    })
    assert resp.status_code == 404
    assert not client.run_started


def test_at_text_without_a_confirmed_id_stays_message_text(client):
    """Spec: REQ-COWRITER-21 -- @-text with no picked identifier becomes no mention context and
    stays in the message."""
    resp = client.turn({"message": "make it like @Rain", "current_song_id": "s1"})
    assert resp.status_code == 200
    _stream_events(resp)
    content = client.content
    assert "make it like @Rain" in content
    assert "<mentioned_songs>" not in content
    assert "rain lyrics" not in content


def test_duplicate_song_ids_emit_one_block(client):
    resp = client.turn({
        "message": "dup",
        "current_song_id": "s1",
        "mentioned_song_ids": ["s2", "s2"],
    })
    assert resp.status_code == 200
    _stream_events(resp)
    content = client.content
    assert content.count("<mentioned_songs>") == 1
    assert content.count("title: Rain") == 1


def test_unknown_or_foreign_mention_is_404_before_provider(client, stranger_client):
    """Spec: REQ-COWRITER-20 -- an unknown, foreign or unrelated mention id refuses the turn
    before any run starts."""
    resp = client.turn({
        "message": "x",
        "current_song_id": "s1",
        "mentioned_song_ids": ["missing"],
    })
    assert resp.status_code == 404
    assert not client.run_started
    assert not stranger_client.run_started

    resp = client.turn({
        "message": "x",
        "current_song_id": "s1",
        "mentioned_version_ids": ["v2"],
    })
    assert resp.status_code == 404
    assert not client.run_started
    assert not stranger_client.run_started

    resp = client.turn({
        "message": "x",
        "current_song_id": "s1",
        "mentioned_album_id": "other",
    })
    assert resp.status_code == 404
    assert not client.run_started
    assert not stranger_client.run_started

    resp = stranger_client.turn({
        "message": "x",
        "current_song_id": "s1",
        "mentioned_song_ids": ["s2"],
    })
    assert resp.status_code == 404
    assert not client.run_started
    assert not stranger_client.run_started


def test_schema_accepts_current_generation_id_field(client):
    resp = client.turn({
        "message": "look at this take",
        "current_song_id": "s1",
        "current_generation_id": None,
    })
    assert resp.status_code == 200
    _stream_events(resp)
    assert client.run_started


def test_schema_caps_mention_lists_before_database_resolution():
    with pytest.raises(ValidationError):
        ChatTurnV2Request(
            message="too many",
            mentioned_song_ids=[f"song-{index}" for index in range(51)],
        )
