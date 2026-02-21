"""Demucs stem separation engine.

Splits audio into 4 stems: vocals, drums, bass, other.
Enables the hybrid workflow — generate with MusicGen, separate
into stems, remix with your own mastering chain.
"""

from stem_separator.demucs_separator import DemucsSeparator, is_demucs_available

__all__ = ["DemucsSeparator", "is_demucs_available"]
