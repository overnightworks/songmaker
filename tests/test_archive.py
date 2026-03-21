"""Tests for the archive module."""

from __future__ import annotations

from pathlib import Path

from songmaker_cli.archive import archive_below_threshold, archive_file


def _create_versioned_mp3(album_dir: Path, name: str, scores: str = "") -> Path:
    """Create a fake MP3 + snapshot in an album directory."""
    mp3 = album_dir / f"{name}.mp3"
    mp3.write_bytes(b"\xff\xfb\x90\x00" * 10)
    snapshot = album_dir / f"{name}.md"
    text = "---\ntitle: Test\n---\n\n## Lyrics\n\nHello\n\n## Generation\n\n- seed: 42\n"
    if scores:
        text += f"\n## Scores\n\n{scores}"
    snapshot.write_text(text)
    return mp3


def test_archive_file_moves_mp3_and_snapshot(tmp_path: Path) -> None:
    album_dir = tmp_path / "_output" / "test_album"
    album_dir.mkdir(parents=True)
    archive_dir = tmp_path / "_archive"

    mp3 = _create_versioned_mp3(album_dir, "01_song_v1")
    archive_file(mp3, archive_dir)

    assert not mp3.exists()
    assert not mp3.with_suffix(".md").exists()
    assert (archive_dir / "test_album" / "01_song_v1.mp3").exists()
    assert (archive_dir / "test_album" / "01_song_v1.md").exists()


def test_archive_file_without_snapshot(tmp_path: Path) -> None:
    album_dir = tmp_path / "_output" / "test_album"
    album_dir.mkdir(parents=True)
    archive_dir = tmp_path / "_archive"

    mp3 = album_dir / "01_song_v1.mp3"
    mp3.write_bytes(b"\xff\xfb\x90\x00" * 10)

    archive_file(mp3, archive_dir)

    assert not mp3.exists()
    assert (archive_dir / "test_album" / "01_song_v1.mp3").exists()


def test_archive_file_creates_dest_dir(tmp_path: Path) -> None:
    album_dir = tmp_path / "_output" / "new_album"
    album_dir.mkdir(parents=True)
    archive_dir = tmp_path / "_archive"

    mp3 = _create_versioned_mp3(album_dir, "01_song_v1")
    archive_file(mp3, archive_dir)

    assert (archive_dir / "new_album").is_dir()


def test_archive_below_threshold_filters_correctly(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output"
    album_dir = output_dir / "test_album"
    album_dir.mkdir(parents=True)
    archive_dir = tmp_path / "_archive"

    _create_versioned_mp3(album_dir, "01_low_v1", "- dynamics: 20.0\n")
    _create_versioned_mp3(album_dir, "02_high_v1", "- dynamics: 80.0\n")
    _create_versioned_mp3(album_dir, "03_mid_v1", "- dynamics: 49.9\n")

    def mock_read_scores(path: Path) -> dict[str, object] | None:
        from songmaker_cli.snapshot import read_scores
        return read_scores(path)

    archived = archive_below_threshold(50.0, output_dir, archive_dir, mock_read_scores)

    assert archived == 2
    assert not (album_dir / "01_low_v1.mp3").exists()
    assert (album_dir / "02_high_v1.mp3").exists()
    assert not (album_dir / "03_mid_v1.mp3").exists()
    assert (archive_dir / "test_album" / "01_low_v1.mp3").exists()
    assert (archive_dir / "test_album" / "03_mid_v1.mp3").exists()


def test_archive_below_threshold_skips_no_snapshot(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output"
    album_dir = output_dir / "test_album"
    album_dir.mkdir(parents=True)
    archive_dir = tmp_path / "_archive"

    mp3 = album_dir / "01_song_v1.mp3"
    mp3.write_bytes(b"\xff\xfb\x90\x00" * 10)

    archived = archive_below_threshold(50.0, output_dir, archive_dir, lambda _: None)

    assert archived == 0
    assert mp3.exists()


def test_archive_below_threshold_skips_no_dynamics(tmp_path: Path) -> None:
    output_dir = tmp_path / "_output"
    album_dir = output_dir / "test_album"
    album_dir.mkdir(parents=True)
    archive_dir = tmp_path / "_archive"

    _create_versioned_mp3(album_dir, "01_song_v1", "- silence_ok: True\n")

    def mock_read_scores(path: Path) -> dict[str, object] | None:
        from songmaker_cli.snapshot import read_scores
        return read_scores(path)

    archived = archive_below_threshold(50.0, output_dir, archive_dir, mock_read_scores)

    assert archived == 0
    assert (album_dir / "01_song_v1.mp3").exists()
