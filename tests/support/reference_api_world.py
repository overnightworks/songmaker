"""Shared arrangement of the reference API test modules: accounts, files and links."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from support.reference_rows import a_reference
from support.web_app import make_test_app, refusal_body, seed_session, web_client

from songmaker_cli.db.models import (
    Album,
    Generation,
    ReferenceRecording,
    Song,
    User,
    Version,
)
from songmaker_cli.timestamps import utcnow

REFERENCES_PATH = "/api/references"
WAV_BYTES = b"RIFF" + b"\x00" * 200
AUDIO_BYTES = bytes(range(256)) * 4
SECRET_FILENAME = "private-take-name.wav"
NOT_FOUND = {"detail": "Not Found"}
REFERENCE_NOT_FOUND = refusal_body("referenceRefusal.notFound")


def _seed_owner_other_and_admin_accounts(session) -> None:
    session.add_all([
        User(id=f"{name}-id", username=name, role=role)
        for name, role in (("owner", "user"), ("other", "user"), ("boss", "admin"))
    ])


def sign_in_owner(tmp_path: Path, factory: sessionmaker) -> TestClient:
    """An app on ``factory`` with the owner, another member and an admin; the owner is signed in."""
    client, _ = make_test_app(
        tmp_path, factory=factory, seed_db=_seed_owner_other_and_admin_accounts,
    )
    seed_session(client, "owner")
    return client


@pytest.fixture
def signed_in(tmp_path: Path, pg_factory) -> TestClient:
    return sign_in_owner(tmp_path, pg_factory)


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
        row = a_reference(
            session, user_id, name=name, size_bytes=1, duration_sec=duration_sec,
            created_at=created_at, reference_id=reference_id, unused_since=utcnow(),
        )
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
    song_trashed: bool = False, album_trashed: bool = False, key: str = "link",
    title: str = "S", slug: str = "", version_number: int = 1, generation_number: int = 1,
    duration_sec: float | None = None, created_at: datetime | None = None,
    versionless: bool = False,
) -> None:
    """Link the reference from a saved version (``via="version"``) or from a take.

    Each ``key`` seeds its own album, song and version, so one reference can be linked many times.
    ``versionless`` leaves a take without a version.
    """
    trashed_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    stamp = {} if created_at is None else {"created_at": created_at}
    with client.app.state.ctx.db() as session:
        album = Album(
            id=f"album-{key}", title="A", artist="A", created_by="owner-id",
            deleted_at=trashed_at if album_trashed else None,
        )
        song = Song(
            id=f"song-{key}", title=title, slug=slug, album_id=album.id, track_number=1,
            deleted_at=trashed_at if song_trashed else None,
        )
        version = Version(
            id=f"version-{key}", song_id=song.id, version_number=version_number,
            lyrics="la", prompt="p", **(stamp if via == "version" else {}),
            reference_recording_id=reference_id if via == "version" else None,
        )
        session.add(album)
        session.flush()
        session.add_all([song, version])
        session.flush()
        if via == "take":
            session.add(Generation(
                song_id=song.id, version_id=None if versionless else version.id,
                mp3_path=f"owner-id/{key}.mp3",
                is_archived=archived, reference_recording_id=reference_id,
                generation_number=generation_number, audio_duration_sec=duration_sec, **stamp,
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
