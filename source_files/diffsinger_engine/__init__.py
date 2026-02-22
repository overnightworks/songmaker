"""DiffSinger singing voice synthesis engine.

Generates isolated singing vocals from MIDI notes + lyrics using
DiffSinger ONNX models (e.g. TIGER English voicebank).

Usage:
    from diffsinger_engine import DiffSingerEngine, VocalNote, VocalPhrase

    phrase = VocalPhrase(
        phrase_id="verse_1",
        bpm=120,
        notes=(
            VocalNote(midi=60, lyric="hel", duration_beats=1.0),
            VocalNote(midi=60, lyric="lo", duration_beats=1.0),
            VocalNote(midi=64, lyric="world", duration_beats=2.0),
        ),
    )

    engine = DiffSingerEngine(voicebank_dir="_diffsinger/checkpoints/tiger")
    result = engine.generate(phrase)
"""

from .engine import DiffSingerEngine
from .models import DiffSingerResult, VocalNote, VocalPhrase

__all__ = [
    "DiffSingerEngine",
    "DiffSingerResult",
    "VocalNote",
    "VocalPhrase",
]
