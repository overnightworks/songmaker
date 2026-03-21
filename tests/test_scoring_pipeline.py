"""Tests for scoring pipeline — models, registry, runner."""

from __future__ import annotations

from pathlib import Path

from songmaker_cli.scoring.models import (
    BpmAccuracyScore,
    EmotionalDynamicsScore,
    SilenceScore,
    SongScores,
    TextAccuracyScore,
)
from songmaker_cli.scoring.pipeline import (
    _SCORERS,
    register,
    run_scoring_pipeline,
)
from songmaker_cli.snapshot import append_scores_section


def test_song_scores_overall_empty() -> None:
    scores = SongScores()
    assert scores.overall == 0.0


def test_song_scores_overall_averages() -> None:
    scores = SongScores(
        text_accuracy=TextAccuracyScore(
            similarity_ratio=0.8, intended_lines=10, transcribed_lines=9,
        ),
        bpm_accuracy=BpmAccuracyScore(
            detected_bpm=120, requested_bpm=120, deviation_percent=0.0,
            octave_corrected=False,
        ),
    )
    assert scores.text_accuracy is not None
    assert scores.text_accuracy.summary == 80.0
    assert scores.bpm_accuracy is not None
    assert scores.bpm_accuracy.summary == 100.0
    assert scores.overall == 90.0


def test_song_scores_to_dict() -> None:
    scores = SongScores(
        silence=SilenceScore(
            total_silence_seconds=1.0, longest_gap_seconds=0.5, gap_count=1,
        ),
    )
    d = scores.to_dict()
    assert "overall" in d
    assert "silence" in d
    assert "text_accuracy" not in d


def test_emotional_dynamics_summary() -> None:
    score = EmotionalDynamicsScore(
        pitch_cv=0.3, rms_contrast=2.5, onset_rate_cv=0.4,
        overall_expressiveness=0.72,
    )
    assert score.summary == 72.0


def test_register_and_run_pipeline(tmp_path: Path) -> None:
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake")

    saved = dict(_SCORERS)
    try:
        _SCORERS.clear()

        @register("silence")
        def mock_silence(mp3_path: Path, meta: object = None) -> SilenceScore:
            return SilenceScore(
                total_silence_seconds=0.5, longest_gap_seconds=0.3, gap_count=1,
            )

        scores = run_scoring_pipeline(mp3)
        assert scores.silence is not None
        assert scores.silence.gap_count == 1
        assert scores.text_accuracy is None
    finally:
        _SCORERS.clear()
        _SCORERS.update(saved)


def test_pipeline_handles_scorer_failure(tmp_path: Path) -> None:
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake")

    saved = dict(_SCORERS)
    try:
        _SCORERS.clear()

        @register("broken")
        def broken_scorer(mp3_path: Path, meta: object = None) -> None:
            raise RuntimeError("boom")

        @register("silence")
        def ok_scorer(mp3_path: Path, meta: object = None) -> SilenceScore:
            return SilenceScore(
                total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0,
            )

        scores = run_scoring_pipeline(mp3)
        assert scores.silence is not None
        assert scores.silence.gap_count == 0
    finally:
        _SCORERS.clear()
        _SCORERS.update(saved)


def test_pipeline_filters_by_name(tmp_path: Path) -> None:
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake")

    saved = dict(_SCORERS)
    try:
        _SCORERS.clear()

        @register("silence")
        def scorer_a(mp3_path: Path, meta: object = None) -> SilenceScore:
            return SilenceScore(
                total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0,
            )

        @register("bpm_accuracy")
        def scorer_b(mp3_path: Path, meta: object = None) -> BpmAccuracyScore:
            return BpmAccuracyScore(
                detected_bpm=120, requested_bpm=120,
                deviation_percent=0.0, octave_corrected=False,
            )

        scores = run_scoring_pipeline(mp3, scorers=["silence"])
        assert scores.silence is not None
        assert scores.bpm_accuracy is None
    finally:
        _SCORERS.clear()
        _SCORERS.update(saved)


def test_append_scores_to_snapshot(tmp_path: Path) -> None:
    snapshot = tmp_path / "song_v1.md"
    snapshot.write_text(
        "---\ntitle: Test\n---\n\n## Lyrics\n\nHello\n\n"
        "## Generation\n\n- seed: 123\n"
    )

    scores = SongScores(
        silence=SilenceScore(
            total_silence_seconds=1.0, longest_gap_seconds=0.5, gap_count=2,
        ),
        bpm_accuracy=BpmAccuracyScore(
            detected_bpm=118, requested_bpm=120,
            deviation_percent=1.7, octave_corrected=False,
        ),
    )
    append_scores_section(snapshot, scores)

    text = snapshot.read_text()
    assert "## Scores" in text
    assert "silence:" in text
    assert "bpm_accuracy:" in text
    assert "overall:" in text
