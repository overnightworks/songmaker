"""Declarative scorer registry — single source of truth for scorer identity.

Drives:
- @register decorator validation in pipeline.py
- needs_audio / device / after_gpu metadata for the pipeline scheduler
- output_keys for SongScores.to_dict()
- VALID_SCORER_NAMES used by ScoreRequest validation
- /scoring/schema API endpoint
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

DEVICE_CPU: Final[str] = "cpu"
DEVICE_GPU: Final[str] = "gpu"

# Named because its time budget is configured separately — a cold Whisper
# model load counts against it (see PipelineConfig.timeout_for).
TEXT_ACCURACY_SCORER: Final[str] = "text_accuracy"


@dataclass(frozen=True)
class ScorerSpec:
    name: str
    output_keys: tuple[str, ...]
    needs_audio: bool = True
    device: str = DEVICE_CPU
    after_gpu: bool = False


SCORERS: dict[str, ScorerSpec] = {
    TEXT_ACCURACY_SCORER: ScorerSpec(
        name=TEXT_ACCURACY_SCORER,
        output_keys=("text_accuracy", "detected_language"),
        needs_audio=False,
        device=DEVICE_CPU,
    ),
    "lyrical_coherence": ScorerSpec(
        name="lyrical_coherence",
        output_keys=("lyrical_coherence", "lyrical_summary"),
        needs_audio=False,
        after_gpu=True,
    ),
    "emotional_dynamics": ScorerSpec(
        name="emotional_dynamics",
        output_keys=(
            "dynamics",
            "dynamics_pitch_cv",
            "dynamics_rms_contrast",
            "dynamics_onset_cv",
        ),
    ),
    "audiobox": ScorerSpec(
        name="audiobox",
        output_keys=(
            "audiobox_enjoyment",
            "audiobox_understanding",
            "audiobox_complexity",
            "audiobox_quality",
        ),
        needs_audio=False,
        device=DEVICE_GPU,
    ),
    "bpm_accuracy": ScorerSpec(
        name="bpm_accuracy",
        output_keys=("bpm_detected", "bpm_deviation"),
    ),
    "silence": ScorerSpec(
        name="silence",
        output_keys=("silence_gaps", "silence_longest"),
    ),
    "spectral_quality": ScorerSpec(
        name="spectral_quality",
        output_keys=("spectral_artifacts",),
    ),
}

VALID_SCORER_NAMES: frozenset[str] = frozenset(SCORERS.keys())
