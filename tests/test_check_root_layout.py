"""Tests for ``scripts/check_root_layout.py``."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_root_layout  # noqa: E402

DIRECTORY_ENTRIES = frozenset(
    {
        ".agent-claim",
        ".git",
        ".github",
        "docker",
        "docs",
        "frontend",
        "monitoring",
        "plans",
        "prompts",
        "scripts",
        "src",
        "tests",
        "vendor",
    }
)


@pytest.fixture(autouse=True)
def _isolated_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keeps the temp-repo tests independent of the developer's global git config."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")


def _seed_allowlisted_root(repository_root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repository_root, check=True)
    for name in check_root_layout.ALLOWED_ROOT_ENTRIES:
        if name in DIRECTORY_ENTRIES:
            if name == ".git":
                continue
            directory = repository_root / name
            directory.mkdir()
            (directory / "keep.txt").write_text("placeholder\n")
        else:
            (repository_root / name).write_text("placeholder\n")
    subprocess.run(["git", "add", "-A"], cwd=repository_root, check=True)


def test_an_allowlist_only_root_reports_no_violations(tmp_path: Path) -> None:
    _seed_allowlisted_root(tmp_path)

    assert check_root_layout.find_violations(tmp_path) == []


def test_an_extra_tracked_root_file_is_a_violation(tmp_path: Path) -> None:
    _seed_allowlisted_root(tmp_path)
    (tmp_path / "stray_helper.py").write_text("print('stray')\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    assert check_root_layout.find_violations(tmp_path) == ["stray_helper.py"]


def test_an_untracked_but_not_ignored_root_file_is_still_a_violation(tmp_path: Path) -> None:
    _seed_allowlisted_root(tmp_path)
    (tmp_path / "stray_helper.py").write_text("print('stray')\n")

    assert check_root_layout.find_violations(tmp_path) == ["stray_helper.py"]


def test_an_ignored_root_file_is_not_a_violation(tmp_path: Path) -> None:
    _seed_allowlisted_root(tmp_path)
    (tmp_path / ".gitignore").write_text("ignored.log\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    (tmp_path / "ignored.log").write_text("noise\n")

    assert check_root_layout.find_violations(tmp_path) == []


def test_an_extra_root_directory_is_a_violation(tmp_path: Path) -> None:
    _seed_allowlisted_root(tmp_path)
    catch_all = tmp_path / "tooling"
    catch_all.mkdir()
    (catch_all / "helper.py").write_text("print('helper')\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    assert check_root_layout.find_violations(tmp_path) == ["tooling"]


def test_main_names_the_placement_for_a_violating_file(tmp_path: Path, capsys) -> None:
    _seed_allowlisted_root(tmp_path)
    (tmp_path / "stray_helper.py").write_text("print('stray')\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    exit_code = check_root_layout.main(tmp_path)

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "stray_helper.py" in captured.err
    assert "move it next to its owner" in captured.err


def test_main_reports_clean_for_an_allowlist_only_root(tmp_path: Path, capsys) -> None:
    _seed_allowlisted_root(tmp_path)

    exit_code = check_root_layout.main(tmp_path)

    assert exit_code == 0
    assert "clean" in capsys.readouterr().out
