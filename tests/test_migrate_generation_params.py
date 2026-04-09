"""Tests for ``scripts/migrate_generation_params.py``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, GenerationPreset, Song

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import migrate_generation_params as mig  # noqa: E402


def _seed_db_with_corrupt_rows(tmp_path: Path):
    factory = init_test_db(tmp_path / "mig.db")
    with factory() as session:
        session.add(Album(id="a1", title="A", artist="X"))
        session.add(Song(id="s1", title="S", album_id="a1", track_number=1))
        session.commit()
        session.execute(text(
            "INSERT INTO versions "
            "(id, song_id, version_number, lyrics, prompt, bpm, audio_duration, "
            "key_scale, generation_params, created_at) "
            "VALUES ('vbad', 's1', 1, '', '', 120, 180, '', :params, "
            "CURRENT_TIMESTAMP)",
        ), {"params": json.dumps({"shift": 2.0, "bogus_field": "x"})})
        session.execute(text(
            "INSERT INTO versions "
            "(id, song_id, version_number, lyrics, prompt, bpm, audio_duration, "
            "key_scale, generation_params, created_at) "
            "VALUES ('vgood', 's1', 2, '', '', 120, 180, '', :params, "
            "CURRENT_TIMESTAMP)",
        ), {"params": json.dumps({"shift": 1.0})})
        session.execute(text(
            "INSERT INTO generations "
            "(id, song_id, version_id, generation_number, mp3_path, "
            "model_mode, generation_params, status, is_archived, "
            "is_picked, is_kept, is_shared, created_at) "
            "VALUES ('gbad', 's1', 'vgood', 1, 'm.mp3', 'sft', :params, "
            "'completed', 0, 0, 0, 0, CURRENT_TIMESTAMP)",
        ), {"params": json.dumps({"acestep_model": "sft", "junk": True})})
        session.commit()
    return factory


def test_dry_run_reports_invalid_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    factory = _seed_db_with_corrupt_rows(tmp_path)
    monkeypatch.setattr(mig, "init_db", lambda _url: factory)
    monkeypatch.setattr(mig, "resolve_database_url", lambda: "sqlite:///fake")

    rc = mig.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "Found 2 invalid rows" in out
    assert "vbad" in out
    assert "gbad" in out
    assert "vgood" not in out


def test_fix_drops_unknown_keys_and_rewrites(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    factory = _seed_db_with_corrupt_rows(tmp_path)
    monkeypatch.setattr(mig, "init_db", lambda _url: factory)
    monkeypatch.setattr(mig, "resolve_database_url", lambda: "sqlite:///fake")

    rc = mig.main(["--fix"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Fixed 2 rows" in out

    with factory() as session:
        rows = session.execute(text(
            "SELECT generation_params FROM versions WHERE id='vbad'",
        )).all()
        params = json.loads(rows[0][0]) if isinstance(rows[0][0], str) else rows[0][0]
        assert "bogus_field" not in params
        assert params["shift"] == 2.0

        rows = session.execute(text(
            "SELECT generation_params FROM generations WHERE id='gbad'",
        )).all()
        params = json.loads(rows[0][0]) if isinstance(rows[0][0], str) else rows[0][0]
        assert "junk" not in params
        assert params["acestep_model"] == "sft"


def test_dry_run_clean_db_returns_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    factory = init_test_db(tmp_path / "clean.db")
    with factory() as session:
        session.add(Album(id="a1", title="A", artist="X"))
        session.add(Song(id="s1", title="S", album_id="a1", track_number=1))
        session.add(GenerationPreset(
            id="p1", name="preset", model_mode="sft",
            params={"shift": 3.0},
        ))
        session.commit()

    monkeypatch.setattr(mig, "init_db", lambda _url: factory)
    monkeypatch.setattr(mig, "resolve_database_url", lambda: "sqlite:///fake")

    rc = mig.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "validate cleanly" in out
