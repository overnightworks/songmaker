"""Scoring pipeline — registry, runner, and orchestration."""

from __future__ import annotations

import logging
import signal
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


SCORER_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class PipelineConfig:
    """Configuration passed to all scorers."""

    whisper_model: str = "medium"
    scorer_timeout: int = SCORER_TIMEOUT_SECONDS


ScorerFunc = Callable[[Path, SongMeta | None, AudioData | None, PipelineConfig], object]

_VALID_SCORER_NAMES = frozenset(f.name for f in fields(SongScores))
_SCORERS: dict[str, ScorerFunc] = {}


_SCORERS_NEEDS_AUDIO: dict[str, bool] = {}


def register(name: str, needs_audio: bool = True) -> Callable[[ScorerFunc], ScorerFunc]:
    """Decorator to register a scorer function.

    The name must match a field on SongScores (e.g. "silence", "bpm_accuracy").
    Set needs_audio=False for scorers that use file paths (e.g. Whisper, AudioBox).
    """

    def decorator(func: ScorerFunc) -> ScorerFunc:
        if name not in _VALID_SCORER_NAMES:
            raise ValueError(
                f"Scorer name '{name}' does not match any SongScores field. "
                f"Valid names: {sorted(_VALID_SCORER_NAMES)}"
            )
        _SCORERS[name] = func
        _SCORERS_NEEDS_AUDIO[name] = needs_audio
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


class _ScorerTimeout(Exception):
    """Raised when a scorer exceeds its time limit."""


def _run_with_timeout(
    func: ScorerFunc, mp3_path: Path, meta: SongMeta | None,
    audio_data: AudioData | None, config: PipelineConfig,
    timeout: int, name: str,
) -> object:
    """Run a scorer with a timeout. Uses SIGALRM on Linux."""
    if timeout <= 0 or not hasattr(signal, "SIGALRM"):
        return func(mp3_path, meta, audio_data, config)

    def _handler(signum: int, frame: object) -> None:
        raise _ScorerTimeout(f"Scorer '{name}' timed out after {timeout}s")

    old_handler = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(timeout)
    try:
        result = func(mp3_path, meta, audio_data, config)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
    return result


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
    """
    _ensure_scorers_registered()
    if scorers is None:
        scorers = list(_SCORERS.keys())
    if config is None:
        config = PipelineConfig()

    any_needs_audio = any(_SCORERS_NEEDS_AUDIO.get(s, True) for s in scorers if s in _SCORERS)
    audio_data = load_audio(mp3_path) if any_needs_audio else None

    results: dict[str, object] = {}
    for name in scorers:
        if name not in _SCORERS:
            log.warning("Unknown scorer: %s (available: %s)", name, ", ".join(_SCORERS))
            continue
        try:
            log.info("Running scorer: %s", name)
            results[name] = _run_with_timeout(
                _SCORERS[name], mp3_path, meta, audio_data, config,
                timeout=config.scorer_timeout, name=name,
            )
        except Exception:
            log.exception("Scorer '%s' failed", name)

    return SongScores(
        text_accuracy=results.get("text_accuracy"),  # type: ignore[arg-type]
        emotional_dynamics=results.get("emotional_dynamics"),  # type: ignore[arg-type]
        audiobox=results.get("audiobox"),  # type: ignore[arg-type]
        bpm_accuracy=results.get("bpm_accuracy"),  # type: ignore[arg-type]
        silence=results.get("silence"),  # type: ignore[arg-type]
    )
