"""Non-model constants for the songmaker CLI."""

from __future__ import annotations

import datetime

OUTPUT_ROOT = "_output"
DEFAULT_ARTIST = "Flex0r"
SIMILARITY_GOOD = 0.8
SIMILARITY_FAIR = 0.5

# Scoring pipeline
SILENCE_LONGEST_GAP_PENALTY = 10.0
SILENCE_LONGEST_GAP_MAX_PENALTY = 50.0
SILENCE_GAP_COUNT_PENALTY = 5.0
SILENCE_GAP_COUNT_MAX_PENALTY = 30.0
BPM_DEVIATION_PENALTY = 5.0


def default_year() -> str:
    return str(datetime.date.today().year)
