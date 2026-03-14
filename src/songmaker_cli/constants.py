"""Non-model constants for the songmaker CLI."""

from __future__ import annotations

import datetime

OUTPUT_ROOT = "_output"
DEFAULT_ARTIST = "Flex0r"
DEFAULT_YEAR = str(datetime.date.today().year)
NORMALIZE_PEAK = 0.95

SIMILARITY_GOOD = 0.8
SIMILARITY_FAIR = 0.5
