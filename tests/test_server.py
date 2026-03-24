"""Tests for the songmaker server."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from songmaker_cli.db.engine import init_db, reset_engine
from songmaker_cli.db.models import Album, Generation, Score, Song, Version
from songmaker_cli.server import create_app


@pytest.fixture()
def server_app(tmp_path: Path) -> TestClient:
    reset_engine()
    output_dir = tmp_path / "_output"
    album_dir = output_dir / "test_album"
    album_dir.mkdir(parents=True)

    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    sk_dir = project_root / "frontend" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>Songmaker</html>")

    mp3 = album_dir / "01_song_v1.mp3"
    mp3.write_bytes(b"\xff\xfb\x90\x00" * 100)

    factory = init_db(output_dir / "songmaker.db")
    with factory() as session:
        album = Album(id="test_album", title="Test", artist="Test")
        session.add(album)
        song = Song(id="s1", title="Song", album_id="test_album", track_number=1)
        session.add(song)
        ver = Version(id="v1", song_id="s1", version_number=1, lyrics="Hello")
        session.add(ver)
        gen = Generation(
            id="g1", song_id="s1", version_id="v1", generation_number=1,
            mp3_path="test_album/01_song_v1.mp3", seed=42,
        )
        session.add(gen)
        score = Score(id="sc1", generation_id="g1", scorer="batch", value={"dynamics": 48.9})
        session.add(score)
        session.commit()

    app = create_app(output_dir, project_root)
    yield TestClient(app)
    reset_engine()


def test_get_player(server_app: TestClient) -> None:
    resp = server_app.get("/")
    assert resp.status_code == 200
    assert "Songmaker" in resp.text


def test_get_audio(server_app: TestClient) -> None:
    resp = server_app.get("/audio/test_album/01_song_v1.mp3")
    assert resp.status_code == 200


def test_get_audio_not_found(server_app: TestClient) -> None:
    resp = server_app.get("/audio/test_album/nonexistent.mp3")
    assert resp.status_code == 404


def test_api_songs(server_app: TestClient) -> None:
    resp = server_app.get("/api/songs")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_api_rate(server_app: TestClient) -> None:
    resp = server_app.post(
        "/api/rate/test_album/01_song_v1",
        json={"rating": 72.5, "notes": "great groove"},
    )
    assert resp.status_code == 200


def test_api_rate_not_found(server_app: TestClient) -> None:
    resp = server_app.post(
        "/api/rate/test_album/nonexistent",
        json={"rating": 3},
    )
    assert resp.status_code == 404
