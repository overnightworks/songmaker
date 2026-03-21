"""Scoring pipeline — registry, runner, and orchestration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from songmaker_cli.parser import SongMeta
from songmaker_cli.scoring.models import SongScores

log = logging.getLogger(__name__)

ScorerFunc = Callable[..., object]

_SCORERS: dict[str, ScorerFunc] = {}


def register(name: str) -> Callable[[ScorerFunc], ScorerFunc]:
    """Decorator to register a scorer function."""

    def decorator(func: ScorerFunc) -> ScorerFunc:
        _SCORERS[name] = func
        return func

    return decorator


def available_scorers() -> list[str]:
    """Return names of all registered scorers."""
    return list(_SCORERS.keys())


def run_scoring_pipeline(
    mp3_path: Path,
    meta: SongMeta | None = None,
    scorers: list[str] | None = None,
) -> SongScores:
    """Run all (or selected) scorers on an MP3 and return aggregated scores.

    Each scorer runs independently — one failure does not block others.
    """
    if scorers is None:
        scorers = list(_SCORERS.keys())

    results: dict[str, object] = {}
    for name in scorers:
        if name not in _SCORERS:
            log.warning("Unknown scorer: %s (available: %s)", name, ", ".join(_SCORERS))
            continue
        try:
            log.info("Running scorer: %s", name)
            results[name] = _SCORERS[name](mp3_path=mp3_path, meta=meta)
        except Exception:
            log.exception("Scorer '%s' failed", name)

    return SongScores(
        text_accuracy=results.get("text_accuracy"),  # type: ignore[arg-type]
        emotional_dynamics=results.get("emotional_dynamics"),  # type: ignore[arg-type]
        audiobox=results.get("audiobox"),  # type: ignore[arg-type]
        bpm_accuracy=results.get("bpm_accuracy"),  # type: ignore[arg-type]
        silence=results.get("silence"),  # type: ignore[arg-type]
    )
