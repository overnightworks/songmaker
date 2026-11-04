"""Shared arrangement of the reference API test modules: accounts, files and links."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.web_app import make_test_app, seed_session, web_client

from songmaker_cli.db.models import (
    Album,
    Generation,
    ReferenceRecording,
    Song,
    User,
    Version,
)
from songmaker_cli.db.queries.reference_recordings import create_reference_recording

REFERENCES_PATH = "/api/references"
WAV_BYTES = b"RIFF" + b"\x00" * 200
AUDIO_BYTES = bytes(range(256)) * 4
SECRET_FILENAME = "private-take-name.wav"
NOT_FOUND = {"detail": "Not Found"}


def _seed_owner_other_and_admin_accounts(session) -> None:
    session.add_all([
        User(id=f"{name}-id", username=name, role=role)
        for name, role in (("owner", "user"), ("other", "user"), ("boss", "admin"))
    ])


@pytest.fixture
def signed_in(tmp_path: Path) -> TestClient:
    client, _ = make_test_app(tmp_path, seed_db=_seed_owner_other_and_admin_accounts)
    seed_session(client, "owner")
    return client


def reference_rows(client: TestClient) -> list[ReferenceRecording]:
    with client.app.state.ctx.db() as session:
        return session.query(ReferenceRecording).all()


def reference_files(client: TestClient) -> list[Path]:
    return [path for path in client.app.state.ctx.audio_dir.rglob("*") if path.is_file()]


def post_reference(
    client: TestClient, payload: bytes = WAV_BYTES, name: str = "ref.wav", **kwargs,
):
    return client.post(REFERENCES_PATH, files={"file": (name, payload, "audio/wav")}, **kwargs)


def seed_reference(
    client: TestClient, user_id: str, name: str, *, created_at: datetime | None = None,
    reference_id: str | None = None, duration_sec: float | None = 12.5,
) -> str:
    with client.app.state.ctx.db() as session:
        row = create_reference_recording(
            session, user_id=user_id, storage_path=f"{user_id}/refs/{name}",
            original_filename=name, size_bytes=1, duration_sec=duration_sec,
        )
        if created_at is not None:
            row.created_at = created_at
        if reference_id is not None:
            row.id = reference_id
        session.commit()
        return row.id


def signed_in_as(signed_in: TestClient, username: str) -> TestClient:
    client = web_client(signed_in.app, raise_server_exceptions=False)
    seed_session(client, username)
    return client


def seed_playable(
    client: TestClient, user_id: str = "owner-id", name: str = SECRET_FILENAME,
) -> str:
    reference_id = seed_reference(client, user_id, name)
    refs = client.app.state.ctx.audio_dir / user_id / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / name).write_bytes(AUDIO_BYTES)
    return reference_id


def link_reference(
    client: TestClient, reference_id: str, *, via: str, archived: bool = False,
    song_trashed: bool = False, album_trashed: bool = False,
) -> None:
    """Link the reference from a saved version (``via="version"``) or from a take."""
    trashed_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    with client.app.state.ctx.db() as session:
        album = Album(
            id="album-link", title="A", artist="A", created_by="owner-id",
            deleted_at=trashed_at if album_trashed else None,
        )
        song = Song(
            id="song-link", title="S", album_id="album-link", track_number=1,
            deleted_at=trashed_at if song_trashed else None,
        )
        version = Version(
            id="version-link", song_id="song-link", version_number=1, lyrics="la", prompt="p",
            reference_recording_id=reference_id if via == "version" else None,
        )
        session.add(album)
        session.flush()
        session.add_all([song, version])
        session.flush()
        if via == "take":
            session.add(Generation(
                song_id="song-link", version_id="version-link", mp3_path="owner-id/take.mp3",
                is_archived=archived, reference_recording_id=reference_id,
            ))
        session.commit()


LINKS = [
    pytest.param({"via": "version"}, id="saved-version"),
    pytest.param({"via": "take"}, id="take"),
    pytest.param({"via": "take", "archived": True}, id="archived-take"),
    pytest.param({"via": "version", "song_trashed": True}, id="version-of-trashed-song"),
    pytest.param({"via": "take", "song_trashed": True}, id="take-of-trashed-song"),
    pytest.param({"via": "version", "album_trashed": True}, id="version-of-trashed-album"),
    pytest.param({"via": "take", "album_trashed": True}, id="take-of-trashed-album"),
]
