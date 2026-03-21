"""Tests for generation snapshot writing and reading."""

from __future__ import annotations

from pathlib import Path

from acestep_engine.models import AceStepConfig, ServerInfo
from songmaker_cli.config import OutputPaths
from songmaker_cli.snapshot import read_generation_info
from songmaker_cli.snapshot import write_snapshot


def _make_song_md(path: Path) -> Path:
    md = path / "song.md"
    md.write_text(
        "---\n"
        "title: Test Song\n"
        "album: test\n"
        "prompt: rock anthem\n"
        "bpm: 120\n"
        "duration: 60\n"
        "key: Am\n"
        "---\n"
        "\n"
        "## Lyrics\n"
        "\n"
        "[verse]\n"
        "Hello world\n",
    )
    return md


def _make_paths(tmp_path: Path) -> OutputPaths:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return OutputPaths(
        output_dir=output_dir,
        base_name="song",
        version=1,
        versioned_name="song_v1",
    )


def test_write_snapshot_creates_md(tmp_path: Path) -> None:
    md = _make_song_md(tmp_path)
    paths = _make_paths(tmp_path)
    config = AceStepConfig(
        prompt="rock anthem", lyrics="Hello world",
        bpm=140, duration=90, key="Am", guidance_scale=3.5,
        inference_steps=60, shift=3.0, think_mode=True,
    )
    info = ServerInfo(model="acestep-v15-turbo", lm_model="lm-4B", version="1.0")

    result = write_snapshot(md, paths, config, seed=12345, server_info=info)

    assert result.exists()
    assert result.name == "song_v1.md"
    text = result.read_text()
    assert "title: Test Song" in text
    assert "bpm: 140" in text
    assert "duration: 90" in text
    assert "guidance_scale: 3.5" in text
    assert "seed: 12345" in text
    assert "acestep_model: acestep-v15-turbo" in text
    assert "## Generation" in text


def test_write_snapshot_overrides_frontmatter(tmp_path: Path) -> None:
    md = _make_song_md(tmp_path)
    paths = _make_paths(tmp_path)
    config = AceStepConfig(
        prompt="rock anthem", lyrics="Hello world",
        bpm=180, duration=120, key="Cm",
    )

    result = write_snapshot(md, paths, config, seed=99)
    text = result.read_text()

    assert "bpm: 180" in text
    assert "duration: 120" in text
    assert "key: Cm" in text


def test_write_snapshot_without_server_info(tmp_path: Path) -> None:
    md = _make_song_md(tmp_path)
    paths = _make_paths(tmp_path)
    config = AceStepConfig(prompt="test", lyrics="test")

    result = write_snapshot(md, paths, config, seed=1)
    text = result.read_text()

    assert "seed: 1" in text
    assert "acestep_model" not in text


def test_write_snapshot_preserves_lyrics(tmp_path: Path) -> None:
    md = _make_song_md(tmp_path)
    paths = _make_paths(tmp_path)
    config = AceStepConfig(prompt="rock anthem", lyrics="Hello world")

    result = write_snapshot(md, paths, config, seed=1)
    text = result.read_text()

    assert "[verse]" in text
    assert "Hello world" in text


def test_read_generation_info_from_snapshot(tmp_path: Path) -> None:
    md = _make_song_md(tmp_path)
    paths = _make_paths(tmp_path)
    config = AceStepConfig(
        prompt="rock", lyrics="hello",
        bpm=140, guidance_scale=3.5, inference_steps=60,
        think_mode=True, shift=3.0,
    )
    info = ServerInfo(model="turbo", lm_model="lm-4B", version="1.0")
    snapshot = write_snapshot(md, paths, config, seed=42, server_info=info)

    gen = read_generation_info(snapshot)

    assert gen is not None
    assert gen["seed"] == 42
    assert gen["acestep_model"] == "turbo"
    assert gen["bpm"] == 140
    assert gen["guidance_scale"] == 3.5
    assert gen["think_mode"] is True


def test_read_generation_info_missing_file(tmp_path: Path) -> None:
    assert read_generation_info(tmp_path / "nonexistent.md") is None


def test_read_generation_info_no_generation_section(tmp_path: Path) -> None:
    md = tmp_path / "plain.md"
    md.write_text("---\nbpm: 120\n---\n\nJust lyrics\n")

    gen = read_generation_info(md)

    assert gen is not None
    assert gen["bpm"] == 120
