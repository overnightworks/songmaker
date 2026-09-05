"""Tests for scoring pipeline — models, registry, runner."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import numpy as np
import pytest

from songmaker_cli.scoring.models import (
    AudioBoxScore,
    BpmAccuracyScore,
    EmotionalDynamicsScore,
    ScorerOutcome,
    ScorerRun,
    SilenceScore,
    SongScores,
    TextAccuracyScore,
)
from songmaker_cli.scoring.pipeline import (
    AudioData,
    PipelineConfig,
    ScorerDependencyUnavailable,
    ScorerRegistry,
    judge_watchdog_timeout,
    run_scoring_pipeline,
)

_FAKE_AUDIO = AudioData(audio=np.zeros(22050, dtype=np.float32), sr=22050)


@pytest.fixture
def clean_registry() -> Generator[ScorerRegistry, None, None]:
    """Provide an isolated scorer registry for testing."""
    registry = ScorerRegistry()
    registry.reset_for_testing()
    yield registry


@pytest.fixture
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


def test_to_dict_keys_match_scorer_output_keys_exactly() -> None:
    from songmaker_cli.scoring.models import (
        BpmAccuracyScore,
        LyricalCoherenceScore,
        SilenceScore,
        SpectralQualityScore,
    )
    from songmaker_cli.scoring.registry import SCORERS

    fully_populated = SongScores(
        text_accuracy=TextAccuracyScore(
            similarity_ratio=0.5,
            intended_line_texts=("a",),
            transcribed_line_texts=("a",),
            detected_language="en",
        ),
        lyrical_coherence=LyricalCoherenceScore(score=5, issues=(), summary="ok"),
        emotional_dynamics=EmotionalDynamicsScore(
            pitch_cv=0.1, rms_contrast=0.2, onset_rate_cv=0.3,
            overall_expressiveness=0.4,
        ),
        audiobox=AudioBoxScore(
            content_enjoyment=1.0, content_understanding=2.0,
            production_complexity=3.0, production_quality=4.0,
        ),
        bpm_accuracy=BpmAccuracyScore(
            detected_bpm=120, requested_bpm=120,
            deviation_percent=0.0, octave_corrected=False,
        ),
        silence=SilenceScore(
            total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0,
        ),
        spectral_quality=SpectralQualityScore(
            mean_flatness=0.1, max_flatness=0.2, artifact_count=0, artifact_windows=(),
        ),
    )

    all_declared_keys: set[str] = set()
    for spec in SCORERS.values():
        all_declared_keys.update(spec.output_keys)

    actual_keys = set(fully_populated.to_dict().keys())
    missing = all_declared_keys - actual_keys
    extra = actual_keys - all_declared_keys
    assert not missing, (
        f"SCORERS declares output_keys not emitted by to_dict() when fully populated: {missing}"
    )
    assert not extra, (
        f"to_dict() emitted keys not declared in any SCORERS spec: {extra}"
    )


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
    with pytest.raises(ValueError, match="not a scorer this process runs"):
        @clean_registry.register("bogus_name")
        def bad_scorer(
            mp3_path: Path, meta: object = None,
            audio_data: object = None, config: object = None,
        ) -> None:
            pass


def test_register_refuses_a_parent_hosted_scorer(clean_registry: ScorerRegistry) -> None:
    """lyrical_coherence calls Claude — it runs in the worker parent, so the
    child must not be able to register it and pull the secret into itself."""
    with pytest.raises(ValueError, match="not a scorer this process runs"):
        @clean_registry.register("lyrical_coherence")
        def judge(
            mp3_path: Path, meta: object = None,
            audio_data: object = None, config: object = None,
        ) -> None:
            pass


def test_the_scorer_child_does_not_load_the_claude_judge() -> None:
    from songmaker_cli.scoring.pipeline import default_registry

    assert "lyrical_coherence" not in default_registry.available()


# ── Pipeline runner tests ────────────────────────────────────────────


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_run_pipeline(mock_load: object, clean_registry: ScorerRegistry, fake_mp3: Path) -> None:
    @clean_registry.register("silence")
    def mock_silence(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None,
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
        config: object = None,
    ) -> None:
        raise RuntimeError("boom")

    @clean_registry.register("silence")
    def ok_scorer(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None,
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
        config: object = None,
    ) -> SilenceScore:
        return SilenceScore(
            total_silence_seconds=0.0, longest_gap_seconds=0.0, gap_count=0,
        )

    @clean_registry.register("bpm_accuracy")
    def scorer_b(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None,
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


def test_pipeline_rejects_a_missing_audio_file(
    clean_registry: ScorerRegistry, tmp_path: Path,
) -> None:
    """No audio file is rejected outright, not scored as an empty success.

    The scorers that would have opened the file are the same ones that may be
    absent, so leaving this to ``load_audio`` made a missing generation score
    clean wherever those modules failed to import.
    """
    missing = tmp_path / "nonexistent.mp3"

    with pytest.raises(FileNotFoundError, match=re.escape(str(missing))):
        run_scoring_pipeline(missing, scorers=["silence"], registry=clean_registry)


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
        config: object = None,
    ) -> str:
        return "not a SilenceScore"  # type: ignore[return-value]

    with caplog.at_level(logging.WARNING):
        scores = run_scoring_pipeline(fake_mp3, registry=clean_registry)

    assert scores.silence is None
    assert "expected SilenceScore" in caplog.text


# ── Concurrency tests ────────────────────────────────────────────


SLEEP_SECONDS = 0.3


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_cpu_scorers_run_concurrently(
    mock_load: object, clean_registry: ScorerRegistry, fake_mp3: Path,
) -> None:
    """CPU scorers execute in parallel — total time is less than their sum."""

    @clean_registry.register("silence")
    def slow_silence(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None,
    ) -> SilenceScore:
        time.sleep(SLEEP_SECONDS)
        return SilenceScore(total_silence_seconds=0, longest_gap_seconds=0, gap_count=0)

    @clean_registry.register("bpm_accuracy")
    def slow_bpm(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None,
    ) -> BpmAccuracyScore:
        time.sleep(SLEEP_SECONDS)
        return BpmAccuracyScore(
            detected_bpm=120, requested_bpm=120, deviation_percent=0, octave_corrected=False,
        )

    @clean_registry.register("emotional_dynamics")
    def slow_dynamics(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None,
    ) -> EmotionalDynamicsScore:
        time.sleep(SLEEP_SECONDS)
        return EmotionalDynamicsScore(
            pitch_cv=0.3, rms_contrast=2.0, onset_rate_cv=0.2, overall_expressiveness=0.5,
        )

    start = time.monotonic()
    scores = run_scoring_pipeline(fake_mp3, registry=clean_registry)
    elapsed = time.monotonic() - start

    assert scores.silence is not None
    assert scores.bpm_accuracy is not None
    assert scores.emotional_dynamics is not None
    serial_time = SLEEP_SECONDS * 3
    assert elapsed < serial_time, (
        f"Expected parallel execution, took {elapsed:.2f}s (serial would be {serial_time:.1f}s)"
    )


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_gpu_scorers_run_sequentially_with_cpu_overlap(
    mock_load: object, clean_registry: ScorerRegistry, fake_mp3: Path,
) -> None:
    """GPU scorers run in main thread while CPU scorers execute in pool."""

    @clean_registry.register("silence")
    def cpu_scorer(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None,
    ) -> SilenceScore:
        time.sleep(SLEEP_SECONDS)
        return SilenceScore(total_silence_seconds=0, longest_gap_seconds=0, gap_count=0)

    @clean_registry.register("audiobox")
    def gpu_scorer(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None,
    ) -> AudioBoxScore:
        time.sleep(SLEEP_SECONDS)
        return AudioBoxScore(
            content_enjoyment=7.0, content_understanding=8.0,
            production_complexity=6.0, production_quality=9.0,
        )

    start = time.monotonic()
    scores = run_scoring_pipeline(fake_mp3, registry=clean_registry)
    elapsed = time.monotonic() - start

    assert scores.silence is not None
    assert scores.audiobox is not None
    serial_time = SLEEP_SECONDS * 2
    assert elapsed < serial_time, f"Expected overlapping execution, took {elapsed:.2f}s"


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_gpu_scorer_failure_does_not_block_cpu(
    mock_load: object, clean_registry: ScorerRegistry, fake_mp3: Path,
) -> None:
    """A failing GPU scorer does not prevent CPU scorers from completing."""

    @clean_registry.register("audiobox")
    def broken_gpu(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None,
    ) -> None:
        raise RuntimeError("GPU exploded")

    @clean_registry.register("silence")
    def ok_cpu(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None,
    ) -> SilenceScore:
        return SilenceScore(total_silence_seconds=0, longest_gap_seconds=0, gap_count=0)

    scores = run_scoring_pipeline(fake_mp3, registry=clean_registry)
    assert scores.silence is not None
    assert scores.audiobox is None


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_pipeline_reports_a_known_but_unregistered_scorer_as_skipped(
    mock_load: object, clean_registry: ScorerRegistry, fake_mp3: Path,
) -> None:
    """A scorer whose module never registered is skipped, not failed."""

    @clean_registry.register("silence")
    def ok_scorer(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None,
    ) -> SilenceScore:
        return SilenceScore(total_silence_seconds=0, longest_gap_seconds=0, gap_count=0)

    scores = run_scoring_pipeline(
        fake_mp3, scorers=["silence", "text_accuracy"], registry=clean_registry,
    )
    assert scores.silence is not None
    assert scores.text_accuracy is None
    assert _outcomes(scores) == {
        "silence": ScorerOutcome.OK,
        "text_accuracy": ScorerOutcome.SKIPPED,
    }




# ── Per-scorer outcome tests ─────────────────────────────────────


SCORER_BUDGET_SECONDS = 1
OVER_BUDGET_SECONDS = 1.2


def _outcomes(scores: SongScores) -> dict[str, ScorerOutcome]:
    return {run.scorer: run.outcome for run in scores.runs}


def _silence_scorer(*_args: object, **_kwargs: object) -> SilenceScore:
    return SilenceScore(total_silence_seconds=0, longest_gap_seconds=0, gap_count=0)


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_timed_out_scorer_reports_timeout_and_no_value(
    mock_load: object, clean_registry: ScorerRegistry, fake_mp3: Path,
) -> None:
    clean_registry.register("silence")(_silence_scorer)

    @clean_registry.register("bpm_accuracy")
    def scorer_over_budget(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None,
    ) -> BpmAccuracyScore:
        time.sleep(OVER_BUDGET_SECONDS)
        return BpmAccuracyScore(
            detected_bpm=120, requested_bpm=120, deviation_percent=0, octave_corrected=False,
        )

    scores = run_scoring_pipeline(
        fake_mp3, registry=clean_registry,
        config=PipelineConfig(scorer_timeout=SCORER_BUDGET_SECONDS, pipeline_timeout=30),
    )

    assert scores.bpm_accuracy is None
    assert _outcomes(scores)["bpm_accuracy"] is ScorerOutcome.TIMED_OUT
    assert scores.silence is not None


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_failed_scorer_reports_failure_with_reason(
    mock_load: object, clean_registry: ScorerRegistry, fake_mp3: Path,
) -> None:
    @clean_registry.register("silence")
    def broken_scorer(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None,
    ) -> SilenceScore:
        raise RuntimeError("boom")

    scores = run_scoring_pipeline(fake_mp3, registry=clean_registry)

    run = scores.runs[0]
    assert run.outcome is ScorerOutcome.FAILED
    assert "boom" in run.detail


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_scorer_with_unavailable_dependency_is_skipped_not_failed(
    mock_load: object, clean_registry: ScorerRegistry, fake_mp3: Path,
) -> None:
    @clean_registry.register("text_accuracy")
    def needs_vocals(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None,
    ) -> object:
        raise ScorerDependencyUnavailable("no transcript")

    scores = run_scoring_pipeline(fake_mp3, registry=clean_registry)

    run = scores.runs[0]
    assert run.outcome is ScorerOutcome.SKIPPED
    assert run.detail == "no transcript"


@patch("songmaker_cli.scoring.pipeline.load_audio", return_value=_FAKE_AUDIO)
def test_wrong_return_type_counts_as_failure(
    mock_load: object, clean_registry: ScorerRegistry, fake_mp3: Path,
) -> None:
    """A wrong type must not count as success — it would clear the stored score."""

    @clean_registry.register("silence")
    def wrong_type_scorer(
        mp3_path: Path, meta: object = None, audio_data: object = None,
        config: object = None,
    ) -> object:
        return "not a SilenceScore"

    scores = run_scoring_pipeline(fake_mp3, registry=clean_registry)

    assert scores.silence is None
    assert scores.runs[0].outcome is ScorerOutcome.FAILED
    assert scores.refreshed_output_keys() == frozenset()


# ── Per-scorer timeout configuration ─────────────────────────────


def test_text_accuracy_has_its_own_timeout_budget() -> None:
    config = PipelineConfig()

    assert config.timeout_for("text_accuracy") == config.text_accuracy_timeout
    assert config.timeout_for("silence") == config.scorer_timeout
    assert config.text_accuracy_timeout > config.scorer_timeout


def test_watchdog_outlives_the_slowest_scorer_in_the_child() -> None:
    """The child runs its scorers concurrently, so the watchdog must outlive
    the slowest single budget — if it fires first, produced values are lost."""
    config = PipelineConfig(scorer_timeout=120, text_accuracy_timeout=900)

    assert config.pipeline_timeout > 900


def test_explicit_pipeline_timeout_is_kept() -> None:
    assert PipelineConfig(pipeline_timeout=42).pipeline_timeout == 42


def test_judge_watchdog_outlives_the_provider_budget() -> None:
    assert judge_watchdog_timeout(120) > 120


# ── Outcome reporting ────────────────────────────────────────────


def test_refreshed_output_keys_covers_only_successful_scorers() -> None:
    scores = SongScores(
        runs=(
            ScorerRun(scorer="silence", outcome=ScorerOutcome.OK),
            ScorerRun(scorer="text_accuracy", outcome=ScorerOutcome.TIMED_OUT),
            ScorerRun(scorer="lyrical_coherence", outcome=ScorerOutcome.SKIPPED),
            ScorerRun(scorer="bpm_accuracy", outcome=ScorerOutcome.FAILED),
        ),
    )

    assert scores.refreshed_output_keys() == frozenset({"silence_gaps", "silence_longest"})


def test_outcome_summary_names_every_scorer_and_its_reason() -> None:
    scores = SongScores(
        runs=(
            ScorerRun(scorer="silence", outcome=ScorerOutcome.OK),
            ScorerRun(
                scorer="text_accuracy", outcome=ScorerOutcome.TIMED_OUT,
                detail="timed out after 300s",
            ),
        ),
    )

    assert scores.outcome_summary() == (
        "silence=ok, text_accuracy=timed_out (timed out after 300s)"
    )


def test_scorer_run_rejects_an_unknown_scorer_name() -> None:
    with pytest.raises(ValueError, match="Unknown scorer"):
        ScorerRun(scorer="not_a_scorer", outcome=ScorerOutcome.OK)
