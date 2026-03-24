"""Integration tests for the REST API endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from songmaker_cli.db.engine import init_db, reset_engine
from songmaker_cli.db.models import Album, Generation, Score, Song, Version


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    reset_engine()
    factory = init_db(tmp_path / "test.db")
    with factory() as session:
        _seed_db(session)

    from fastapi import FastAPI

    from songmaker_cli.api import router
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    reset_engine()


def _seed_db(session) -> None:
    album = Album(id="rock", title="Rock Album", artist="TestBand")
    session.add(album)
    song = Song(id="s1", title="Thunder", album_id="rock", track_number=1)
    session.add(song)
    ver = Version(id="v1", song_id="s1", version_number=1, lyrics="boom", prompt="hard rock")
    session.add(ver)
    gen1 = Generation(
        id="g1", song_id="s1", version_id="v1", generation_number=1,
        mp3_path="rock/01_thunder_v1.mp3", seed=42,
        generation_params={"bpm": 140},
    )
    gen2 = Generation(
        id="g2", song_id="s1", version_id="v1", generation_number=2,
        mp3_path="rock/01_thunder_v2.mp3", seed=77,
    )
    session.add_all([gen1, gen2])
    score = Score(id="sc1", generation_id="g1", scorer="batch", value={"dynamics": 65.0})
    session.add(score)
    session.commit()


def test_list_albums(client: TestClient) -> None:
    resp = client.get("/api/albums")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_songs(client: TestClient) -> None:
    resp = client.get("/api/songs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["generation_count"] == 2


def test_get_song(client: TestClient) -> None:
    resp = client.get("/api/songs/s1")
    assert resp.status_code == 200
    d = resp.json()
    assert d["title"] == "Thunder"
    assert len(d["generations"]) == 2


def test_create_song(client: TestClient) -> None:
    resp = client.post("/api/songs", json={
        "title": "Lightning", "album_id": "rock", "lyrics": "flash", "bpm": 160,
    })
    assert resp.status_code == 200
    assert resp.json()["title"] == "Lightning"


def test_update_song(client: TestClient) -> None:
    resp = client.put("/api/songs/s1", json={"lyrics": "kaboom"})
    assert resp.status_code == 200
    assert resp.json()["version_count"] == 2


def test_song_versions(client: TestClient) -> None:
    resp = client.get("/api/songs/s1/versions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["lyrics"] == "boom"


def test_get_generation(client: TestClient) -> None:
    resp = client.get("/api/generations/g1")
    assert resp.status_code == 200
    assert resp.json()["seed"] == 42


def test_rate_generation(client: TestClient) -> None:
    resp = client.post("/api/generations/g1/rate", json={"rating": 85.0, "notes": "awesome"})
    assert resp.status_code == 200

    resp = client.get("/api/generations/g1")
    assert resp.json()["scores"]["user_rating"] == 85.0


def test_rate_by_path(client: TestClient) -> None:
    resp = client.post("/api/rate/rock/01_thunder_v2", json={"rating": 72.0})
    assert resp.status_code == 200


def test_rate_not_found(client: TestClient) -> None:
    resp = client.post("/api/generations/nonexistent/rate", json={"rating": 50.0})
    assert resp.status_code == 404


def test_rate_invalid(client: TestClient) -> None:
    resp = client.post("/api/generations/g1/rate", json={"rating": 150.0})
    assert resp.status_code == 422


def test_capabilities(client: TestClient) -> None:
    resp = client.get("/api/capabilities")
    assert resp.status_code == 200
    assert "generation" in resp.json()


# ── Delete endpoints ─────────────────────────────────────────────────


def test_delete_generation_api(client: TestClient) -> None:
    resp = client.delete("/api/generations/g2")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g2")
    assert resp.status_code == 404


def test_delete_generation_not_found(client: TestClient) -> None:
    resp = client.delete("/api/generations/nonexistent")
    assert resp.status_code == 404


def test_delete_version_keep_gens(client: TestClient) -> None:
    resp = client.delete("/api/versions/v1?delete_generations=false")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g1")
    assert resp.status_code == 200
    assert resp.json()["version_id"] is None


def test_delete_version_with_gens(client: TestClient) -> None:
    resp = client.delete("/api/versions/v1?delete_generations=true")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g1")
    assert resp.status_code == 404


# ── Pick endpoints ───────────────────────────────────────────────────


def test_pick_generation_api(client: TestClient) -> None:
    resp = client.post("/api/generations/g1/pick")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g1")
    assert resp.json()["is_picked"] is True


def test_pick_replaces_previous(client: TestClient) -> None:
    client.post("/api/generations/g1/pick")
    client.post("/api/generations/g2/pick")
    resp = client.get("/api/generations/g1")
    assert resp.json()["is_picked"] is False
    resp = client.get("/api/generations/g2")
    assert resp.json()["is_picked"] is True


def test_unpick_generation_api(client: TestClient) -> None:
    client.post("/api/generations/g1/pick")
    resp = client.post("/api/generations/g1/unpick")
    assert resp.status_code == 200
    resp = client.get("/api/generations/g1")
    assert resp.json()["is_picked"] is False


def test_cleanup_album_api(client: TestClient) -> None:
    client.post("/api/generations/g1/pick")
    resp = client.post("/api/albums/rock/cleanup")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1


# ── Job endpoints ────────────────────────────────────────────────────


def test_get_job_not_found(client: TestClient) -> None:
    resp = client.get("/api/jobs/nonexistent")
    assert resp.status_code == 404


# ── Generation params ───────────────────────────────────────────────


def test_create_song_with_generation_params(client: TestClient) -> None:
    resp = client.post("/api/songs", json={
        "title": "Bolt", "album_id": "rock",
        "generation_params": {"inference_steps": 50, "shift": 2.0},
    })
    assert resp.status_code == 200
    assert resp.json()["generation_params"] == {"inference_steps": 50, "shift": 2.0}


def test_create_song_invalid_generation_params(client: TestClient) -> None:
    resp = client.post("/api/songs", json={
        "title": "Bad", "album_id": "rock",
        "generation_params": {"bad_key": 1},
    })
    assert resp.status_code == 422


def test_update_song_sets_generation_params(client: TestClient) -> None:
    resp = client.put("/api/songs/s1", json={
        "generation_params": {"guidance_scale": 5.5},
    })
    assert resp.status_code == 200
    assert resp.json()["generation_params"] == {"guidance_scale": 5.5}


def test_update_song_clears_generation_params(client: TestClient) -> None:
    client.put("/api/songs/s1", json={
        "generation_params": {"inference_steps": 25},
    })
    resp = client.put("/api/songs/s1", json={
        "generation_params": None,
    })
    assert resp.status_code == 200
    assert resp.json()["generation_params"] is None


def test_update_song_omit_keeps_generation_params(client: TestClient) -> None:
    client.put("/api/songs/s1", json={
        "generation_params": {"shift": 4.0},
    })
    resp = client.put("/api/songs/s1", json={"lyrics": "new lyrics"})
    assert resp.status_code == 200
    assert resp.json()["generation_params"] == {"shift": 4.0}


def test_update_song_invalid_generation_params(client: TestClient) -> None:
    resp = client.put("/api/songs/s1", json={
        "generation_params": {"typo_key": 1},
    })
    assert resp.status_code == 422


def test_version_includes_generation_params(client: TestClient) -> None:
    client.put("/api/songs/s1", json={
        "generation_params": {"lm_temperature": 0.5},
    })
    resp = client.get("/api/songs/s1/versions")
    assert resp.status_code == 200
    latest = resp.json()[0]
    assert latest["generation_params"] == {"lm_temperature": 0.5}


# ── Generation defaults ─────────────────────────────────────────────


def test_generation_defaults_roundtrip(client: TestClient, tmp_path: Path) -> None:
    from songmaker_cli import config as config_mod
    original = config_mod._defaults_path

    config_mod._defaults_path = lambda: tmp_path / "gen_defaults.json"
    try:
        resp = client.get("/api/settings/generation-defaults")
        assert resp.status_code == 200
        assert resp.json() == {}

        resp = client.put("/api/settings/generation-defaults", json={
            "turbo": {"inference_steps": 12},
            "sft": {"inference_steps": 60},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["turbo"] == {"inference_steps": 12}
        assert data["sft"] == {"inference_steps": 60}

        resp = client.get("/api/settings/generation-defaults")
        assert resp.json()["turbo"]["inference_steps"] == 12
    finally:
        config_mod._defaults_path = original
