"""Scoring pipeline — registry, runner, and orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, fields
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import numpy as np

from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import SongScores

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioData:
    """Pre-loaded audio shared across scorers to avoid redundant decoding."""

    audio: np.ndarray
    sr: int


PipelineConfig = dict[str, object]

ScorerFunc = Callable[[Path, SongMeta | None, AudioData | None, PipelineConfig], object]

_VALID_SCORER_NAMES = frozenset(f.name for f in fields(SongScores))
_SCORERS: dict[str, ScorerFunc] = {}


def register(name: str) -> Callable[[ScorerFunc], ScorerFunc]:
    """Decorator to register a scorer function.

    The name must match a field on SongScores (e.g. "silence", "bpm_accuracy").
    """

    def decorator(func: ScorerFunc) -> ScorerFunc:
        if name not in _VALID_SCORER_NAMES:
            raise ValueError(
                f"Scorer name '{name}' does not match any SongScores field. "
                f"Valid names: {sorted(_VALID_SCORER_NAMES)}"
            )
        _SCORERS[name] = func
        return func

    return decorator


def available_scorers() -> list[str]:
    """Return names of all registered scorers."""
    _ensure_scorers_registered()
    return list(_SCORERS.keys())


def load_audio(mp3_path: Path) -> AudioData:
    """Load and resample audio once for all scorers."""
    import librosa

    from songmaker_cli.constants import SCORING_SAMPLE_RATE

    audio, sr = librosa.load(mp3_path, sr=SCORING_SAMPLE_RATE, mono=True)
    return AudioData(audio=audio, sr=sr)


_scorers_loaded = False


def _ensure_scorers_registered() -> None:
    """Lazily import scorer modules to trigger @register decorators."""
    global _scorers_loaded
    if _scorers_loaded:
        return
    _scorers_loaded = True
    import songmaker_cli.scoring.audiobox_aesthetics  # noqa: F401
    import songmaker_cli.scoring.bpm_accuracy  # noqa: F401
    import songmaker_cli.scoring.emotional_dynamics  # noqa: F401
    import songmaker_cli.scoring.silence_detection  # noqa: F401
    import songmaker_cli.scoring.text_accuracy  # noqa: F401


def run_scoring_pipeline(
    mp3_path: Path,
    meta: SongMeta | None = None,
    scorers: list[str] | None = None,
    config: PipelineConfig | None = None,
) -> SongScores:
    """Run all (or selected) scorers on an MP3 and return aggregated scores.

    Audio is loaded once and shared across all scorers.
    Each scorer runs independently — one failure does not block others.
    Config dict is passed to all scorers for scorer-specific settings
    (e.g. {"whisper_model": "large-v3"}).
    """
    _ensure_scorers_registered()
    if scorers is None:
        scorers = list(_SCORERS.keys())
    if config is None:
        config = {}

    audio_data = load_audio(mp3_path)

    results: dict[str, object] = {}
    for name in scorers:
        if name not in _SCORERS:
            log.warning("Unknown scorer: %s (available: %s)", name, ", ".join(_SCORERS))
            continue
        try:
            log.info("Running scorer: %s", name)
            results[name] = _SCORERS[name](mp3_path, meta, audio_data, config)
        except Exception:
            log.exception("Scorer '%s' failed", name)

    return SongScores(
        text_accuracy=results.get("text_accuracy"),  # type: ignore[arg-type]
        emotional_dynamics=results.get("emotional_dynamics"),  # type: ignore[arg-type]
        audiobox=results.get("audiobox"),  # type: ignore[arg-type]
        bpm_accuracy=results.get("bpm_accuracy"),  # type: ignore[arg-type]
        silence=results.get("silence"),  # type: ignore[arg-type]
    )
