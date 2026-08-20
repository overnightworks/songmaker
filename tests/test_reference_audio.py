"""Owner-root resolution for reference audio."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import login_and_csrf, make_test_app

from songmaker_cli.auth import hash_password
from songmaker_cli.constants import REFERENCE_AUDIO_DIR
from songmaker_cli.db.models import Album, Song, User
from songmaker_cli.reference_audio import (
    ReferenceAudioRejected,
    resolve_owned_reference_audio,
)


def _write_ref(root: Path, user_id: str, name: str, data: bytes = b"RIFF") -> Path:
    dest = root / user_id / REFERENCE_AUDIO_DIR / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def test_resolves_owned_regular_file(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    _write_ref(audio_dir, "user-a", "clip.wav")
    resolved = resolve_owned_reference_audio(
        audio_dir, "user-a", f"user-a/{REFERENCE_AUDIO_DIR}/clip.wav",
    )
    assert resolved.is_file()
    assert resolved.name == "clip.wav"


def test_rejects_cross_user_path(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    _write_ref(audio_dir, "user-b", "clip.wav")
    with pytest.raises(ReferenceAudioRejected):
        resolve_owned_reference_audio(
            audio_dir, "user-a", f"user-b/{REFERENCE_AUDIO_DIR}/clip.wav",
        )


def test_rejects_user_id_sibling_prefix(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    _write_ref(audio_dir, "user-a-other", "clip.wav")
    with pytest.raises(ReferenceAudioRejected):
        resolve_owned_reference_audio(
            audio_dir, "user-a", f"user-a-other/{REFERENCE_AUDIO_DIR}/clip.wav",
        )


def test_rejects_traversal(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    _write_ref(audio_dir, "user-a", "clip.wav")
    with pytest.raises(ReferenceAudioRejected):
        resolve_owned_reference_audio(
            audio_dir, "user-a", f"user-a/{REFERENCE_AUDIO_DIR}/../clip.wav",
        )


def test_rejects_absolute_path(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    dest = _write_ref(audio_dir, "user-a", "clip.wav")
    with pytest.raises(ReferenceAudioRejected):
        resolve_owned_reference_audio(audio_dir, "user-a", str(dest))


def test_rejects_symlink_outside_owner_root(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    foreign = _write_ref(audio_dir, "user-b", "secret.wav", b"SECRET")
    link_dir = audio_dir / "user-a" / REFERENCE_AUDIO_DIR
    link_dir.mkdir(parents=True, exist_ok=True)
    link = link_dir / "alias.wav"
    link.symlink_to(foreign)
    with pytest.raises(ReferenceAudioRejected):
        resolve_owned_reference_audio(
            audio_dir, "user-a", f"user-a/{REFERENCE_AUDIO_DIR}/alias.wav",
        )


def _seed_users(session) -> None:
    session.add_all([
        User(
            id="user-a", username="owner", password_hash=hash_password("pass1234"),
        ),
        User(
            id="user-b", username="other", password_hash=hash_password("pass1234"),
        ),
    ])
    session.flush()
    session.add(Album(id="album-a", title="A", artist="A", created_by="user-a"))


def test_song_write_accepts_owned_reference_and_rejects_foreign(
    tmp_path: Path,
) -> None:
    client, factory = make_test_app(tmp_path, seed_db=_seed_users)
    login_and_csrf(client, "owner", "pass1234")
    client.headers["Origin"] = "http://127.0.0.1:8080"
    audio_dir = tmp_path / "audio"
    _write_ref(audio_dir, "user-a", "mine.wav")
    _write_ref(audio_dir, "user-b", "secret.wav", b"SECRET")

    own_resp = client.post("/api/songs", json={
        "title": "Own ref",
        "album_id": "album-a",
        "generation_params": {
            "reference_audio_path": f"user-a/{REFERENCE_AUDIO_DIR}/mine.wav",
        },
    })
    assert own_resp.status_code == 200, own_resp.text

    foreign_resp = client.post("/api/songs", json={
        "title": "Foreign ref",
        "album_id": "album-a",
        "generation_params": {
            "reference_audio_path": f"user-b/{REFERENCE_AUDIO_DIR}/secret.wav",
        },
    })
    assert foreign_resp.status_code == 404
    assert foreign_resp.json()["detail"] == "Not Found"
    with factory() as session:
        assert session.query(Song).filter_by(title="Foreign ref").first() is None
