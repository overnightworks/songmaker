"""Owner-scoped reference-audio path resolution."""

from __future__ import annotations

from pathlib import Path

from songmaker_cli.constants import REFERENCE_AUDIO_DIR, REFERENCE_AUDIO_EXTENSIONS


class ReferenceAudioRejected(ValueError):
    pass


def owner_reference_audio_root(audio_dir: Path, user_id: str) -> Path:
    return audio_dir / user_id / REFERENCE_AUDIO_DIR


def resolve_owned_reference_audio(
    audio_dir: Path, user_id: str, stored_relative: str,
) -> Path:
    if not stored_relative or stored_relative.startswith("/") or ".." in stored_relative:
        raise ReferenceAudioRejected("reference audio path is not owned")
    root = owner_reference_audio_root(audio_dir, user_id).resolve()
    raw = audio_dir / stored_relative
    if raw.is_symlink():
        raise ReferenceAudioRejected("reference audio path is not owned")
    candidate = raw.resolve()
    if not candidate.is_relative_to(root):
        raise ReferenceAudioRejected("reference audio path is not owned")
    if not candidate.is_file():
        raise ReferenceAudioRejected("reference audio path is not owned")
    if candidate.suffix.lower() not in REFERENCE_AUDIO_EXTENSIONS:
        raise ReferenceAudioRejected("reference audio path is not owned")
    return candidate
