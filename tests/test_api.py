"""Integration tests for the REST API endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from songmaker_cli.db.engine import init_db, reset_engine
from songmaker_cli.db.models import Album, Rating, Score, Song, SongRevision, Version


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """Create a test client with a seeded database."""
    reset_engine()
    factory = init_db(tmp_path / "test.db")

    with factory() as session:
        _seed_db(session)

    from songmaker_cli.api import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    reset_engine()


def _seed_db(session) -> None:
    album = Album(id="rock", title="Rock Album", artist="TestBand", subtitle="loud")
    session.add(album)

    song = Song(id="s1", title="Thunder", album_id="rock", track_number=1)
    session.add(song)

    rev = SongRevision(id="r1", song_id="s1", lyrics="boom", prompt="hard rock")
    session.add(rev)

    v1 = Version(
        id="v1", song_id="s1", revision_id="r1", version_number=1,
        mp3_path="rock/01_thunder_v1.mp3", seed=42,
        generation_params={"bpm": 140, "key": "E"},
    )
    v2 = Version(
        id="v2", song_id="s1", revision_id="r1", version_number=2,
        mp3_path="rock/01_thunder_v2.mp3", seed=77,
    )
    session.add_all([v1, v2])

    score = Score(id="sc1", version_id="v1", scorer="batch", value={"dynamics": 65.0})
    session.add(score)

    session.commit()


# ── Album endpoints ──────────────────────────────────────────────────


def test_list_albums(client: TestClient) -> None:
    resp = client.get("/api/albums")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "rock"
    assert data[0]["song_count"] == 1


def test_get_album(client: TestClient) -> None:
    resp = client.get("/api/albums/rock")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Rock Album"


def test_get_album_not_found(client: TestClient) -> None:
    resp = client.get("/api/albums/nonexistent")
    assert resp.status_code == 404


# ── Library endpoint ─────────────────────────────────────────────────


def test_library(client: TestClient) -> None:
    resp = client.get("/api/library")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


def test_library_filtered(client: TestClient) -> None:
    resp = client.get("/api/library?album_id=rock")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


def test_library_pagination(client: TestClient) -> None:
    resp = client.get("/api/library?limit=1&offset=0")
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["total"] == 2


# ── Version endpoints ────────────────────────────────────────────────


def test_get_version(client: TestClient) -> None:
    resp = client.get("/api/versions/v1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["seed"] == 42
    assert data["scores"]["dynamics"] == 65.0


def test_get_version_not_found(client: TestClient) -> None:
    resp = client.get("/api/versions/nonexistent")
    assert resp.status_code == 404


def test_song_versions(client: TestClient) -> None:
    resp = client.get("/api/songs/s1/versions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["version_number"] == 2  # desc order


# ── Rating endpoints ─────────────────────────────────────────────────


def test_rate_version_by_id(client: TestClient) -> None:
    resp = client.post("/api/versions/v1/rate", json={"rating": 85.0, "notes": "awesome"})
    assert resp.status_code == 200
    assert resp.json()["rating"] == 85.0

    # Verify it persists
    resp = client.get("/api/versions/v1")
    assert resp.json()["scores"]["user_rating"] == 85.0


def test_rate_version_by_path(client: TestClient) -> None:
    resp = client.post("/api/rate/rock/01_thunder_v2", json={"rating": 72.0})
    assert resp.status_code == 200

    resp = client.get("/api/versions/v2")
    assert resp.json()["scores"]["user_rating"] == 72.0


def test_rate_version_not_found(client: TestClient) -> None:
    resp = client.post("/api/versions/nonexistent/rate", json={"rating": 50.0})
    assert resp.status_code == 404


def test_rate_version_invalid_rating(client: TestClient) -> None:
    resp = client.post("/api/versions/v1/rate", json={"rating": 150.0})
    assert resp.status_code == 422  # validation error


def test_rate_version_update(client: TestClient) -> None:
    client.post("/api/versions/v1/rate", json={"rating": 60.0})
    client.post("/api/versions/v1/rate", json={"rating": 90.0, "notes": "changed my mind"})

    resp = client.get("/api/versions/v1")
    assert resp.json()["scores"]["user_rating"] == 90.0
    assert resp.json()["scores"]["user_notes"] == "changed my mind"
