"""The lockfile's ffmpeg, reachable as `ffmpeg` on PATH for the tests that request it."""

from __future__ import annotations

import os
from pathlib import Path

import imageio_ffmpeg
import pytest


@pytest.fixture
def locked_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Link the `dev` extra's ffmpeg as `ffmpeg` in a temporary directory ahead of PATH."""
    link_directory = tmp_path / "locked-ffmpeg"
    link_directory.mkdir()
    link = link_directory / "ffmpeg"
    link.symlink_to(imageio_ffmpeg.get_ffmpeg_exe())
    monkeypatch.setenv("PATH", f"{link_directory}{os.pathsep}{os.environ['PATH']}")
    return link
