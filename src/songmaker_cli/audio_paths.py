"""Resolve stored audio paths without exposing the server's filesystem."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import HTTPException

log = logging.getLogger(__name__)


def resolve_audio_path(audio_dir: Path, relative_path: str) -> Path:
    """Return an existing audio file constrained to ``audio_dir``."""
    audio_root = audio_dir.resolve()
    audio_path = (audio_root / relative_path).resolve()
    if not audio_path.is_relative_to(audio_root):
        log.warning("Audio path traversal denied: %r", relative_path)
        raise HTTPException(404, "Not Found")
    if not audio_path.exists():
        raise HTTPException(404, "Not Found")
    return audio_path
