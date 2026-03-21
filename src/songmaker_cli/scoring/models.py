"""Score dataclasses for the scoring pipeline."""

from __future__ import annotations

from dataclasses import dataclass, fields


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
        return max(0.0, 100.0 - self.deviation_percent * 5)


@dataclass(frozen=True)
class SilenceScore:
    """Problematic silence gaps in the audio."""

    total_silence_seconds: float
    longest_gap_seconds: float
    gap_count: int

    @property
    def summary(self) -> float:
        penalty = min(self.longest_gap_seconds * 10, 50.0)
        penalty += min(self.gap_count * 5, 30.0)
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
        """Weighted average of available scores (0-100)."""
        scores = []
        for field in fields(self):
            value = getattr(self, field.name)
            if value is not None:
                scores.append(value.summary)
        return sum(scores) / len(scores) if scores else 0.0

    def to_dict(self) -> dict[str, float]:
        """Flat dict of all scores for snapshot persistence."""
        result: dict[str, float] = {"overall": round(self.overall, 1)}
        if self.text_accuracy:
            result["text_accuracy"] = round(self.text_accuracy.summary, 1)
        if self.emotional_dynamics:
            result["emotional_dynamics"] = round(self.emotional_dynamics.summary, 1)
        if self.audiobox:
            result["audiobox_enjoyment"] = round(self.audiobox.content_enjoyment, 1)
            result["audiobox_quality"] = round(self.audiobox.production_quality, 1)
        if self.bpm_accuracy:
            result["bpm_accuracy"] = round(self.bpm_accuracy.summary, 1)
        if self.silence:
            result["silence"] = round(self.silence.summary, 1)
        return result
