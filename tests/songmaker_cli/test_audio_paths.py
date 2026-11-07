"""Which stored or requested audio paths count as lying below the audio folder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from songmaker_cli.audio_paths import (
    AudioFileNotFoundError,
    AudioPathRejectedError,
    canonical_audio_filename,
    confined_under,
    resolve_audio_path,
)
from songmaker_cli.db.queries.generations import delete_generation_files


@dataclass(frozen=True)
class AudioLayout:
    audio_dir: Path
    requested: str
    take_file: Path
    is_confined: bool


def _child_file(tmp_path: Path, requested: str | None = None) -> AudioLayout:
    audio_dir = tmp_path / "audio"
    take_file = audio_dir / "u1" / "g1.mp3"
    take_file.parent.mkdir(parents=True)
    take_file.write_bytes(b"fake")
    return AudioLayout(audio_dir, requested or "u1/g1.mp3", take_file, is_confined=True)


def _root_itself(tmp_path: Path, requested: str) -> AudioLayout:
    layout = _child_file(tmp_path)
    return AudioLayout(layout.audio_dir, requested, layout.take_file, is_confined=False)


def _escape(tmp_path: Path) -> AudioLayout:
    layout = _child_file(tmp_path)
    outside = tmp_path / "outside" / "g1.mp3"
    outside.parent.mkdir()
    outside.write_bytes(b"fake")
    return AudioLayout(layout.audio_dir, "../outside/g1.mp3", outside, is_confined=False)


def _link_inside_to_outside(tmp_path: Path) -> AudioLayout:
    layout = _child_file(tmp_path)
    outside = tmp_path / "outside" / "g2.mp3"
    outside.parent.mkdir()
    outside.write_bytes(b"fake")
    (layout.audio_dir / "u1" / "link.mp3").symlink_to(outside)
    return AudioLayout(layout.audio_dir, "u1/link.mp3", outside, is_confined=False)


def _link_inside_to_inside(tmp_path: Path) -> AudioLayout:
    layout = _child_file(tmp_path)
    (layout.audio_dir / "u1" / "link.mp3").symlink_to(layout.take_file)
    return AudioLayout(layout.audio_dir, "u1/link.mp3", layout.take_file, is_confined=True)


def _symlinked_audio_folder(tmp_path: Path) -> AudioLayout:
    layout = _child_file(tmp_path)
    linked_folder = tmp_path / "audio-link"
    linked_folder.symlink_to(layout.audio_dir)
    return AudioLayout(linked_folder, "u1/g1.mp3", layout.take_file, is_confined=True)


LAYOUTS = {
    "child": lambda tmp_path: _child_file(tmp_path),
    "empty-name": lambda tmp_path: _root_itself(tmp_path, ""),
    "dot": lambda tmp_path: _root_itself(tmp_path, "."),
    "dotdot-escape": _escape,
    "link-inside-to-outside": _link_inside_to_outside,
    "link-inside-to-inside": _link_inside_to_inside,
    "symlinked-audio-folder": _symlinked_audio_folder,
}


@pytest.fixture(params=LAYOUTS)
def layout(request: pytest.FixtureRequest, tmp_path: Path) -> AudioLayout:
    return LAYOUTS[request.param](tmp_path)


def test_serving_a_path_answers_only_for_one_below_the_audio_folder(layout: AudioLayout) -> None:
    if layout.is_confined:
        assert resolve_audio_path(layout.audio_dir, layout.requested) == layout.take_file
    else:
        with pytest.raises(AudioPathRejectedError):
            resolve_audio_path(layout.audio_dir, layout.requested)


def test_confined_under_returns_the_resolved_path_only_for_one_below_the_root(
    layout: AudioLayout,
) -> None:
    confined = confined_under(layout.audio_dir, layout.audio_dir / layout.requested)

    assert confined == (layout.take_file if layout.is_confined else None)


def test_storing_a_path_keeps_only_one_below_the_audio_folder(layout: AudioLayout) -> None:
    stored = canonical_audio_filename(layout.audio_dir, layout.requested)

    if layout.is_confined:
        assert (
            stored == layout.take_file.resolve().relative_to(layout.audio_dir.resolve()).as_posix()
        )
    else:
        assert stored is None


def test_deleting_a_take_removes_its_file_only_when_it_lies_below_the_audio_folder(
    layout: AudioLayout,
) -> None:
    delete_generation_files(layout.audio_dir, layout.requested)

    assert layout.take_file.exists() is not layout.is_confined


def test_serving_a_missing_child_is_not_found(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()

    with pytest.raises(AudioFileNotFoundError):
        resolve_audio_path(audio_dir, "u1/missing.mp3")
