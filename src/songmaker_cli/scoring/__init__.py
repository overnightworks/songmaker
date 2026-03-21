"""Scoring pipeline for automated song quality assessment."""

from songmaker_cli.scoring.models import SongScores
from songmaker_cli.scoring.pipeline import available_scorers, register, run_scoring_pipeline

__all__ = [
    "SongScores",
    "available_scorers",
    "register",
    "run_scoring_pipeline",
]
