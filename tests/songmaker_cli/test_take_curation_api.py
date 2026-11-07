"""A take's Pick and Keep change independently, and a song is created only inside an album."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.web_app import make_test_app, seed_session, seed_user

from songmaker_cli.db.models import Album, Generation, Song, Version

OWNER = "owner"


def _seed_album_with_two_takes(session) -> None:
    owner = seed_user(session, OWNER)
    session.add(Album(id="a1", title="Album", artist="X", created_by=owner.id))
    session.flush()
    session.add(Song(id="s1", slug="s1", title="Song", album_id="a1", track_number=1))
    session.flush()
    session.add(Version(id="v1", song_id="s1", version_number=1, lyrics="l", prompt="p"))
    session.flush()
    session.add_all(
        Generation(
            id=f"g{number}", song_id="s1", version_id="v1", generation_number=number,
            mp3_path=f"{OWNER}/g{number}.mp3",
        )
        for number in (1, 2)
    )


@pytest.fixture
def client(tmp_path: Path, pg_factory) -> TestClient:
    web, _ = make_test_app(tmp_path, factory=pg_factory, seed_db=_seed_album_with_two_takes)
    seed_session(web, OWNER)
    return web


def test_changing_the_pick_leaves_every_keep_as_it_was(client: TestClient) -> None:
    """Spec: REQ-CURATION-03 -- Picking another take or unpicking keeps each take's Keep as it was,
    for a take that is both and for a take that is only kept."""
    client.post("/api/generations/g1/keep")
    client.post("/api/generations/g1/pick")
    client.post("/api/generations/g2/keep")
    client.post("/api/generations/g2/unkeep")

    client.post("/api/generations/g2/pick")
    after_repick = [client.get(f"/api/generations/{g}").json()["is_kept"] for g in ("g1", "g2")]
    client.post("/api/generations/g2/unpick")
    after_unpick = [client.get(f"/api/generations/{g}").json()["is_kept"] for g in ("g1", "g2")]

    assert after_repick == [True, False]
    assert after_unpick == [True, False]


def test_changing_a_keep_leaves_the_songs_pick_as_it_was(client: TestClient) -> None:
    """Spec: REQ-CURATION-05 -- Keeping or unkeeping any take of the song, the picked one included,
    leaves the song's Pick on the same take."""
    client.post("/api/generations/g1/pick")

    def pick_flags() -> list[bool]:
        return [client.get(f"/api/generations/{g}").json()["is_picked"] for g in ("g1", "g2")]

    client.post("/api/generations/g2/keep")
    after_keeping_another = pick_flags()
    client.post("/api/generations/g1/keep")
    client.post("/api/generations/g1/unkeep")
    after_changing_the_picked = pick_flags()

    assert after_keeping_another == [True, False]
    assert after_changing_the_picked == [True, False]


@pytest.mark.parametrize("body", [
    pytest.param({"title": "Orphan"}, id="without-album"),
    pytest.param({"title": "Orphan", "album_id": "no-such-album"}, id="unknown-album"),
])
def test_a_song_is_refused_without_an_existing_album(client: TestClient, body: dict) -> None:
    """Spec: REQ-CATALOG-01 -- A song cannot be created outside an album."""
    songs_before = client.get("/api/songs").json()

    resp = client.post("/api/songs", json=body)

    assert resp.status_code in (404, 422)
    assert client.get("/api/songs").json() == songs_before
