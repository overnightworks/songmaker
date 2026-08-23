"""Declarative scorer registry — single source of truth for scorer identity.

Drives:
- @register decorator validation in pipeline.py
- needs_audio / device metadata for the child's pipeline scheduler
- host: which process runs a scorer (see ScorerHost)
- output_keys for SongScores.to_dict()
- VALID_SCORER_NAMES used by ScoreRequest validation
- /scoring/schema API endpoint
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

DEVICE_CPU: Final[str] = "cpu"
DEVICE_GPU: Final[str] = "gpu"

# Named because its time budget is configured separately — a cold Whisper
# model load counts against it (see PipelineConfig.timeout_for).
TEXT_ACCURACY_SCORER: Final[str] = "text_accuracy"

# Named because the worker parent runs it itself, on the result the scorer
# child returned (see ScorerHost and jobs/scoring.py).
LYRICAL_COHERENCE_SCORER: Final[str] = "lyrical_coherence"


class ScorerHost(StrEnum):
    """Which process runs a scorer.

    The scorer child loads third-party model weights and is spawned without
    any secret in its environment, so a scorer that calls an external
    service runs in the worker parent instead — on the result the child
    already returned.
    """

    CHILD = "child"
    PARENT = "parent"


@dataclass(frozen=True)
class ScorerSpec:
    name: str
    output_keys: tuple[str, ...]
    needs_audio: bool = True
    device: str = DEVICE_CPU
    host: ScorerHost = ScorerHost.CHILD
    # Consumes another scorer's output, so it can only run once that scorer
    # is done. Reported by /scoring/schema; see the invariant below.
    after_gpu: bool = False


SCORERS: dict[str, ScorerSpec] = {
    TEXT_ACCURACY_SCORER: ScorerSpec(
        name=TEXT_ACCURACY_SCORER,
        output_keys=("text_accuracy", "detected_language"),
        needs_audio=False,
        device=DEVICE_CPU,
    ),
    LYRICAL_COHERENCE_SCORER: ScorerSpec(
        name=LYRICAL_COHERENCE_SCORER,
        output_keys=("lyrical_coherence", "lyrical_summary"),
        needs_audio=False,
        host=ScorerHost.PARENT,
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

CHILD_SCORER_NAMES: frozenset[str] = frozenset(
    name for name, spec in SCORERS.items() if spec.host is ScorerHost.CHILD
)

assert all(spec.host is ScorerHost.PARENT for spec in SCORERS.values() if spec.after_gpu), (
    "a scorer that consumes another scorer's output runs in the parent, on the "
    "result the child returned — the child itself schedules no second phase"
)
