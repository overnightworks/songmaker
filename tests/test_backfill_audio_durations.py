"""Tests for ``scripts/backfill_audio_durations.py``."""

from __future__ import annotations

import sys
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
    monkeypatch.setattr(backfill, "connect_db", lambda _url: factory)
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
    monkeypatch.setattr(backfill, "connect_db", lambda _url: factory)
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


def test_apply_survives_an_interruption_after_the_first_commit_batch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The done-when promise, pinned instead of counted: an aborted run keeps
    the batches it already committed, and a rerun fills exactly the rest.

    COMMIT_BATCH_SIZE=2 over 5 rows (processed in id order) means the first
    commit lands after g0 and g1. The probe is made to blow up on the 3rd
    call (g2) to simulate a mid-run crash — g0/g1 must survive that crash
    already written; g2..g4 must still be NULL until the rerun fills them.
    """
    monkeypatch.setattr(backfill, "COMMIT_BATCH_SIZE", 2)

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    factory = init_test_db(tmp_path / "batched.db")

    generation_ids = [f"g{i}" for i in range(5)]
    with factory() as session:
        session.add(Album(id="a1", title="A", artist="X"))
        session.add(Song(id="s1", title="S", album_id="a1", track_number=1))
        for i, gen_id in enumerate(generation_ids):
            session.add(Generation(
                id=gen_id, song_id="s1", generation_number=i + 1,
                mp3_path=f"take{i}.wav",
            ))
        session.commit()
        for i in range(5):
            write_wav(audio_dir / f"take{i}.wav", np.zeros(4410), 44100)

    real_read_audio_duration = backfill.queue_streams.read_audio_duration
    calls_made = 0

    def _probe_that_crashes_on_the_third_call(path: Path) -> float | None:
        nonlocal calls_made
        calls_made += 1
        if calls_made == 3:
            raise RuntimeError("simulated crash mid-run")
        return real_read_audio_duration(path)

    monkeypatch.setattr(
        backfill.queue_streams, "read_audio_duration",
        _probe_that_crashes_on_the_third_call,
    )

    with pytest.raises(RuntimeError, match="simulated crash mid-run"), factory() as session:
        backfill.run_backfill(session, audio_dir, apply=True)

    with factory() as session:
        measured_after_crash = {
            gen_id: session.get(Generation, gen_id).audio_duration_sec
            for gen_id in generation_ids
        }
    assert measured_after_crash["g0"] is not None
    assert measured_after_crash["g1"] is not None
    assert measured_after_crash["g2"] is None
    assert measured_after_crash["g3"] is None
    assert measured_after_crash["g4"] is None

    monkeypatch.setattr(
        backfill.queue_streams, "read_audio_duration", real_read_audio_duration,
    )
    with factory() as session:
        rerun_report = backfill.run_backfill(session, audio_dir, apply=True)

    assert rerun_report.filled == 3
    assert rerun_report.skipped_already_measured == 2

    with factory() as session:
        for gen_id in generation_ids:
            assert session.get(Generation, gen_id).audio_duration_sec is not None
