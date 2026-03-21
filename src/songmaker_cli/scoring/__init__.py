"""Scoring pipeline for automated song quality assessment."""

from songmaker_cli.scoring.models import SongScores
from songmaker_cli.scoring.pipeline import (
    ScorerRegistry,
    available_scorers,
    default_registry,
    register,
    run_scoring_pipeline,
)

__all__ = [
    "ScorerRegistry",
    "SongScores",
    "available_scorers",
    "default_registry",
    "register",
    "run_scoring_pipeline",
]
