"""Regression evidence for the retired remaster API."""

from pathlib import Path

import pytest
from conftest import (
    make_test_app,
    seed_session,
)
from sqlalchemy import select

from songmaker_cli.constants import AuditAction, ResourceType
from songmaker_cli.db.models import Album, AuditLog, Generation, Song, User
from songmaker_cli.db.queries.auth import record_audit


@pytest.mark.parametrize("authenticated", [True, False], ids=["owner", "unauthenticated"])
def test_remaster_is_unavailable_and_preserves_audio_and_history(
    tmp_path: Path, make_stereo_wav_bytes, authenticated: bool, mock_arq_pool,
) -> None:
    """1301-F3-M-REMOVED; 1301-F3-M-PRESERVED: retirement never mutates assets."""
    client, db = make_test_app(tmp_path)
    audio_dir = tmp_path / "audio"
    audio_before = {
        "generation.raw.wav": make_stereo_wav_bytes(),
        "generation.wav": b"existing mastered wav",
        "generation.mp3": b"existing mp3",
        "generation.pre-remaster.wav": b"historical wav backup",
        "generation.pre-remaster.mp3": b"historical mp3 backup",
    }
    for name, content in audio_before.items():
        (audio_dir / name).write_bytes(content)
    with db() as session:
        session.add(User(id="owner", username="owner"))
        session.flush()
        session.add(Album(id="album", title="Album", artist="Artist", created_by="owner"))
        session.add(Song(id="song", album_id="album", title="Song", track_number=1))
        session.add(Generation(
            id="generation", song_id="song", mp3_path="generation.mp3",
            wav_path="generation.wav", created_by="owner",
        ))
        session.flush()
        record_audit(
            session, "owner", AuditAction.REMASTER, ResourceType.GENERATION, "generation",
        )
        session.commit()

    with client:
        if authenticated:
            seed_session(client, "owner")
        with db() as session:
            generation_before = session.execute(select(Generation.__table__)).all()
            audits_before = session.execute(select(AuditLog.__table__).order_by(AuditLog.id)).all()

        response = client.post("/api/generations/generation/remaster")

        assert response.status_code in ({404} if authenticated else {401, 403, 404})
        if response.status_code == 404:
            assert response.json() == {"detail": "Not Found"}
        paths = client.app.openapi()["paths"]
        assert "/api/generations/{gen_id}/remaster" not in paths

    assert {
        path.relative_to(audio_dir).as_posix(): path.read_bytes()
        for path in audio_dir.rglob("*") if path.is_file()
    } == audio_before
    with db() as session:
        assert session.execute(select(Generation.__table__)).all() == generation_before
        audits_after = session.execute(select(AuditLog.__table__).order_by(AuditLog.id)).all()
        assert audits_after == audits_before
