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
from songmaker_cli.scoring.pipeline import (
    AudioData,
    ScorerRegistry,
    run_scoring_pipeline,
)

_FAKE_AUDIO = AudioData(audio=np.zeros(22050, dtype=np.float32), sr=22050)


@pytest.fixture()
def clean_registry() -> Generator[ScorerRegistry, None, None]:
    """Provide an isolated scorer registry for testing."""
    registry = ScorerRegistry()
    registry.reset_for_testing()
    yield registry


@pytest.fixture()
def fake_mp3(tmp_path: Path) -> Path:
    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake")
    return mp3


# ── Model tests ──────────────────────────────────────────────────────


def test_song_scores_to_dict_empty() -> None:
    scores = SongScores()
    assert scores.to_dict() == {}


def test_song_scores_to_dict_dynamics() -> None:
    scores = SongScores(
        emotional_dynamics=EmotionalDynamicsScore(
            pitch_cv=0.3, rms_contrast=2.5, onset_rate_cv=0.4,
            overall_expressiveness=0.72,
        ),
    )
    d = scores.to_dict()
    assert d["dynamics"] == 72.0
    assert d["dynamics_pitch_cv"] == 0.3
    assert "overall" not in d


def test_song_scores_to_dict_all_scorers() -> None:
    scores = SongScores(
        text_accuracy=TextAccuracyScore(
            similarity_ratio=0.8,
            intended_line_texts=tuple(f"line{i}" for i in range(10)),
            transcribed_line_texts=tuple(f"line{i}" for i in range(9)),
        ),
        emotional_dynamics=EmotionalDynamicsScore(
            pitch_cv=0.3, rms_contrast=2.0, onset_rate_cv=0.2,
            overall_expressiveness=0.5,
        ),
        audiobox=AudioBoxScore(
            content_enjoyment=7.0, content_understanding=8.0,
            production_complexity=6.0, production_quality=9.0,
        ),
        bpm_accuracy=BpmAccuracyScore(
            detected_bpm=118, requested_bpm=120,
            deviation_percent=1.7, octave_corrected=False,
        ),
        silence=SilenceScore(
            total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0,
        ),
    )
    d = scores.to_dict()
    assert d["text_accuracy"] == 80.0
    assert d["dynamics"] == 50.0
    assert d["audiobox_enjoyment"] == 7.0
    assert d["audiobox_quality"] == 9.0
    assert d["bpm_detected"] == 118
    assert d["bpm_deviation"] == 1.7
    assert d["silence_gaps"] == 0
    assert "silence_ok" not in d


def test_silence_has_problems() -> None:
    clean = SilenceScore(total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0)
    assert clean.has_problems is False

    problematic = SilenceScore(total_silence_seconds=3.0, longest_gap_seconds=3.0, gap_count=1)
    assert problematic.has_problems is True


def test_emotional_dynamics_expressiveness_capped() -> None:
    score = EmotionalDynamicsScore(
        pitch_cv=1.0, rms_contrast=5.0, onset_rate_cv=1.0,
        overall_expressiveness=1.5,
    )
    d = SongScores(emotional_dynamics=score).to_dict()
    assert d["dynamics"] == 100.0


# ── Registry tests ───────────────────────────────────────────────────


def test_register_valid_name(clean_registry: ScorerRegistry) -> None:
    @clean_registry.register("silence")
    def my_scorer(
        mp3_path: Path, meta: object = None,
        audio_data: object = None, config: object = None,
    ) -> SilenceScore:
        return SilenceScore(total_silence_seconds=0, longest_gap_seconds=0, gap_count=0)

    assert clean_registry.get("silence") is not None


def test_register_invalid_name_raises(clean_registry: ScorerRegistry) -> None:
    with pytest.raises(ValueError, match="does not match any SongScores field"):
        @clean_registry.register("bogus_name")
        def bad_scorer(
            mp3_path: Path, meta: object = None,
            audio_data: object = None, config: object = None,
        ) -> None:
            pass


# ── Pipeline runner tests ────────────────────────────────────────────


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_run_pipeline(mock_load: object, clean_registry: ScorerRegistry, fake_mp3: Path) -> None:
    @clean_registry.register("silence")
    def mock_silence(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None, shared_data: object = None,
    ) -> SilenceScore:
        return SilenceScore(
            total_silence_seconds=0.5, longest_gap_seconds=0.3, gap_count=1,
        )

    scores = run_scoring_pipeline(fake_mp3, registry=clean_registry)
    assert scores.silence is not None
    assert scores.silence.gap_count == 1
    assert scores.text_accuracy is None


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_pipeline_handles_scorer_failure(
    mock_load: object, clean_registry: ScorerRegistry, fake_mp3: Path,
) -> None:
    @clean_registry.register("text_accuracy")
    def broken_scorer(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None, shared_data: object = None,
    ) -> None:
        raise RuntimeError("boom")

    @clean_registry.register("silence")
    def ok_scorer(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None, shared_data: object = None,
    ) -> SilenceScore:
        return SilenceScore(
            total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0,
        )

    scores = run_scoring_pipeline(fake_mp3, registry=clean_registry)
    assert scores.silence is not None
    assert scores.text_accuracy is None


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_pipeline_filters_by_name(
    mock_load: object, clean_registry: ScorerRegistry, fake_mp3: Path,
) -> None:
    @clean_registry.register("silence")
    def scorer_a(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None, shared_data: object = None,
    ) -> SilenceScore:
        return SilenceScore(
            total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0,
        )

    @clean_registry.register("bpm_accuracy")
    def scorer_b(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None, shared_data: object = None,
    ) -> BpmAccuracyScore:
        return BpmAccuracyScore(
            detected_bpm=120, requested_bpm=120,
            deviation_percent=0.0, octave_corrected=False,
        )

    scores = run_scoring_pipeline(fake_mp3, scorers=["silence"], registry=clean_registry)
    assert scores.silence is not None
    assert scores.bpm_accuracy is None


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_pipeline_warns_on_unknown_scorer(
    mock_load: object, clean_registry: ScorerRegistry, fake_mp3: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    with caplog.at_level(logging.WARNING):
        run_scoring_pipeline(fake_mp3, scorers=["nonexistent"], registry=clean_registry)
    assert "Unknown scorer" in caplog.text


# ── Type validation tests ─────────────────────────────────────────


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_pipeline_rejects_wrong_return_type(
    mock_load: object, clean_registry: ScorerRegistry, fake_mp3: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A scorer returning the wrong type gets logged and treated as None."""
    import logging

    @clean_registry.register("silence")
    def wrong_type_scorer(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None, shared_data: object = None,
    ) -> str:
        return "not a SilenceScore"  # type: ignore[return-value]

    with caplog.at_level(logging.WARNING):
        scores = run_scoring_pipeline(fake_mp3, registry=clean_registry)

    assert scores.silence is None
    assert "expected SilenceScore" in caplog.text


