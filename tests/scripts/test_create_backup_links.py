"""Every tracked link under ``scripts/`` resolves to a tracked executable inside ``scripts/``."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

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


NOT_EXECUTABLE = "does not resolve to a tracked executable file"


@pytest.mark.parametrize(
    ("link_target", "reason"),
    [
        ("missing.sh", NOT_EXECUTABLE),
        ("plain.sh", NOT_EXECUTABLE),
        ("untracked.sh", NOT_EXECUTABLE),
        ("../outside.sh", "leaves scripts/"),
    ],
    ids=["dangling", "tracked-not-executable", "untracked", "outside-scripts"],
)
def test_a_link_that_is_not_a_tracked_executable_inside_scripts_is_reported(
    tmp_path, link_target, reason
):
    _git(tmp_path, "init", "-q")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "bad.sh").symlink_to(link_target)
    (tmp_path / "outside.sh").write_text("")
    (scripts / "untracked.sh").write_text("")
    (scripts / "untracked.sh").chmod(0o755)
    (scripts / "plain.sh").write_text("")
    _git(tmp_path, "add", "scripts/bad.sh", "scripts/plain.sh")

    assert broken_links(tmp_path) == [f"scripts/bad.sh {reason}"]
