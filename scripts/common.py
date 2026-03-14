"""Shared utilities for ACE-Step scripts."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def find_uv() -> list[str]:
    """Find a working uv command.

    Returns the command prefix as a list (e.g. ["uv"] or
    [sys.executable, "-m", "uv"]).
    """
    if shutil.which("uv"):
        return ["uv"]

    try:
        subprocess.run(
            [sys.executable, "-m", "uv", "--version"],
            capture_output=True, check=True,
        )
        return [sys.executable, "-m", "uv"]
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    if sys.platform == "win32":
        home = Path.home()
        candidates = [
            home / ".local" / "bin" / "uv.exe",
            home / ".cargo" / "bin" / "uv.exe",
            home / "AppData" / "Roaming" / "Python" / "Python312" / "Scripts" / "uv.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return [str(candidate)]

    return []
