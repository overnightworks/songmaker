"""Owner-root resolution for reference audio."""

from __future__ import annotations

from pathlib import Path

import pytest

from songmaker_cli.constants import REFERENCE_AUDIO_DIR
from songmaker_cli.reference_audio import (
    ReferenceAudioRejected,
    resolve_owned_reference_audio,
)


def _write_ref(root: Path, user_id: str, name: str, data: bytes = b"RIFF") -> Path:
    dest = root / user_id / REFERENCE_AUDIO_DIR / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def test_resolves_owned_regular_file(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    _write_ref(audio_dir, "user-a", "clip.wav")
    resolved = resolve_owned_reference_audio(
        audio_dir, "user-a", f"user-a/{REFERENCE_AUDIO_DIR}/clip.wav",
    )
    assert resolved.is_file()
    assert resolved.name == "clip.wav"


def test_rejects_cross_user_path(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    _write_ref(audio_dir, "user-b", "clip.wav")
    with pytest.raises(ReferenceAudioRejected):
        resolve_owned_reference_audio(
            audio_dir, "user-a", f"user-b/{REFERENCE_AUDIO_DIR}/clip.wav",
        )


def test_rejects_traversal(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    _write_ref(audio_dir, "user-a", "clip.wav")
    with pytest.raises(ReferenceAudioRejected):
        resolve_owned_reference_audio(
            audio_dir, "user-a", f"user-a/{REFERENCE_AUDIO_DIR}/../clip.wav",
        )


def test_rejects_absolute_path(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    dest = _write_ref(audio_dir, "user-a", "clip.wav")
    with pytest.raises(ReferenceAudioRejected):
        resolve_owned_reference_audio(audio_dir, "user-a", str(dest))


def test_rejects_symlink_outside_owner_root(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    foreign = _write_ref(audio_dir, "user-b", "secret.wav", b"SECRET")
    link_dir = audio_dir / "user-a" / REFERENCE_AUDIO_DIR
    link_dir.mkdir(parents=True, exist_ok=True)
    link = link_dir / "alias.wav"
    link.symlink_to(foreign)
    with pytest.raises(ReferenceAudioRejected):
        resolve_owned_reference_audio(
            audio_dir, "user-a", f"user-a/{REFERENCE_AUDIO_DIR}/alias.wav",
        )
