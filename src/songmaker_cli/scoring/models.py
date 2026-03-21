"""Score dataclasses for the scoring pipeline."""

from __future__ import annotations

from dataclasses import dataclass

# Snapshot serialization keys — used by to_dict() and read back by manifest.read_scores().
# Player SCORE_LABELS must match these keys.
SCORE_KEY_DYNAMICS = "dynamics"
SCORE_KEY_DYNAMICS_PITCH_CV = "dynamics_pitch_cv"
SCORE_KEY_DYNAMICS_RMS_CONTRAST = "dynamics_rms_contrast"
SCORE_KEY_DYNAMICS_ONSET_CV = "dynamics_onset_cv"
SCORE_KEY_TEXT_ACCURACY = "text_accuracy"
SCORE_KEY_AUDIOBOX_ENJOYMENT = "audiobox_enjoyment"
SCORE_KEY_AUDIOBOX_UNDERSTANDING = "audiobox_understanding"
SCORE_KEY_AUDIOBOX_COMPLEXITY = "audiobox_complexity"
SCORE_KEY_AUDIOBOX_QUALITY = "audiobox_quality"
SCORE_KEY_BPM_DETECTED = "bpm_detected"
SCORE_KEY_BPM_DEVIATION = "bpm_deviation"
SCORE_KEY_SILENCE_GAPS = "silence_gaps"
SCORE_KEY_SILENCE_LONGEST = "silence_longest"
SCORE_KEY_SILENCE_OK = "silence_ok"


@dataclass(frozen=True)
class TextAccuracyScore:
    """Whisper transcription vs intended lyrics."""

    similarity_ratio: float
    intended_line_texts: tuple[str, ...]
    transcribed_line_texts: tuple[str, ...]

    @property
    def intended_lines(self) -> int:
        return len(self.intended_line_texts)

    @property
    def transcribed_lines(self) -> int:
        return len(self.transcribed_line_texts)


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
            result[SCORE_KEY_DYNAMICS] = round(min(self.emotional_dynamics.overall_expressiveness * 100, 100.0), 1)
            result[SCORE_KEY_DYNAMICS_PITCH_CV] = self.emotional_dynamics.pitch_cv
            result[SCORE_KEY_DYNAMICS_RMS_CONTRAST] = self.emotional_dynamics.rms_contrast
            result[SCORE_KEY_DYNAMICS_ONSET_CV] = self.emotional_dynamics.onset_rate_cv

        if self.text_accuracy:
            result[SCORE_KEY_TEXT_ACCURACY] = round(self.text_accuracy.similarity_ratio * 100, 1)

        if self.audiobox:
            result[SCORE_KEY_AUDIOBOX_ENJOYMENT] = self.audiobox.content_enjoyment
            result[SCORE_KEY_AUDIOBOX_UNDERSTANDING] = self.audiobox.content_understanding
            result[SCORE_KEY_AUDIOBOX_COMPLEXITY] = self.audiobox.production_complexity
            result[SCORE_KEY_AUDIOBOX_QUALITY] = self.audiobox.production_quality

        if self.bpm_accuracy:
            result[SCORE_KEY_BPM_DETECTED] = self.bpm_accuracy.detected_bpm
            result[SCORE_KEY_BPM_DEVIATION] = self.bpm_accuracy.deviation_percent

        if self.silence:
            result[SCORE_KEY_SILENCE_GAPS] = self.silence.gap_count
            result[SCORE_KEY_SILENCE_LONGEST] = self.silence.longest_gap_seconds
            result[SCORE_KEY_SILENCE_OK] = not self.silence.has_problems

        return result
