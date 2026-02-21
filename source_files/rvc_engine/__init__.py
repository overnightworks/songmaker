"""RVC (Retrieval-based Voice Conversion) engine for Songmaker.

Converts Bark vocal output through a trained voice model to produce
natural-sounding vocals.

Public API:
    - RVCConverter: Voice conversion via rvc-python
    - is_rvc_available: Check if RVC is installed and ready

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
