"""The lockfile's ffmpeg, reachable as `ffmpeg` on PATH for the tests that request it."""

from __future__ import annotations

import os
from pathlib import Path

import imageio_ffmpeg
import pytest


def _locked_ffmpeg_executable() -> Path:
    """Return the ffmpeg inside the installed package, never one the environment points at."""
    package_directory = Path(imageio_ffmpeg.__file__).resolve().parent
    executable = Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()
    assert executable.is_relative_to(package_directory), (
        f"imageio_ffmpeg resolved {executable}, outside its package directory {package_directory}; "
        "unset IMAGEIO_FFMPEG_EXE and remove any conda ffmpeg so the locked build is used"
    )
    return executable


@pytest.fixture
def locked_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Link the `dev` extra's ffmpeg as `ffmpeg` in a temporary directory ahead of PATH."""
    link_directory = tmp_path / "locked-ffmpeg"
    link_directory.mkdir()
    link = link_directory / "ffmpeg"
    link.symlink_to(_locked_ffmpeg_executable())
    monkeypatch.setenv("PATH", f"{link_directory}{os.pathsep}{os.environ['PATH']}")
    return link
