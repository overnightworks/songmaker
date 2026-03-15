"""Non-model constants for the songmaker CLI."""

from __future__ import annotations

import datetime

OUTPUT_ROOT = "_output"
DEFAULT_ARTIST = "Flex0r"
SIMILARITY_GOOD = 0.8
SIMILARITY_FAIR = 0.5


def default_year() -> str:
    return str(datetime.date.today().year)
