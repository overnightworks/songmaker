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
    """Temporarily replace the scorer registry, restore after test.

    Clears all registered scorers so tests control exactly which scorers run.
    Also resets _scorers_loaded so _ensure_scorers_registered won't re-import
    real scorers during the test.
    """
    saved = dict(_SCORERS)
    saved_loaded = scoring_pipeline._scorers_loaded
    _SCORERS.clear()
    scoring_pipeline._scorers_loaded = True  # Prevent re-import of real scorers
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
    assert d["silence_ok"] is True


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


def test_register_valid_name(clean_registry: dict) -> None:
    @register("silence")
    def my_scorer(mp3_path: Path, meta: object = None, audio_data: object = None, config: object = None) -> SilenceScore:
        return SilenceScore(total_silence_seconds=0, longest_gap_seconds=0, gap_count=0)

    assert "silence" in clean_registry


def test_register_invalid_name_raises() -> None:
    with pytest.raises(ValueError, match="does not match any SongScores field"):
        @register("bogus_name")
        def bad_scorer(mp3_path: Path, meta: object = None, audio_data: object = None, config: object = None) -> None:
            pass


# ── Pipeline runner tests ────────────────────────────────────────────


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_run_pipeline(mock_load: object, clean_registry: dict, fake_mp3: Path) -> None:
    @register("silence")
    def mock_silence(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None,
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
        config: object = None,
    ) -> None:
        raise RuntimeError("boom")

    @register("silence")
    def ok_scorer(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None,
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
        config: object = None,
    ) -> SilenceScore:
        return SilenceScore(
            total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0,
        )

    @register("bpm_accuracy")
    def scorer_b(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None,
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
        emotional_dynamics=EmotionalDynamicsScore(
            pitch_cv=0.3, rms_contrast=2.0, onset_rate_cv=0.2,
            overall_expressiveness=0.5,
        ),
    )
    append_scores_section(snapshot, scores)

    text = snapshot.read_text()
    assert "## Scores" in text
    assert "dynamics:" in text
    assert "silence_gaps:" in text


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
        emotional_dynamics=EmotionalDynamicsScore(
            pitch_cv=0.3, rms_contrast=2.0, onset_rate_cv=0.2,
            overall_expressiveness=0.5,
        ),
    )
    append_scores_section(snapshot, scores_v2)

    text = snapshot.read_text()
    assert text.count("## Scores") == 1
    assert "dynamics:" in text
    assert "silence_ok: True" in text


# ── CLI tests ────────────────────────────────────────────────────────


def test_log_scores(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from songmaker_cli.main import _log_scores

    scores = SongScores(
        silence=SilenceScore(
            total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0,
        ),
        emotional_dynamics=EmotionalDynamicsScore(
            pitch_cv=0.3, rms_contrast=2.0, onset_rate_cv=0.2,
            overall_expressiveness=0.5,
        ),
    )
    with caplog.at_level(logging.INFO):
        _log_scores(scores)

    assert "dynamics" in caplog.text
    assert "silence_ok" in caplog.text


def test_log_ranking(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from songmaker_cli.config import OutputPaths
    from songmaker_cli.main import _log_ranking

    paths_a = OutputPaths(
        output_dir=Path("/tmp"), base_name="song", version=1, versioned_name="song_v1",
    )
    paths_b = OutputPaths(
        output_dir=Path("/tmp"), base_name="song", version=2, versioned_name="song_v2",
    )
    scores_a = SongScores(
        emotional_dynamics=EmotionalDynamicsScore(
            pitch_cv=0.4, rms_contrast=2.0, onset_rate_cv=0.2,
            overall_expressiveness=0.6,
        ),
    )
    scores_b = SongScores(
        emotional_dynamics=EmotionalDynamicsScore(
            pitch_cv=0.1, rms_contrast=1.2, onset_rate_cv=0.1,
            overall_expressiveness=0.3,
        ),
    )

    with caplog.at_level(logging.INFO):
        _log_ranking([(paths_b, scores_b), (paths_a, scores_a)])

    assert "RANKING" in caplog.text
    assert "song_v1" in caplog.text
    assert "song_v2" in caplog.text
    # v1 has higher expressiveness, should be first (marked best)
    lines = caplog.text.split("\n")
    ranking_lines = [l for l in lines if "song_v" in l]
    assert "song_v1" in ranking_lines[0]
    assert "best" in ranking_lines[0]


def test_log_scores_warns_on_silence_problems(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    from songmaker_cli.main import _log_scores

    scores = SongScores(
        silence=SilenceScore(
            total_silence_seconds=5.0, longest_gap_seconds=5.0, gap_count=1,
        ),
    )
    with caplog.at_level(logging.WARNING):
        _log_scores(scores)

    assert "Silence gaps detected" in caplog.text


# ── Text accuracy scorer tests ───────────────────────────────────────


def test_text_accuracy_no_meta() -> None:
    from songmaker_cli.scoring.text_accuracy import score_text_accuracy

    with pytest.raises(ValueError, match="No lyrics"):
        score_text_accuracy(Path("fake.mp3"), meta=None)


def test_text_accuracy_no_lyrics() -> None:
    from songmaker_cli.parser import SongMeta
    from songmaker_cli.scoring.text_accuracy import score_text_accuracy

    meta = SongMeta(title="Test", album="test", prompt="test", lyrics="")
    with pytest.raises(ValueError, match="No lyrics"):
        score_text_accuracy(Path("fake.mp3"), meta=meta)


def test_text_accuracy_with_mock_whisper(tmp_path: Path) -> None:
    from unittest.mock import MagicMock, patch

    from songmaker_cli.parser import SongMeta
    from songmaker_cli.scoring.text_accuracy import score_text_accuracy

    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake")
    meta = SongMeta(
        title="Test", album="test", prompt="test",
        lyrics="[verse]\nHello world\nGoodbye moon",
        generation_params={"language": "en"},
    )

    mock_model = MagicMock()
    mock_model.transcribe.return_value = {
        "text": "Hello world goodbye moon",
        "segments": [{"text": "Hello world"}, {"text": "goodbye moon"}],
    }

    with patch(
        "songmaker_cli.scoring.text_accuracy._get_whisper_model",
        return_value=mock_model,
    ):
        result = score_text_accuracy(mp3, meta=meta)
        assert result.similarity_ratio > 0.5
        assert result.intended_lines == 2
        assert result.transcribed_lines == 2


# ── AudioBox scorer tests ────────────────────────────────────────────


def test_audiobox_with_mock_predictor(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from songmaker_cli.scoring.audiobox_aesthetics import score_audiobox, _predictor_cache

    mp3 = tmp_path / "test.mp3"
    mp3.write_bytes(b"fake")

    mock_predictor = MagicMock()
    mock_predictor.forward.return_value = [
        {"CE": 7.5, "CU": 8.0, "PC": 6.0, "PQ": 8.5},
    ]

    saved = dict(_predictor_cache)
    _predictor_cache["default"] = mock_predictor
    try:
        result = score_audiobox(mp3)
        assert result.content_enjoyment == 7.5
        assert result.production_quality == 8.5
    finally:
        _predictor_cache.clear()
        _predictor_cache.update(saved)


# ── Manifest read_scores tests ───────────────────────────────────────


def test_read_scores_from_snapshot(tmp_path: Path) -> None:
    from songmaker_cli.snapshot import read_scores

    snapshot = tmp_path / "song_v1.md"
    snapshot.write_text(
        "---\ntitle: Test\n---\n\n## Generation\n\n- seed: 123\n\n"
        "## Scores\n\n- dynamics: 48.9\n- silence_ok: True\n- bpm_detected: 94\n"
    )
    scores = read_scores(snapshot)
    assert scores is not None
    assert scores["dynamics"] == 48.9
    assert scores["silence_ok"] is True
    assert scores["bpm_detected"] == 94


def test_read_scores_missing_section(tmp_path: Path) -> None:
    from songmaker_cli.snapshot import read_scores

    snapshot = tmp_path / "song_v1.md"
    snapshot.write_text("---\ntitle: Test\n---\n\n## Generation\n\n- seed: 123\n")
    assert read_scores(snapshot) is None


def test_read_scores_missing_file(tmp_path: Path) -> None:
    from songmaker_cli.snapshot import read_scores

    assert read_scores(tmp_path / "nonexistent.md") is None


def test_scores_roundtrip(tmp_path: Path) -> None:
    """Write scores via append_scores_section, read back via read_scores."""
    from songmaker_cli.snapshot import read_scores

    snapshot = tmp_path / "song_v1.md"
    snapshot.write_text("---\ntitle: Test\n---\n\n## Generation\n\n- seed: 42\n")

    scores = SongScores(
        emotional_dynamics=EmotionalDynamicsScore(
            pitch_cv=0.3, rms_contrast=2.0, onset_rate_cv=0.2,
            overall_expressiveness=0.5,
        ),
        silence=SilenceScore(
            total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0,
        ),
    )
    append_scores_section(snapshot, scores)

    read_back = read_scores(snapshot)
    assert read_back is not None
    assert read_back["dynamics"] == 50.0
    assert read_back["silence_ok"] is True
