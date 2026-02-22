"""ACE-Step vocal engine for Songmaker.

Generates singing vocals via ACE-Step 1.5 (text-to-music AI). Runs as
a REST API client talking to an ACE-Step server on localhost:8001.

The server runs in a separate Python venv (.venv-acestep) because
ACE-Step pins a different torch version than Songmaker.

Typical workflow:
    1. ACE-Step generates a full mix (vocals + instruments)
    2. Demucs separates out the vocal stem
    3. Optionally RVC converts the voice timbre
    4. Songmaker mixes the vocals onto its own instrumentals

Setup:
    python scripts/setup_acestep.py   # Clone, install, download models
    python scripts/start_acestep.py   # Launch API server on port 8001

Usage:
    from acestep_engine import AceStepClient, AceStepConfig

    client = AceStepClient()
    result = client.generate(AceStepConfig(
        prompt="female vocal, emotional ballad, piano",
        lyrics="[verse]\\nIf I should stay...",
        bpm=72,
        duration=30,
    ))
"""

from acestep_engine.client import AceStepClient, is_acestep_available
from acestep_engine.models import AceStepConfig, AceStepResult

__all__ = [
    "AceStepClient",
    "AceStepConfig",
    "AceStepResult",
    "is_acestep_available",
]
