"""The sentences a refused cover is answered with."""

from __future__ import annotations

from typing import Final

COVER_UNSUPPORTED_TYPE: Final = "Cover must be a JPEG or PNG image"
COVER_TOO_LARGE: Final = "Cover file is too large"
COVER_TOO_MANY_PIXELS: Final = "Cover image is too large"
COVER_VARIANT_UNKNOWN: Final = "Unknown cover variant"
