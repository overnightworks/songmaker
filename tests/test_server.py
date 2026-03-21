"""Tests for the songmaker server."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from songmaker_cli.server import create_app


@pytest.fixture()
def server_app(tmp_path: Path) -> TestClient:
    """Create a test server with a minimal project layout."""
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

    snapshot = album_dir / "01_song_v1.md"
    snapshot.write_text(
        "---\ntitle: Test\n---\n\n## Lyrics\n\nHello\n\n"
        "## Generation\n\n- seed: 42\n\n"
        "## Scores\n\n- dynamics: 48.9\n- silence_ok: True\n"
    )

    manifest = {"albums": [{"id": "test_album", "title": "Test", "tracks": []}]}
    (output_dir / "manifest.json").write_text(json.dumps(manifest))
    (output_dir / "player.html").write_text("<html>player</html>")

    app = create_app(output_dir, project_root)
    return TestClient(app)


def test_get_manifest(server_app: TestClient) -> None:
    resp = server_app.get("/manifest.json")
    assert resp.status_code == 200
    assert "albums" in resp.json()


def test_get_player(server_app: TestClient) -> None:
    resp = server_app.get("/")
    assert resp.status_code == 200
    assert "player" in resp.text


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


def test_rate_version(server_app: TestClient) -> None:
    resp = server_app.post(
        "/rate/test_album/01_song_v1",
        json={"rating": 4, "notes": "great song"},
    )
    assert resp.status_code == 200
    assert resp.json()["rating"] == 4


def test_rate_version_not_found(server_app: TestClient) -> None:
    resp = server_app.post(
        "/rate/test_album/nonexistent",
        json={"rating": 3},
    )
    assert resp.status_code == 404
