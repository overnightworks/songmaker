"""RVC (Retrieval-based Voice Conversion) engine for Songmaker.

Converts Bark vocal output through a trained voice model to produce
natural-sounding vocals. Runs in an isolated Python 3.12 venv to
avoid dependency conflicts with the main Python 3.14 environment.

Public API:
    - RVCConverter: Voice conversion with auto-detection of venv
    - is_rvc_available: Check if RVC is installed and ready
    - setup_rvc_venv: Install RVC in an isolated venv

Usage:
    from rvc_engine import RVCConverter, is_rvc_available

    if is_rvc_available():
        converter = RVCConverter(model_name="male_singer_v2")
        output_samples = converter.convert("input.wav", "output.wav")
"""

from rvc_engine.converter import RVCConverter, is_rvc_available

__all__ = [
    "RVCConverter",
    "is_rvc_available",
]
