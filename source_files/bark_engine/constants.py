"""Constants for the Bark vocal engine."""

from __future__ import annotations

from typing import Final

BARK_SAMPLE_RATE: Final[int] = 24000
TARGET_SAMPLE_RATE: Final[int] = 44100
TEMP_DIR_NAME: Final[str] = "_temp_bark"

MAX_CHUNK_LENGTH: Final[int] = 120
SENTENCE_DELIMITERS: Final[tuple[str, ...]] = (".", "!", "?", ",", ";")
