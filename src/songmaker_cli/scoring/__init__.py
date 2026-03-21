"""Scoring pipeline for automated song quality assessment."""

from songmaker_cli.scoring.models import SongScores
from songmaker_cli.scoring.pipeline import available_scorers, register, run_scoring_pipeline

# Import scorer modules to trigger @register decorators
import songmaker_cli.scoring.bpm_accuracy as _bpm  # noqa: F401
import songmaker_cli.scoring.emotional_dynamics as _dynamics  # noqa: F401
import songmaker_cli.scoring.silence_detection as _silence  # noqa: F401

__all__ = [
    "SongScores",
    "available_scorers",
    "register",
    "run_scoring_pipeline",
]
