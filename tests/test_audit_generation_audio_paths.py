"""Tests for ``scripts/audit_generation_audio_paths.py``."""

from __future__ import annotations

import sys
from pathlib import Path

from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Generation, Song

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import audit_generation_audio_paths as audit  # noqa: E402


def test_audit_reports_legacy_paths_without_changing_them(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    (audio_dir / "owner").mkdir(parents=True)
    factory = init_test_db(tmp_path / "audit.db")
    with factory() as session:
        session.add(Album(id="a1", title="A", artist="X"))
        session.add(Song(id="s1", title="S", album_id="a1", track_number=1))
        session.add_all([
            Generation(
                id="canonical", song_id="s1", generation_number=1,
                mp3_path="owner/good.mp3",
            ),
            Generation(
                id="normalizable", song_id="s1", generation_number=2,
                mp3_path="owner/../owner/normalizable.mp3",
            ),
            Generation(
                id="outside", song_id="s1", generation_number=3,
                mp3_path="../outside.mp3",
            ),
            Generation(
                id="wav-only", song_id="s1", generation_number=4,
                mp3_path="",
            ),
        ])
        session.commit()

        report = audit.audit_generation_audio_paths(session, audio_dir)

        assert report.canonical == 1
        assert report.wav_only == 1
        assert report.mismatches == [
            audit.AudioPathMismatch(
                generation_id="normalizable",
                stored_path="owner/../owner/normalizable.mp3",
                canonical_path="owner/normalizable.mp3",
            ),
            audit.AudioPathMismatch(
                generation_id="outside",
                stored_path="../outside.mp3",
                canonical_path=None,
            ),
        ]
        session.expire_all()
        assert session.get(Generation, "normalizable").mp3_path == "owner/../owner/normalizable.mp3"
        assert session.get(Generation, "outside").mp3_path == "../outside.mp3"
