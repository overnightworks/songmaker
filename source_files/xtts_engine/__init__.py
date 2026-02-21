"""XTTS v2 text-to-speech engine (isolated venv).

Provides high-quality speech synthesis with voice cloning via Coqui XTTS v2.
Best for spoken, whispered, and rap vocals. Cannot sing — use Bark for that.

Runs in an isolated Python 3.12 venv to avoid dependency conflicts.
"""

from xtts_engine.converter import XTTSConverter, is_xtts_available

__all__ = ["XTTSConverter", "is_xtts_available"]
