"""Tests for the songmaker server."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from songmaker_cli.db.engine import init_db, reset_engine
from songmaker_cli.db.models import Album, Score, Song, SongRevision, Version
from songmaker_cli.server import create_app


@pytest.fixture()
def server_app(tmp_path: Path) -> TestClient:
    """Create a test server with DB and a minimal project layout."""
    reset_engine()
    output_dir = tmp_path / "_output"
    album_dir = output_dir / "test_album"
    album_dir.mkdir(parents=True)

    project_root = tmp_path
    (project_root / "pyproject.toml").write_text("[project]\nname = 'test'\n")
    albums_dir = project_root / "albums" / "test_album"
    lyrics_dir = albums_dir / "lyrics"
    lyrics_dir.mkdir(parents=True)
    (albums_dir / "album.yaml").write_text("title: Test\nartist: Test\n")

    mp3 = album_dir / "01_song_v1.mp3"
    mp3.write_bytes(b"\xff\xfb\x90\x00" * 100)

    # SvelteKit build placeholder
    sk_dir = project_root / "player" / "build"
    sk_dir.mkdir(parents=True)
    (sk_dir / "index.html").write_text("<html>SvelteKit Player</html>")

    # Init DB with test data
    factory = init_db(output_dir / "songmaker.db")
    with factory() as session:
        album = Album(id="test_album", title="Test", artist="Test")
        session.add(album)
        song = Song(id="s1", title="Song", album_id="test_album", track_number=1)
        session.add(song)
        rev = SongRevision(id="r1", song_id="s1", lyrics="Hello")
        session.add(rev)
        version = Version(
            id="v1", song_id="s1", revision_id="r1", version_number=1,
            mp3_path="test_album/01_song_v1.mp3", seed=42,
        )
        session.add(version)
        score = Score(id="sc1", version_id="v1", scorer="batch", value={"dynamics": 48.9})
        session.add(score)
        session.commit()

    app = create_app(output_dir, project_root)
    yield TestClient(app)
    reset_engine()


def test_get_player(server_app: TestClient) -> None:
    resp = server_app.get("/")
    assert resp.status_code == 200
    assert "SvelteKit" in resp.text


def test_get_audio(server_app: TestClient) -> None:
    resp = server_app.get("/audio/test_album/01_song_v1.mp3")
    assert resp.status_code == 200
    assert len(resp.content) > 0


def test_get_audio_not_found(server_app: TestClient) -> None:
    resp = server_app.get("/audio/test_album/nonexistent.mp3")
    assert resp.status_code == 404


def test_get_audio_path_traversal(server_app: TestClient) -> None:
    resp = server_app.get("/audio/../../../etc/passwd")
    assert resp.status_code in (403, 404, 422)


def test_api_albums(server_app: TestClient) -> None:
    resp = server_app.get("/api/albums")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == "test_album"


def test_api_rate_version(server_app: TestClient) -> None:
    resp = server_app.post(
        "/api/rate/test_album/01_song_v1",
        json={"rating": 72.5, "notes": "great groove"},
    )
    assert resp.status_code == 200
    assert resp.json()["rating"] == 72.5


def test_api_rate_not_found(server_app: TestClient) -> None:
    resp = server_app.post(
        "/api/rate/test_album/nonexistent",
        json={"rating": 3},
    )
    assert resp.status_code == 404
