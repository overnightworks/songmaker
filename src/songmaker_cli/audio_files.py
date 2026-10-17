"""Read facts from stored audio files."""

from __future__ import annotations

from pathlib import Path


def read_audio_duration(audio_path: Path) -> float | None:
    """Read a file's real length in seconds, or None if it can't be read.

    Pure: no HTTP dependency, no request-boundary shape. Safe to call from
    any layer, including a background job or the DB query layer.
    """
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(audio_path)
        if audio is None:
            return None
        length = float(audio.info.length)
    except Exception:
        return None
    return length if length > 0 else None
