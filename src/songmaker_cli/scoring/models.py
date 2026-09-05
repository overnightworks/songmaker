"""Score models for the scoring pipeline — values plus per-scorer outcomes."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from enum import StrEnum
from typing import cast

from pydantic import BaseModel, ConfigDict, field_validator

from songmaker_cli.api_models.whisper import WhisperCue
from songmaker_cli.scoring.registry import SCORERS, ScorerHost


class ScorerOutcome(StrEnum):
    """What happened to a single scorer during one pipeline run."""

    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"


class ScorerRun(BaseModel):
    """One scorer's fate in a pipeline run, with the reason when it produced
    no value. Only an ``OK`` run may overwrite a stored score."""

    model_config = ConfigDict(frozen=True)

    scorer: str
    outcome: ScorerOutcome
    detail: str = ""

    @field_validator("scorer")
    @classmethod
    def _must_be_a_known_scorer(cls, value: str) -> str:
        if value not in SCORERS:
            raise ValueError(f"Unknown scorer: {value}")
        return value

    @property
    def produced_value(self) -> bool:
        return self.outcome is ScorerOutcome.OK

    def __str__(self) -> str:
        reason = f" ({self.detail})" if self.detail else ""
        return f"{self.scorer}={self.outcome}{reason}"


@dataclass(frozen=True)
class ScorerExecution:
    """What one scorer produced, and how its run ended."""

    run: ScorerRun
    value: object | None = None


@dataclass(frozen=True)
class TextAccuracyScore:
    """Whisper transcription vs intended lyrics."""

    similarity_ratio: float
    intended_line_texts: tuple[str, ...]
    transcribed_line_texts: tuple[str, ...]
    whisper_cues: tuple[WhisperCue, ...] = ()
    detected_language: str | None = None

    @property
    def intended_lines(self) -> int:
        return len(self.intended_line_texts)

    @property
    def transcribed_lines(self) -> int:
        return len(self.transcribed_line_texts)

    @property
    def transcript(self) -> str:
        """What Whisper heard, as one text — the form the coherence judge
        reads and the generation stores."""
        return "\n".join(self.transcribed_line_texts)

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "text_accuracy": round(self.similarity_ratio * 100, 1),
        }
        if self.detected_language:
            result["detected_language"] = self.detected_language
        return result


@dataclass(frozen=True)
class EmotionalDynamicsScore:
    """Vocal expressiveness — pitch, energy, rhythm variance across sections."""

    pitch_cv: float
    rms_contrast: float
    onset_rate_cv: float
    overall_expressiveness: float

    def to_dict(self) -> dict[str, object]:
        return {
            "dynamics": round(min(self.overall_expressiveness * 100, 100.0), 1),
            "dynamics_pitch_cv": self.pitch_cv,
            "dynamics_rms_contrast": self.rms_contrast,
            "dynamics_onset_cv": self.onset_rate_cv,
        }


@dataclass(frozen=True)
class AudioBoxScore:
    """Meta AudioBox Aesthetics — four quality dimensions (1-10 each)."""

    content_enjoyment: float
    content_understanding: float
    production_complexity: float
    production_quality: float

    def to_dict(self) -> dict[str, object]:
        return {
            "audiobox_enjoyment": self.content_enjoyment,
            "audiobox_understanding": self.content_understanding,
            "audiobox_complexity": self.production_complexity,
            "audiobox_quality": self.production_quality,
        }


@dataclass(frozen=True)
class SpectralQualityScore:
    """Spectral artifact detection — flags noise, distortion, glitches."""

    mean_flatness: float
    max_flatness: float
    artifact_count: int
    artifact_windows: tuple[tuple[float, float], ...]

    @property
    def has_artifacts(self) -> bool:
        return self.artifact_count > 0

    def to_dict(self) -> dict[str, object]:
        return {"spectral_artifacts": self.artifact_count}


@dataclass(frozen=True)
class LyricalCoherenceScore:
    """Claude LLM judge — rates lyrical coherence 1-10 with issues."""

    score: int
    issues: tuple[str, ...]
    summary: str

    def to_dict(self) -> dict[str, object]:
        return {
            "lyrical_coherence": self.score,
            "lyrical_summary": self.summary,
        }


@dataclass(frozen=True)
class BpmAccuracyScore:
    """Detected vs requested BPM. Informational — not a quality indicator."""

    detected_bpm: float
    requested_bpm: int
    deviation_percent: float
    octave_corrected: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "bpm_detected": self.detected_bpm,
            "bpm_deviation": self.deviation_percent,
        }


@dataclass(frozen=True)
class SilenceScore:
    """Silence gap detection. Used as a pass/fail flag, not a quality score."""

    total_silence_seconds: float
    longest_gap_seconds: float
    gap_count: int

    @property
    def has_problems(self) -> bool:
        """True if any gap exceeds the minimum threshold."""
        return self.gap_count > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "silence_gaps": self.gap_count,
            "silence_longest": self.longest_gap_seconds,
        }


@dataclass(frozen=True)
class SongScores:
    """Aggregated results from all scorers.

    No overall score — individual metrics serve different purposes:
    - silence: pass/fail flag (problematic gaps?)
    - bpm_accuracy: informational (what BPM was detected?)
    - emotional_dynamics: relative comparison (sort versions, listen to top N)
    - text_accuracy: quality signal (did the model sing the right words?)
    - audiobox: quality signal (production quality from Meta's model)
    - spectral_quality: pass/fail flag (noise artifacts?)
    - lyrical_coherence: LLM judge (do the sung lyrics make sense?)
    """

    text_accuracy: TextAccuracyScore | None = None
    lyrical_coherence: LyricalCoherenceScore | None = None
    emotional_dynamics: EmotionalDynamicsScore | None = None
    audiobox: AudioBoxScore | None = None
    bpm_accuracy: BpmAccuracyScore | None = None
    silence: SilenceScore | None = None
    spectral_quality: SpectralQualityScore | None = None
    runs: tuple[ScorerRun, ...] = ()

    def including(self, execution: ScorerExecution) -> SongScores:
        """These scores plus one more scorer's run.

        The value lands only when that scorer produced one, so a failed,
        skipped, or timed-out run contributes its reason alone and leaves
        whatever the generation already scored untouched.
        """
        produced = (
            {execution.run.scorer: execution.value}
            if execution.run.produced_value else {}
        )
        return cast(
            SongScores,
            replace(self, runs=(*self.runs, execution.run), **produced),
        )

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for name in _TO_DICT_ORDER:
            score = getattr(self, name)
            if score is not None:
                result.update(score.to_dict())
        return result

    def refreshed_output_keys(self) -> frozenset[str]:
        """Score keys owned by the scorers that produced a value in this run.

        Persisting replaces exactly these keys, so a scorer that failed,
        timed out, or was skipped keeps its previously stored value.
        """
        return frozenset(
            key
            for run in self.runs
            if run.produced_value
            for key in SCORERS[run.scorer].output_keys
        )

    @property
    def any_child_scorer_timed_out(self) -> bool:
        """True when a scorer inside the scorer child blew its budget.

        Its call was abandoned, not stopped, so that child still runs it and
        is no longer clean. A parent-hosted scorer over budget leaves its
        thread here instead — killing the child would reclaim nothing.
        """
        return any(
            run.outcome is ScorerOutcome.TIMED_OUT
            and SCORERS[run.scorer].host is ScorerHost.CHILD
            for run in self.runs
        )

    def outcome_summary(self) -> str:
        """Every scorer's outcome in one line, for the job log."""
        return ", ".join(str(run) for run in self.runs) if self.runs else "no scorers ran"


_TO_DICT_ORDER: tuple[str, ...] = (
    "emotional_dynamics",
    "text_accuracy",
    "audiobox",
    "bpm_accuracy",
    "silence",
    "spectral_quality",
    "lyrical_coherence",
)

assert frozenset(_TO_DICT_ORDER) == frozenset(SCORERS.keys()), (
    "_TO_DICT_ORDER must contain exactly the scorer names from SCORERS"
)

SCORE_TYPES: dict[str, type] = {
    "text_accuracy": TextAccuracyScore,
    "lyrical_coherence": LyricalCoherenceScore,
    "emotional_dynamics": EmotionalDynamicsScore,
    "audiobox": AudioBoxScore,
    "bpm_accuracy": BpmAccuracyScore,
    "silence": SilenceScore,
    "spectral_quality": SpectralQualityScore,
}

_SCORE_FIELD_NAMES = frozenset(f.name for f in fields(SongScores)) - {"runs"}

assert frozenset(SCORE_TYPES) == _SCORE_FIELD_NAMES == frozenset(SCORERS.keys()), (
    "SCORE_TYPES, the SongScores score fields, and SCORERS must name the same scorers"
)
