"""Owner-scoped reference-audio path resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from songmaker_cli.constants import REFERENCE_AUDIO_DIR, REFERENCE_AUDIO_EXTENSIONS

REFERENCE_AUDIO_NOT_OWNED_DETAIL: Final = "reference audio path is not owned"


class ReferenceAudioRejected(ValueError):
    pass


def owner_reference_audio_root(audio_dir: Path, user_id: str) -> Path:
    return audio_dir / user_id / REFERENCE_AUDIO_DIR


def resolve_owned_reference_audio(
    audio_dir: Path, user_id: str, stored_relative: str,
) -> Path:
    if not stored_relative or stored_relative.startswith("/") or ".." in stored_relative:
        raise ReferenceAudioRejected(REFERENCE_AUDIO_NOT_OWNED_DETAIL)
    root = owner_reference_audio_root(audio_dir, user_id).resolve()
    raw = audio_dir / stored_relative
    if raw.is_symlink():
        raise ReferenceAudioRejected(REFERENCE_AUDIO_NOT_OWNED_DETAIL)
    candidate = raw.resolve()
    if not candidate.is_relative_to(root):
        raise ReferenceAudioRejected(REFERENCE_AUDIO_NOT_OWNED_DETAIL)
    if not candidate.is_file():
        raise ReferenceAudioRejected(REFERENCE_AUDIO_NOT_OWNED_DETAIL)
    if candidate.suffix.lower() not in REFERENCE_AUDIO_EXTENSIONS:
        raise ReferenceAudioRejected(REFERENCE_AUDIO_NOT_OWNED_DETAIL)
    return candidate
