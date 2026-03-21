"""Tests for scoring pipeline — models, registry, runner."""

from __future__ import annotations

from pathlib import Path
from typing import Generator
from unittest.mock import patch

import numpy as np
import pytest

from songmaker_cli.scoring.models import (
    AudioBoxScore,
    BpmAccuracyScore,
    EmotionalDynamicsScore,
    SilenceScore,
    SongScores,
    TextAccuracyScore,
)
from songmaker_cli.scoring import pipeline as scoring_pipeline
from songmaker_cli.scoring.pipeline import (
    AudioData,
    _SCORERS,
    register,
    run_scoring_pipeline,
)
from songmaker_cli.snapshot import append_scores_section

_FAKE_AUDIO = AudioData(audio=np.zeros(22050, dtype=np.float32), sr=22050)


@pytest.fixture()
def clean_registry() -> Generator[dict[str, object], None, None]:
    """Temporarily clear the scorer registry, restore after test."""
    saved = dict(_SCORERS)
    saved_loaded = scoring_pipeline._scorers_loaded
    _SCORERS.clear()
    yield _SCORERS
    _SCORERS.clear()
    _SCORERS.update(saved)
    scoring_pipeline._scorers_loaded = saved_loaded


@pytest.fixture()
def fake_mp3(tmp_path: Path) -> Path:
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake")
    return mp3


# ── Model tests ──────────────────────────────────────────────────────


def test_song_scores_overall_empty() -> None:
    scores = SongScores()
    assert scores.overall == 0.0


def test_song_scores_to_dict_empty() -> None:
    scores = SongScores()
    assert scores.to_dict() == {}


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


def test_song_scores_to_dict_consistent_scale() -> None:
    scores = SongScores(
        silence=SilenceScore(
            total_silence_seconds=1.0, longest_gap_seconds=0.5, gap_count=1,
        ),
        audiobox=AudioBoxScore(
            content_enjoyment=7.0, content_understanding=8.0,
            production_complexity=6.0, production_quality=9.0,
        ),
    )
    d = scores.to_dict()
    assert "overall" in d
    assert "silence" in d
    assert "audiobox" in d
    assert "text_accuracy" not in d
    # Both should be on 0-100 scale
    assert 0 <= d["silence"] <= 100
    assert 0 <= d["audiobox"] <= 100


def test_emotional_dynamics_summary() -> None:
    score = EmotionalDynamicsScore(
        pitch_cv=0.3, rms_contrast=2.5, onset_rate_cv=0.4,
        overall_expressiveness=0.72,
    )
    assert score.summary == 72.0


def test_emotional_dynamics_summary_capped() -> None:
    score = EmotionalDynamicsScore(
        pitch_cv=1.0, rms_contrast=5.0, onset_rate_cv=1.0,
        overall_expressiveness=1.5,
    )
    assert score.summary == 100.0


def test_audiobox_summary_scales_to_100() -> None:
    score = AudioBoxScore(
        content_enjoyment=10.0, content_understanding=10.0,
        production_complexity=10.0, production_quality=10.0,
    )
    assert score.summary == 100.0

    score_mid = AudioBoxScore(
        content_enjoyment=5.0, content_understanding=5.0,
        production_complexity=5.0, production_quality=5.0,
    )
    assert score_mid.summary == 50.0


def test_bpm_summary_perfect() -> None:
    score = BpmAccuracyScore(
        detected_bpm=120, requested_bpm=120,
        deviation_percent=0.0, octave_corrected=False,
    )
    assert score.summary == 100.0


def test_bpm_summary_with_deviation() -> None:
    score = BpmAccuracyScore(
        detected_bpm=114, requested_bpm=120,
        deviation_percent=5.0, octave_corrected=False,
    )
    assert score.summary == 75.0


def test_silence_summary_no_gaps() -> None:
    score = SilenceScore(
        total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0,
    )
    assert score.summary == 100.0


def test_to_dict_uses_field_names() -> None:
    scores = SongScores(
        text_accuracy=TextAccuracyScore(
            similarity_ratio=0.9, intended_lines=10, transcribed_lines=10,
        ),
    )
    d = scores.to_dict()
    assert "text_accuracy" in d
    assert d["text_accuracy"] == 90.0


# ── Registry tests ───────────────────────────────────────────────────


def test_register_valid_name(clean_registry: dict) -> None:
    @register("silence")
    def my_scorer(mp3_path: Path, meta: object = None, audio_data: object = None) -> SilenceScore:
        return SilenceScore(total_silence_seconds=0, longest_gap_seconds=0, gap_count=0)

    assert "silence" in clean_registry


def test_register_invalid_name_raises() -> None:
    with pytest.raises(ValueError, match="does not match any SongScores field"):
        @register("bogus_name")
        def bad_scorer(mp3_path: Path, meta: object = None, audio_data: object = None) -> None:
            pass


# ── Pipeline runner tests ────────────────────────────────────────────


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_run_pipeline(mock_load: object, clean_registry: dict, fake_mp3: Path) -> None:
    @register("silence")
    def mock_silence(
        mp3_path: Path, meta: object = None, audio_data: object = None,
    ) -> SilenceScore:
        return SilenceScore(
            total_silence_seconds=0.5, longest_gap_seconds=0.3, gap_count=1,
        )

    scores = run_scoring_pipeline(fake_mp3)
    assert scores.silence is not None
    assert scores.silence.gap_count == 1
    assert scores.text_accuracy is None


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_pipeline_handles_scorer_failure(
    mock_load: object, clean_registry: dict, fake_mp3: Path,
) -> None:
    @register("text_accuracy")
    def broken_scorer(
        mp3_path: Path, meta: object = None, audio_data: object = None,
    ) -> None:
        raise RuntimeError("boom")

    @register("silence")
    def ok_scorer(
        mp3_path: Path, meta: object = None, audio_data: object = None,
    ) -> SilenceScore:
        return SilenceScore(
            total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0,
        )

    scores = run_scoring_pipeline(fake_mp3)
    assert scores.silence is not None
    assert scores.text_accuracy is None


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_pipeline_filters_by_name(
    mock_load: object, clean_registry: dict, fake_mp3: Path,
) -> None:
    @register("silence")
    def scorer_a(
        mp3_path: Path, meta: object = None, audio_data: object = None,
    ) -> SilenceScore:
        return SilenceScore(
            total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0,
        )

    @register("bpm_accuracy")
    def scorer_b(
        mp3_path: Path, meta: object = None, audio_data: object = None,
    ) -> BpmAccuracyScore:
        return BpmAccuracyScore(
            detected_bpm=120, requested_bpm=120,
            deviation_percent=0.0, octave_corrected=False,
        )

    scores = run_scoring_pipeline(fake_mp3, scorers=["silence"])
    assert scores.silence is not None
    assert scores.bpm_accuracy is None


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_pipeline_warns_on_unknown_scorer(
    mock_load: object, clean_registry: dict, fake_mp3: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    with caplog.at_level(logging.WARNING):
        run_scoring_pipeline(fake_mp3, scorers=["nonexistent"])
    assert "Unknown scorer" in caplog.text


# ── Snapshot integration tests ───────────────────────────────────────


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


def test_append_scores_empty_is_noop(tmp_path: Path) -> None:
    snapshot = tmp_path / "song_v1.md"
    original = "---\ntitle: Test\n---\n\nLyrics\n"
    snapshot.write_text(original)

    scores = SongScores()
    append_scores_section(snapshot, scores)

    text = snapshot.read_text()
    assert "## Scores" not in text
    assert text == original


def test_append_scores_idempotent(tmp_path: Path) -> None:
    snapshot = tmp_path / "song_v1.md"
    snapshot.write_text(
        "---\ntitle: Test\n---\n\n## Lyrics\n\nHello\n\n"
        "## Generation\n\n- seed: 123\n"
    )

    scores_v1 = SongScores(
        silence=SilenceScore(
            total_silence_seconds=1.0, longest_gap_seconds=0.5, gap_count=2,
        ),
    )
    append_scores_section(snapshot, scores_v1)

    scores_v2 = SongScores(
        silence=SilenceScore(
            total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0,
        ),
        bpm_accuracy=BpmAccuracyScore(
            detected_bpm=120, requested_bpm=120,
            deviation_percent=0.0, octave_corrected=False,
        ),
    )
    append_scores_section(snapshot, scores_v2)

    text = snapshot.read_text()
    assert text.count("## Scores") == 1
    assert "bpm_accuracy:" in text
    assert "silence: 100.0" in text


# ── CLI tests ────────────────────────────────────────────────────────


def test_log_scores(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from songmaker_cli.main import _log_scores

    scores = SongScores(
        silence=SilenceScore(
            total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0,
        ),
    )
    with caplog.at_level(logging.INFO):
        _log_scores(scores)

    assert "overall" in caplog.text
    assert "silence" in caplog.text
