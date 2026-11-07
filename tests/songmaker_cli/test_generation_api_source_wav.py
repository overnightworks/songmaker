"""Repaint and cover of an mp3-only take record its wav only together with the job."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from support.generation_job_world import worker_up
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.constants import JobType
from songmaker_cli.db.models import Album, AvailableModel, Generation, Song, User, Version
from songmaker_cli.db.queries.jobs import create_job
from songmaker_cli.settings import get_settings

OWNER_ID = "owner"
TAKE_ID = "take"
CONVERTED_WAV = "owner/take.wav"
REPAINT = ("repaint", {
    "src_generation_id": TAKE_ID, "repainting_start": 0.0, "repainting_end": 0.5, "model": "sft",
})
COVER = ("cover", {"src_generation_id": TAKE_ID, "model": "sft"})


def _seed_mp3_only_take(session: Session) -> None:
    session.add(User(id=OWNER_ID, username="owner", role="user"))
    session.flush()
    session.add(Album(id="album", title="Album", artist="X", created_by=OWNER_ID))
    session.add(Song(id="song", title="Song", album_id="album", track_number=1, slug="song"))
    session.add(Version(id="version", song_id="song", version_number=1, lyrics="l", prompt="p"))
    session.add(Generation(
        id=TAKE_ID, song_id="song", version_id="version", generation_number=1,
        mp3_path="owner/take.mp3",
    ))
    session.query(AvailableModel).filter(AvailableModel.id == "sft").update({"is_active": True})
    session.commit()


@pytest.fixture
def client(tmp_path: Path, pg_factory) -> TestClient:
    with pg_factory() as session:
        _seed_mp3_only_take(session)
    audio = tmp_path / "audio" / "owner"
    audio.mkdir(parents=True)
    (audio / "take.mp3").write_bytes(b"mp3")
    (audio / "take.wav").write_bytes(b"RIFF" + b"\x00" * 40)
    app = make_router_app(
        make_router_ctx(tmp_path, db=pg_factory),
        user=make_authenticated_user(OWNER_ID, username="owner"),
    )
    return web_client(app)


def _stored_wav_path(client: TestClient) -> str | None:
    with client.app.state.ctx.db() as session:
        return session.get(Generation, TAKE_ID).wav_path


def _fill_the_active_job_limit(client: TestClient) -> None:
    with client.app.state.ctx.db() as session:
        for _ in range(get_settings().max_user_active_jobs):
            create_job(session, JobType.GENERATE, user_id=OWNER_ID)
        session.commit()


@pytest.mark.parametrize(("route", "body"), [REPAINT, COVER], ids=["repaint", "cover"])
def test_the_request_creates_the_job_and_records_the_converted_wav(
    client: TestClient, route: str, body: dict,
) -> None:
    with worker_up():
        response = client.post(f"/api/generations/{TAKE_ID}/{route}", json=body)

    assert response.status_code == 200
    assert _stored_wav_path(client) == CONVERTED_WAV


@pytest.mark.parametrize(("route", "body"), [REPAINT, COVER], ids=["repaint", "cover"])
def test_a_refused_rate_limit_leaves_the_wav_unrecorded(
    client: TestClient, route: str, body: dict,
) -> None:
    _fill_the_active_job_limit(client)

    with worker_up():
        response = client.post(f"/api/generations/{TAKE_ID}/{route}", json=body)

    assert response.status_code == 429
    assert _stored_wav_path(client) is None
