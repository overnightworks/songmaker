"""Score dataclasses for the scoring pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextAccuracyScore:
    """Whisper transcription vs intended lyrics."""

    similarity_ratio: float
    intended_lines: int
    transcribed_lines: int


@dataclass(frozen=True)
class EmotionalDynamicsScore:
    """Vocal expressiveness — pitch, energy, rhythm variance across sections."""

    pitch_cv: float
    rms_contrast: float
    onset_rate_cv: float
    overall_expressiveness: float


@dataclass(frozen=True)
class AudioBoxScore:
    """Meta AudioBox Aesthetics — four quality dimensions (1-10 each)."""

    content_enjoyment: float
    content_understanding: float
    production_complexity: float
    production_quality: float


@dataclass(frozen=True)
class BpmAccuracyScore:
    """Detected vs requested BPM. Informational — not a quality indicator."""

    detected_bpm: float
    requested_bpm: int
    deviation_percent: float
    octave_corrected: bool


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


@dataclass(frozen=True)
class SongScores:
    """Aggregated results from all scorers.

    No overall score — individual metrics serve different purposes:
    - silence: pass/fail flag (problematic gaps?)
    - bpm_accuracy: informational (what BPM was detected?)
    - emotional_dynamics: relative comparison (sort versions, listen to top N)
    - text_accuracy: quality signal (did the model sing the right words?)
    - audiobox: quality signal (production quality from Meta's model)
    """

    text_accuracy: TextAccuracyScore | None = None
    emotional_dynamics: EmotionalDynamicsScore | None = None
    audiobox: AudioBoxScore | None = None
    bpm_accuracy: BpmAccuracyScore | None = None
    silence: SilenceScore | None = None

    def to_dict(self) -> dict[str, object]:
        """Structured dict for snapshot persistence.

        Returns empty dict if no scorers produced results.
        """
        result: dict[str, object] = {}

        if self.emotional_dynamics:
            result["dynamics"] = round(min(self.emotional_dynamics.overall_expressiveness * 100, 100.0), 1)
            result["dynamics_pitch_cv"] = self.emotional_dynamics.pitch_cv
            result["dynamics_rms_contrast"] = self.emotional_dynamics.rms_contrast
            result["dynamics_onset_cv"] = self.emotional_dynamics.onset_rate_cv

        if self.text_accuracy:
            result["text_accuracy"] = round(self.text_accuracy.similarity_ratio * 100, 1)

        if self.audiobox:
            result["audiobox_enjoyment"] = self.audiobox.content_enjoyment
            result["audiobox_quality"] = self.audiobox.production_quality

        if self.bpm_accuracy:
            result["bpm_detected"] = self.bpm_accuracy.detected_bpm
            result["bpm_deviation"] = self.bpm_accuracy.deviation_percent

        if self.silence:
            result["silence_gaps"] = self.silence.gap_count
            result["silence_longest"] = self.silence.longest_gap_seconds
            result["silence_ok"] = not self.silence.has_problems

        return result
