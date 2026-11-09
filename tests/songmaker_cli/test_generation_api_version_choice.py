"""Repaint, cover and generate act on the version the request names."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from support.generation_job_world import worker_up
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.db.models import Album, AvailableModel, Generation, Job, Song, User, Version

OWNER_ID = "owner"
LINKED_TAKE_ID = "linked-take"
DETACHED_TAKE_ID = "detached-take"
OTHER_VERSION_ID = "other-version"
UNKNOWN_VERSION_ID = "no-such-version"
REPAINT = ("generations/{take}/repaint", {
    "src_generation_id": "{take}", "repainting_start": 0.0, "repainting_end": 0.5, "model": "sft",
})
COVER = ("generations/{take}/cover", {"src_generation_id": "{take}", "model": "sft"})
GENERATE = ("songs/song/generate", {"model": "sft"})


def _seed_two_versions_two_takes(session: Session) -> None:
    session.add(User(id=OWNER_ID, username="owner", role="user"))
    session.flush()
    session.add(Album(id="album", title="Album", artist="X", created_by=OWNER_ID))
    session.add(Song(id="song", title="Song", album_id="album", track_number=1, slug="song"))
    session.add(Version(id="version", song_id="song", version_number=1, lyrics="l", prompt="p"))
    session.add(Version(
        id=OTHER_VERSION_ID, song_id="song", version_number=2, lyrics="l", prompt="p",
    ))
    takes = ((LINKED_TAKE_ID, "version"), (DETACHED_TAKE_ID, None))
    for number, (take_id, version_id) in enumerate(takes, start=1):
        session.add(Generation(
            id=take_id, song_id="song", version_id=version_id, generation_number=number,
            mp3_path=f"owner/{take_id}.mp3", wav_path=f"owner/{take_id}.wav",
        ))
    session.query(AvailableModel).filter(AvailableModel.id == "sft").update({"is_active": True})
    session.commit()


@pytest.fixture
def client(tmp_path: Path, pg_factory) -> TestClient:
    audio = tmp_path / "audio" / "owner"
    audio.mkdir(parents=True)
    for take_id in (LINKED_TAKE_ID, DETACHED_TAKE_ID):
        (audio / f"{take_id}.wav").write_bytes(b"RIFF" + b"\x00" * 40)
    ctx = make_router_ctx(tmp_path, db=pg_factory, seed_db=_seed_two_versions_two_takes)
    app = make_router_app(ctx, user=make_authenticated_user(OWNER_ID, username="owner"))
    return web_client(app)


def _post_for_take(client: TestClient, route_and_body: tuple[str, dict], take: str, **extra):
    route, body = route_and_body
    path = route.format(take=take)
    payload = {key: value.format(take=take) if isinstance(value, str) else value
               for key, value in body.items()} | extra
    with worker_up():
        return client.post(f"/api/{path}", json=payload)


@pytest.mark.parametrize("route", [REPAINT, COVER], ids=["repaint", "cover"])
def test_a_take_job_is_created_against_the_version_the_request_names(
    client: TestClient, route: tuple[str, dict],
) -> None:
    response = _post_for_take(client, route, LINKED_TAKE_ID, version_id=OTHER_VERSION_ID)

    assert response.status_code == 200
    with client.app.state.ctx.db() as session:
        assert session.get(Job, response.json()["id"]).version_id == OTHER_VERSION_ID


@pytest.mark.parametrize("route", [REPAINT, COVER, GENERATE], ids=["repaint", "cover", "generate"])
def test_a_version_the_song_does_not_have_is_refused_as_missing(
    client: TestClient, route: tuple[str, dict],
) -> None:
    response = _post_for_take(client, route, LINKED_TAKE_ID, version_id=UNKNOWN_VERSION_ID)

    assert response.status_code == 404
    assert response.json()["detail"] == "Version not found"


def test_a_repaint_of_a_take_without_a_version_is_refused_as_invalid(
    client: TestClient,
) -> None:
    response = _post_for_take(client, REPAINT, DETACHED_TAKE_ID)

    assert response.status_code == 400
    assert response.json()["detail"] == "Generation has no linked version"
