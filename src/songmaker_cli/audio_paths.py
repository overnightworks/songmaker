"""Resolve stored audio paths without exposing the server's filesystem."""

from __future__ import annotations

import logging
from pathlib import Path, PurePosixPath

from fastapi import HTTPException

log = logging.getLogger(__name__)


class AudioFileNotFoundError(FileNotFoundError):
    """The stored audio file is no longer present on disk."""


def _resolved_audio_root(audio_dir: Path) -> Path:
    return audio_dir.resolve()


def _resolved_within_root(audio_dir: Path, filename: str) -> Path | None:
    """Resolve ``filename`` and return it only when it stays below the root."""
    audio_root = _resolved_audio_root(audio_dir)
    audio_path = (audio_root / filename).resolve()
    if not audio_path.is_relative_to(audio_root):
        return None
    return audio_path


def require_canonical_audio_filename(filename: str) -> None:
    """Require a canonical relative filename without inspecting the filesystem."""
    audio_path = PurePosixPath(filename)
    canonical_filename = audio_path.as_posix()
    if (
        audio_path.is_absolute()
        or ".." in audio_path.parts
        or canonical_filename != filename
    ):
        log.warning("non-canonical audio path rejected: %r", filename)
        raise HTTPException(404, "Not Found")


def audio_filename_is_contained(audio_dir: Path, filename: str) -> bool:
    """Whether resolving ``filename`` keeps it inside ``audio_dir``."""
    return _resolved_within_root(audio_dir, filename) is not None


def canonical_audio_filename(audio_dir: Path, filename: str) -> str | None:
    """Return the root-relative canonical filename, or ``None`` if it escapes."""
    audio_path = _resolved_within_root(audio_dir, filename)
    if audio_path is None:
        return None
    return audio_path.relative_to(_resolved_audio_root(audio_dir)).as_posix()


def resolve_audio_path(audio_dir: Path, relative_path: str) -> Path:
    """Return an existing audio file constrained to ``audio_dir``."""
    audio_path = _resolved_within_root(audio_dir, relative_path)
    if audio_path is None:
        log.warning("Audio path traversal denied: %r", relative_path)
        raise HTTPException(404, "Not Found")
    if not audio_path.exists():
        raise AudioFileNotFoundError(relative_path)
    return audio_path


def canonical_audio_path(audio_dir: Path, filename: str) -> Path:
    """Return a canonical audio path constrained to ``audio_dir``."""
    audio_path = _resolved_within_root(audio_dir, filename)
    if audio_path is None:
        log.warning("Audio path traversal denied: %r", filename)
        raise HTTPException(404, "Not Found")
    if audio_path.relative_to(_resolved_audio_root(audio_dir)).as_posix() != filename:
        log.warning("non-canonical audio path rejected: %r", filename)
        raise HTTPException(404, "Not Found")
    return audio_path


def require_existing_audio_path(audio_path: Path) -> Path:
    """Return ``audio_path`` when its file still exists."""
    if not audio_path.exists():
        raise AudioFileNotFoundError(str(audio_path))
    return audio_path
