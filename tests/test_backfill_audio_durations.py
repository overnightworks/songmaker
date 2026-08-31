"""Tests for ``scripts/backfill_audio_durations.py``."""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np
import pytest
from conftest import write_wav
from sqlalchemy.orm import Session

from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Generation, Song

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import backfill_audio_durations as backfill  # noqa: E402

_READABLE_DURATION_SECONDS = 1.5


def _seed_generations(session: Session, audio_dir: Path) -> None:
    session.add(Album(id="a1", title="A", artist="X"))
    session.add(Song(id="s1", title="S", album_id="a1", track_number=1))
    session.add(Generation(
        id="g-already-measured", song_id="s1", generation_number=1,
        mp3_path="already.mp3", audio_duration_sec=42.0,
    ))
    session.add(Generation(
        id="g-readable", song_id="s1", generation_number=2,
        mp3_path="readable.mp3",
    ))
    session.add(Generation(
        id="g-missing", song_id="s1", generation_number=3,
        mp3_path="missing.mp3",
    ))
    session.commit()

    write_wav(
        audio_dir / "readable.mp3",
        np.zeros(int(44100 * _READABLE_DURATION_SECONDS)),
        44100,
    )


@pytest.fixture
def seeded_backfill_db(tmp_path: Path) -> tuple:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    factory = init_test_db(tmp_path / "backfill.db")
    with factory() as session:
        _seed_generations(session, audio_dir)
    return factory, audio_dir


def test_dry_run_reports_counts_without_writing(seeded_backfill_db: tuple) -> None:
    factory, audio_dir = seeded_backfill_db

    with factory() as session:
        report = backfill.run_backfill(session, audio_dir, apply=False)

        assert report.filled == 1
        assert report.skipped_already_measured == 1
        assert report.missing_or_unreadable == 1

        session.expire_all()
        untouched = session.get(Generation, "g-readable")
        assert untouched.audio_duration_sec is None


def test_apply_fills_only_readable_unmeasured_rows(seeded_backfill_db: tuple) -> None:
    factory, audio_dir = seeded_backfill_db

    with factory() as session:
        report = backfill.run_backfill(session, audio_dir, apply=True)

    assert report.filled == 1
    assert report.skipped_already_measured == 1
    assert report.missing_or_unreadable == 1

    with factory() as session:
        already = session.get(Generation, "g-already-measured")
        readable = session.get(Generation, "g-readable")
        missing = session.get(Generation, "g-missing")

        assert already.audio_duration_sec == 42.0
        assert readable.audio_duration_sec == pytest.approx(
            _READABLE_DURATION_SECONDS, abs=0.01,
        )
        assert missing.audio_duration_sec is None


def test_apply_is_harmless_to_rerun(seeded_backfill_db: tuple) -> None:
    factory, audio_dir = seeded_backfill_db

    with factory() as session:
        backfill.run_backfill(session, audio_dir, apply=True)

    with factory() as session:
        second_run = backfill.run_backfill(session, audio_dir, apply=True)

    assert second_run.filled == 0
    assert second_run.skipped_already_measured == 2
    assert second_run.missing_or_unreadable == 1

    with factory() as session:
        readable = session.get(Generation, "g-readable")
        assert readable.audio_duration_sec == pytest.approx(
            _READABLE_DURATION_SECONDS, abs=0.01,
        )


def test_main_dry_run_prints_counts_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    seeded_backfill_db: tuple,
    capsys: pytest.CaptureFixture[str],
) -> None:
    factory, audio_dir = seeded_backfill_db
    monkeypatch.setattr(backfill, "init_db", lambda _url: factory)
    monkeypatch.setattr(backfill, "resolve_database_url", lambda: "sqlite:///fake")
    monkeypatch.setattr(backfill, "_resolve_audio_dir", lambda: audio_dir)

    rc = backfill.main([])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Would fill: 1" in out
    assert "Skipped (already measured): 1" in out
    assert "Missing or unreadable: 1" in out
    assert "Dry run only" in out

    with factory() as session:
        assert session.get(Generation, "g-readable").audio_duration_sec is None


def test_main_apply_writes_and_reports_filled(
    monkeypatch: pytest.MonkeyPatch,
    seeded_backfill_db: tuple,
    capsys: pytest.CaptureFixture[str],
) -> None:
    factory, audio_dir = seeded_backfill_db
    monkeypatch.setattr(backfill, "init_db", lambda _url: factory)
    monkeypatch.setattr(backfill, "resolve_database_url", lambda: "sqlite:///fake")
    monkeypatch.setattr(backfill, "_resolve_audio_dir", lambda: audio_dir)

    rc = backfill.main(["--apply"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Filled: 1" in out
    assert "Dry run" not in out

    with factory() as session:
        assert session.get(Generation, "g-readable").audio_duration_sec == pytest.approx(
            _READABLE_DURATION_SECONDS, abs=0.01,
        )


def test_apply_commits_in_batches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A partial commit checkpoint every COMMIT_BATCH_SIZE rows means a run
    interrupted mid-way keeps what it already wrote."""
    monkeypatch.setattr(backfill, "COMMIT_BATCH_SIZE", 2)

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    factory = init_test_db(tmp_path / "batched.db")

    with factory() as session:
        session.add(Album(id="a1", title="A", artist="X"))
        session.add(Song(id="s1", title="S", album_id="a1", track_number=1))
        for i in range(5):
            session.add(Generation(
                id=f"g{i}", song_id="s1", generation_number=i + 1,
                mp3_path=f"take{i}.wav",
            ))
        session.commit()
        for i in range(5):
            _write_short_wav(audio_dir / f"take{i}.wav")

    commit_calls = []
    with factory() as session:
        original_commit = session.commit

        def _counting_commit() -> None:
            commit_calls.append(1)
            original_commit()

        session.commit = _counting_commit
        report = backfill.run_backfill(session, audio_dir, apply=True)

    assert report.filled == 5
    assert len(commit_calls) >= 2


def _write_short_wav(path: Path) -> None:
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(np.zeros(4410, dtype=np.int16).tobytes())
