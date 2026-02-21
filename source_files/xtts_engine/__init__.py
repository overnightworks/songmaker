"""XTTS v2 text-to-speech engine.

Provides high-quality speech synthesis with voice cloning via Coqui XTTS v2.
Best for spoken, whispered, and rap vocals. Cannot sing — use Bark for that.
"""

from xtts_engine.converter import XTTSConverter, is_xtts_available

__all__ = ["XTTSConverter", "is_xtts_available"]
