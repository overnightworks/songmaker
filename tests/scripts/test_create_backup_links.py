"""Every tracked link under ``scripts/`` resolves to a tracked executable inside ``scripts/``."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYMLINK_MODE = "120000"
EXECUTABLE_MODE = "100755"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def _tracked_modes(root: Path) -> dict[Path, str]:
    modes: dict[Path, str] = {}
    for line in _git(root, "ls-files", "-s", "scripts").splitlines():
        mode_and_object, path = line.split("\t", 1)
        modes[Path(path)] = mode_and_object.split()[0]
    return modes


def broken_links(root: Path) -> list[str]:
    modes = _tracked_modes(root)
    scripts_dir = (root / "scripts").resolve()
    problems = []
    for path, mode in modes.items():
        if mode != SYMLINK_MODE:
            continue
        target = (root / path).resolve()
        if not target.is_relative_to(scripts_dir):
            problems.append(f"{path} leaves scripts/")
        elif modes.get(target.relative_to(root.resolve())) != EXECUTABLE_MODE:
            problems.append(f"{path} does not resolve to a tracked executable file")
    return problems


def test_every_tracked_link_under_scripts_resolves_to_a_tracked_executable():
    assert broken_links(REPO_ROOT) == []


def test_a_dangling_link_is_reported(tmp_path):
    _git(tmp_path, "init", "-q")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "gone.sh").symlink_to("missing.sh")
    _git(tmp_path, "add", "scripts")

    assert broken_links(tmp_path) == [
        "scripts/gone.sh does not resolve to a tracked executable file"
    ]
