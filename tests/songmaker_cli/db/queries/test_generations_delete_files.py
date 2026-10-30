"""Tests for which files deleting a take removes."""

from __future__ import annotations

from pathlib import Path

import pytest

from songmaker_cli.db.queries.generations import delete_generation_files


@pytest.mark.parametrize(
    ("relative_name", "is_deleted"),
    [
        ("g1.mp3", True),
        ("g1.wav", True),
        ("g1.raw.wav", True),
        ("g1.pre-remaster.wav", True),
        ("g1.pre-remaster.mp3", True),
        ("g1.md", True),
        ("g1.whisper", True),
        ("g10.raw.wav", False),
        ("g1.mp3.part", False),
        ("refs/x.wav", False),
    ],
)
def test_delete_generation_files_removes_only_the_take_file_set(
    tmp_path: Path,
    relative_name: str,
    is_deleted: bool,
) -> None:
    audio_dir = tmp_path / "audio"
    take_dir = audio_dir / "u1"
    (take_dir / "refs").mkdir(parents=True)
    (take_dir / "g1.mp3").write_bytes(b"fake")
    candidate = take_dir / relative_name
    candidate.write_bytes(b"fake")

    delete_generation_files(audio_dir, "u1/g1.mp3")

    assert candidate.exists() is not is_deleted


def test_delete_generation_files_from_a_wav_path_removes_the_take_file_set(
    tmp_path: Path,
) -> None:
    take_dir = tmp_path / "audio" / "u1"
    take_dir.mkdir(parents=True)
    for name in ("g1.wav", "g1.raw.wav"):
        (take_dir / name).write_bytes(b"fake")

    delete_generation_files(tmp_path / "audio", "u1/g1.wav")

    assert not (take_dir / "g1.wav").exists()
    assert not (take_dir / "g1.raw.wav").exists()


def test_delete_generation_files_through_a_symlink_spares_files_outside(
    tmp_path: Path,
) -> None:
    audio_dir = tmp_path / "audio"
    (audio_dir / "u1").mkdir(parents=True)
    (audio_dir / "u1" / "g1.mp3").write_bytes(b"fake")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "g1.mp3").symlink_to(audio_dir / "u1" / "g1.mp3")
    bystander = outside / "g1.wav"
    bystander.write_bytes(b"fake")

    delete_generation_files(audio_dir, "../outside/g1.mp3")

    assert bystander.exists()
    assert not (audio_dir / "u1" / "g1.mp3").exists()
