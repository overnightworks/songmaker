"""Audio engine constants."""

from __future__ import annotations

from typing import Final

FALLBACK_SAMPLE_RATE: Final[int] = 48000
INT16_MAX: Final[float] = 32768.0

# ── Mastering chain tuning parameters ────────────────────────────────

DEFAULT_TARGET_LUFS: Final[float] = -14.0
DEFAULT_STEREO_WIDTH: Final[float] = 1.2
DEFAULT_SOFT_CLIP_CEILING: Final[float] = 0.98
DEFAULT_CROSSOVER_BANDS: Final[tuple[tuple[float, float], ...]] = (
    (20.0, 250.0),
    (250.0, 4000.0),
    (4000.0, 20000.0),
)
DEFAULT_COMPRESSION_RATIOS: Final[tuple[float, ...]] = (3.0, 2.5, 2.0)
DEFAULT_COMPRESSION_THRESHOLDS: Final[tuple[float, ...]] = (0.5, 0.6, 0.7)
BUTTER_ORDER: Final[int] = 4
COMPRESSOR_ATTACK_SECONDS: Final[float] = 0.005
COMPRESSOR_RELEASE_SECONDS: Final[float] = 0.05
MIN_RMS_FLOOR: Final[float] = 1e-10
MAX_GAIN_DB: Final[float] = 24.0
SOFT_CLIP_KNEE: Final[float] = 0.85
CHANNEL_LENGTH_TOLERANCE: Final[int] = 16

# ── Pre-EQ tuning parameters ───────────────────────────────────────
EQ_MUD_CENTER_HZ: Final[float] = 350.0
EQ_MUD_Q: Final[float] = 1.0
EQ_MUD_GAIN_DB: Final[float] = -3.0
EQ_AIR_SHELF_HZ: Final[float] = 10000.0
EQ_AIR_GAIN_DB: Final[float] = 2.0
