"""Resolve stored audio paths without exposing the server's filesystem."""

from __future__ import annotations

import logging
from pathlib import Path, PurePosixPath

log = logging.getLogger(__name__)


class AudioPathRejectedError(Exception):
    """The path escapes the audio root or is not in canonical form."""


class AudioFileNotFoundError(FileNotFoundError):
    """The stored audio file is no longer present on disk."""


def _resolved_audio_root(audio_dir: Path) -> Path:
    return audio_dir.resolve()


def confined_under(root: Path, path: Path) -> Path | None:
    """Return ``path`` resolved when it lies strictly below the resolved ``root``.

    The root may itself be a symlink or a mount; a path counts where it resolves.
    The root itself is not below it.
    """
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_path == resolved_root or not resolved_path.is_relative_to(resolved_root):
        return None
    return resolved_path


def _resolved_within_root(audio_dir: Path, filename: str) -> Path | None:
    """Resolve ``filename`` and return it only when it stays below the root."""
    return confined_under(audio_dir, audio_dir / filename)


def require_canonical_audio_filename(filename: str) -> None:
    """Require a canonical relative filename without inspecting the filesystem."""
    audio_path = PurePosixPath(filename)
    canonical_filename = audio_path.as_posix()
    if (
        audio_path.is_absolute()
        or ".." in audio_path.parts
        or canonical_filename != filename
    ):
        log.warning("non-canonical audio path rejected")
        raise AudioPathRejectedError("audio path is not in canonical form")


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
        log.warning("Audio path traversal denied")
        raise AudioPathRejectedError("audio path escapes the audio root")
    if not audio_path.exists():
        raise AudioFileNotFoundError(relative_path)
    return audio_path


def canonical_audio_path(audio_dir: Path, filename: str) -> Path:
    """Return a canonical audio path constrained to ``audio_dir``."""
    audio_path = _resolved_within_root(audio_dir, filename)
    if audio_path is None:
        log.warning("Audio path traversal denied")
        raise AudioPathRejectedError("audio path escapes the audio root")
    if audio_path.relative_to(_resolved_audio_root(audio_dir)).as_posix() != filename:
        log.warning("non-canonical audio path rejected")
        raise AudioPathRejectedError("audio path is not in canonical form")
    return audio_path


def require_existing_audio_path(audio_path: Path) -> Path:
    """Return ``audio_path`` when its file still exists."""
    if not audio_path.exists():
        raise AudioFileNotFoundError(str(audio_path))
    return audio_path
