"""Shared arrangement for the cover tests that try to escape the cover directory."""

from __future__ import annotations

from pathlib import Path

SIBLING_DIRECTORY = "<absolute path of the directory beside audio_dir>"


def unsafe_cover_id(raw_id: str, sibling_marker: Path) -> str:
    """Resolve the sibling-directory sentinel to the real directory beside audio_dir."""
    return str(sibling_marker.parent) if raw_id == SIBLING_DIRECTORY else raw_id


def cover_escape_layout(
    tmp_path: Path, legit_relative: Path,
) -> tuple[Path, Path, Path, Path]:
    """Build audio_dir, a sibling directory and one legit cover directory, each marked."""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    marker = audio_dir / "marker.txt"
    marker.write_text("keep")
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    sibling_marker = sibling / "marker.txt"
    sibling_marker.write_text("keep")
    legit = audio_dir / legit_relative
    legit.mkdir(parents=True)
    (legit / "keep.txt").write_text("keep")
    return audio_dir, marker, sibling_marker, legit


def assert_escape_markers_survive(
    audio_dir: Path, marker: Path, sibling_marker: Path, legit: Path,
) -> None:
    """Assert that nothing outside the intended cover directory was touched."""
    assert marker.read_text() == "keep"
    assert sibling_marker.read_text() == "keep"
    assert (legit / "keep.txt").read_text() == "keep"
    assert audio_dir.is_dir()
