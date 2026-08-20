"""Score dataclasses for the scoring pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

from songmaker_cli.api_models.whisper import WhisperCue
from songmaker_cli.scoring.registry import SCORERS


@dataclass
class SharedScorerData:
    """Data shared between scorer phases (e.g. text_accuracy → lyrical_coherence).

    Mutable: scorers write fields during execution. Not frozen because
    GPU-phase scorers populate data that CPU-phase scorers read.
    """

    whisper_text: str | None = field(default=None)


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

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for name in _TO_DICT_ORDER:
            score = getattr(self, name)
            if score is not None:
                result.update(score.to_dict())
        return result


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
