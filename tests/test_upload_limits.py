"""Body-size path rules and real create_app() upload budgets."""

from __future__ import annotations

from pathlib import Path

from conftest import login_and_csrf, make_test_app
from fastapi.testclient import TestClient

from songmaker_cli.auth import hash_password
from songmaker_cli.constants import (
    AUDIO_UPLOAD_BODY_MAX_BYTES,
    AUDIO_UPLOAD_FILE_MAX_BYTES,
    COVER_UPLOAD_BODY_MAX_BYTES,
    JSON_REQUEST_BODY_MAX_BYTES,
    REFERENCE_AUDIO_MAX_BYTES,
    REIMPORT_BODY_MAX_BYTES,
)
from songmaker_cli.db.models import Album, User
from songmaker_cli.db.queries import create_user_lora
from songmaker_cli.middleware.body_size import (
    body_limit_for_path,
    is_large_upload_path,
)


def test_is_large_upload_path_is_exact() -> None:
    assert is_large_upload_path("/api/audio/upload")
    assert is_large_upload_path("/api/loras/abc-id/samples")
    assert is_large_upload_path("/api/songs/song-id/reimport")
    assert is_large_upload_path("/api/playlists/playlist-id/cover")
    assert not is_large_upload_path("/api/loras/abc-id/samples/extra")
    assert not is_large_upload_path("/api/other/samples")
    assert not is_large_upload_path("/api/loras//samples")
    assert not is_large_upload_path("/api/songs//reimport")
    assert not is_large_upload_path("/api/other/song-id/reimport")
    assert not is_large_upload_path("/api/songs/song-id/reimport/extra")
    assert not is_large_upload_path("/api/playlists//cover")


def test_body_limits_keep_json_small_and_uploads_larger() -> None:
    assert body_limit_for_path("/api/songs") == JSON_REQUEST_BODY_MAX_BYTES
    assert body_limit_for_path("/api/audio/upload") == AUDIO_UPLOAD_BODY_MAX_BYTES
    assert body_limit_for_path("/api/loras/x/samples") == AUDIO_UPLOAD_BODY_MAX_BYTES
    assert body_limit_for_path("/api/songs/x/reimport") == REIMPORT_BODY_MAX_BYTES
    assert body_limit_for_path("/api/playlists/x/cover") == COVER_UPLOAD_BODY_MAX_BYTES
    assert REIMPORT_BODY_MAX_BYTES == 2 * AUDIO_UPLOAD_FILE_MAX_BYTES + 1024 * 1024
    assert AUDIO_UPLOAD_BODY_MAX_BYTES > REFERENCE_AUDIO_MAX_BYTES


def _seed_owner(session) -> None:
    session.add(User(id="owner-id", username="owner", password_hash=hash_password("pass1234")))
    session.flush()
    session.add(Album(id="a1", title="A", artist="A", created_by="owner-id"))


def _authed_app(tmp_path: Path) -> TestClient:
    client, _ = make_test_app(tmp_path, seed_db=_seed_owner)
    login_and_csrf(client, "owner", "pass1234")
    client.headers["Origin"] = "http://127.0.0.1:8080"
    return client


def test_create_app_accepts_2mib_reference_audio(tmp_path: Path) -> None:
    client = _authed_app(tmp_path)
    payload = b"RIFF" + b"\x00" * (2 * 1024 * 1024)
    resp = client.post(
        "/api/audio/upload",
        files={"file": ("ref.wav", payload, "audio/wav")},
    )
    assert resp.status_code == 200, resp.text
    assert "refs/" in resp.json()["path"]


def test_create_app_accepts_2mib_lora_sample(tmp_path: Path) -> None:
    client, factory = make_test_app(tmp_path, seed_db=_seed_owner)
    login_and_csrf(client, "owner", "pass1234")
    client.headers["Origin"] = "http://127.0.0.1:8080"
    with factory() as session:
        lora = create_user_lora(session, "owner-id", "Voice", "v")
        session.commit()
        lora_id = lora.id
    payload = b"RIFF" + b"\x00" * (2 * 1024 * 1024)
    resp = client.post(
        f"/api/loras/{lora_id}/samples",
        data={"caption": "verse", "lyrics": "la"},
        files={"audio": ("clip.wav", payload, "audio/wav")},
    )
    assert resp.status_code == 200, resp.text


def test_json_route_still_rejects_over_1mib(tmp_path: Path) -> None:
    client = _authed_app(tmp_path)
    resp = client.post(
        "/api/songs",
        content=b"x" * (JSON_REQUEST_BODY_MAX_BYTES + 10),
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 413


def test_reimport_suffix_does_not_expand_unrelated_route_budget(tmp_path: Path) -> None:
    client = _authed_app(tmp_path)
    resp = client.post(
        "/api/other/resource/reimport",
        content=b"x" * (JSON_REQUEST_BODY_MAX_BYTES + 1),
        headers={"content-type": "application/octet-stream"},
    )
    assert resp.status_code == 413


def test_reimport_keeps_per_file_limit_separate(
    tmp_path: Path, monkeypatch,
) -> None:
    client = _authed_app(tmp_path)
    song_resp = client.post("/api/songs", json={"title": "Song", "album_id": "a1"})
    assert song_resp.status_code == 200
    monkeypatch.setattr("songmaker_cli.reimport_api.AUDIO_UPLOAD_FILE_MAX_BYTES", 4)
    resp = client.post(
        f"/api/songs/{song_resp.json()['id']}/reimport",
        files={"mp3": ("take.mp3", b"12345", "audio/mpeg")},
    )
    assert resp.status_code == 413
    assert resp.json()["detail"] == "MP3 file too large"


def test_50mib_file_with_multipart_envelope_is_accepted(tmp_path: Path) -> None:
    client = _authed_app(tmp_path)
    payload = b"RIFF" + b"\x00" * (AUDIO_UPLOAD_FILE_MAX_BYTES - 4)
    resp = client.post(
        "/api/audio/upload",
        files={"file": ("ref.wav", payload, "audio/wav")},
    )
    assert resp.status_code == 200, resp.text


def test_file_over_50mib_is_business_rejected(tmp_path: Path) -> None:
    client = _authed_app(tmp_path)
    payload = b"RIFF" + b"\x00" * (AUDIO_UPLOAD_FILE_MAX_BYTES - 3)
    resp = client.post(
        "/api/audio/upload",
        files={"file": ("ref.wav", payload, "audio/wav")},
    )
    assert resp.status_code == 400
    assert "too large" in resp.json()["detail"].lower()
