"""Bark-based singing vocal engine for MC Tobbisch Birthday Album.

Package providing AI singing vocal generation using Bark (by Suno),
replacing edge-tts speech synthesis with actual singing voices.

Multi-take selection is the default behavior: each VocalSection
generates num_takes candidates (default 3), scores them on quality
metrics, and auto-selects the best one.

Pitch correction is enabled by default at 70% intensity in C minor.
Detects pitch via autocorrelation and quantizes to the target scale
using PSOLA resynthesis for artifact-free correction.

Public API:
    - BarkVocalEngine: Core engine for generating singing vocals
    - VocalSection: Immutable configuration for a vocal section
    - VocalStyle: Enum for vocal processing styles
    - VocalLanguage: Supported voice languages
    - GeneratedVocal: Result container for generated audio
    - TakeScore: Quality metrics for a single vocal take
    - score_vocal_take: Score a single take on quality metrics
    - select_best_take: Select the highest-scoring take
    - apply_pitch_correction: Pitch correction pipeline
    - get_scale_notes: Get note names in a scale
    - freq_to_midi: Frequency to MIDI conversion
    - midi_to_freq: MIDI to frequency conversion

Usage:
    from bark_engine import BarkVocalEngine, VocalSection, VocalStyle

    engine = BarkVocalEngine()
    engine.preload_models()
    vocals = engine.generate_vocals([
        VocalSection(section_id="chorus", text="Happy Birthday!", singing=True),
    ])
    engine.cleanup()
"""

from bark_engine.audio_io import (
    apply_fade_out,
    calculate_vocal_durations,
    master_to_mp3,
    mix_tracks,
    normalize_audio,
    overlay_audio,
    read_wav_file,
    write_wav_file,
)
from bark_engine.constants import BARK_SAMPLE_RATE, TARGET_SAMPLE_RATE
from bark_engine.engine import BarkVocalEngine
from bark_engine.models import (
    GeneratedVocal,
    VocalLanguage,
    VocalSection,
    VocalStyle,
)
from bark_engine.pitch_correction import (
    apply_pitch_correction,
    freq_to_midi,
    get_scale_notes,
    midi_to_freq,
)
from bark_engine.take_selection import TakeScore, score_vocal_take, select_best_take

__all__ = [
    "BarkVocalEngine",
    "VocalSection",
    "VocalStyle",
    "VocalLanguage",
    "GeneratedVocal",
    "TakeScore",
    "score_vocal_take",
    "select_best_take",
    "BARK_SAMPLE_RATE",
    "TARGET_SAMPLE_RATE",
    "write_wav_file",
    "read_wav_file",
    "normalize_audio",
    "overlay_audio",
    "mix_tracks",
    "apply_fade_out",
    "calculate_vocal_durations",
    "master_to_mp3",
    "apply_pitch_correction",
    "get_scale_notes",
    "freq_to_midi",
    "midi_to_freq",
]
