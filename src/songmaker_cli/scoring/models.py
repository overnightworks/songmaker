"""Score dataclasses for the scoring pipeline."""

from __future__ import annotations

from dataclasses import dataclass, fields

from songmaker_cli.constants import (
    BPM_DEVIATION_PENALTY,
    SILENCE_GAP_COUNT_MAX_PENALTY,
    SILENCE_GAP_COUNT_PENALTY,
    SILENCE_LONGEST_GAP_MAX_PENALTY,
    SILENCE_LONGEST_GAP_PENALTY,
)


@dataclass(frozen=True)
class TextAccuracyScore:
    """Whisper transcription vs intended lyrics."""

    similarity_ratio: float
    intended_lines: int
    transcribed_lines: int

    @property
    def summary(self) -> float:
        return self.similarity_ratio * 100


@dataclass(frozen=True)
class EmotionalDynamicsScore:
    """Vocal expressiveness — pitch, energy, rhythm variance across sections."""

    pitch_cv: float
    rms_contrast: float
    onset_rate_cv: float
    overall_expressiveness: float

    @property
    def summary(self) -> float:
        return min(self.overall_expressiveness * 100, 100.0)


@dataclass(frozen=True)
class AudioBoxScore:
    """Meta AudioBox Aesthetics — four quality dimensions (1-10 each)."""

    content_enjoyment: float
    content_understanding: float
    production_complexity: float
    production_quality: float

    @property
    def summary(self) -> float:
        mean = (
            self.content_enjoyment
            + self.content_understanding
            + self.production_complexity
            + self.production_quality
        ) / 4
        return mean * 10


@dataclass(frozen=True)
class BpmAccuracyScore:
    """Detected vs requested BPM."""

    detected_bpm: float
    requested_bpm: int
    deviation_percent: float
    octave_corrected: bool

    @property
    def summary(self) -> float:
        return max(0.0, 100.0 - self.deviation_percent * BPM_DEVIATION_PENALTY)


@dataclass(frozen=True)
class SilenceScore:
    """Problematic silence gaps in the audio."""

    total_silence_seconds: float
    longest_gap_seconds: float
    gap_count: int

    @property
    def summary(self) -> float:
        penalty = min(
            self.longest_gap_seconds * SILENCE_LONGEST_GAP_PENALTY,
            SILENCE_LONGEST_GAP_MAX_PENALTY,
        )
        penalty += min(
            self.gap_count * SILENCE_GAP_COUNT_PENALTY,
            SILENCE_GAP_COUNT_MAX_PENALTY,
        )
        return max(0.0, 100.0 - penalty)


@dataclass(frozen=True)
class SongScores:
    """Aggregated scores from all scorers."""

    text_accuracy: TextAccuracyScore | None = None
    emotional_dynamics: EmotionalDynamicsScore | None = None
    audiobox: AudioBoxScore | None = None
    bpm_accuracy: BpmAccuracyScore | None = None
    silence: SilenceScore | None = None

    @property
    def overall(self) -> float:
        """Unweighted average of available scorer summaries (0-100)."""
        scores = []
        for field in fields(self):
            value = getattr(self, field.name)
            if value is not None:
                scores.append(value.summary)
        return sum(scores) / len(scores) if scores else 0.0

    def to_dict(self) -> dict[str, float]:
        """Flat dict of all scores (0-100 scale) for snapshot persistence.

        Returns empty dict if no scorers produced results.
        """
        per_scorer: dict[str, float] = {}
        for field in fields(self):
            value = getattr(self, field.name)
            if value is not None:
                per_scorer[field.name] = round(value.summary, 1)
        if not per_scorer:
            return {}
        return {"overall": round(self.overall, 1), **per_scorer}
