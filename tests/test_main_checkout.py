"""Behavioural tests for ``scripts/main_checkout.py`` (issue #1499): which checkout is the main one.

Every path that is not a git checkout is refused with the module's one failure,
``CheckoutError``, saying so: callers such as ``scripts/grafana_password.py`` catch
nothing else. Checkouts are real repositories built in ``tmp_path``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from main_checkout import CheckoutError, main_checkout_elsewhere  # noqa: E402

NEEDS_NON_ROOT = pytest.mark.skipif(
    os.geteuid() == 0, reason="root enters every directory, so no permission can deny it",
)

LockDirectory = Callable[[Path], None]


def git(directory: Path, *arguments: str) -> None:
    subprocess.run(
        [
            "git", "-c", "user.name=test", "-c", "user.email=test@example.invalid",
            "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *arguments,
        ],
        cwd=directory, check=True, capture_output=True,
    )


@pytest.fixture
def main_checkout(tmp_path: Path) -> Path:
    checkout = tmp_path / "main"
    checkout.mkdir()
    git(checkout, "init", "-q")
    git(checkout, "commit", "-q", "--allow-empty", "-m", "first")
    return checkout


@pytest.fixture
def linked_worktree(main_checkout: Path, tmp_path: Path) -> Path:
    linked = tmp_path / "linked"
    git(main_checkout, "worktree", "add", "-q", str(linked))
    return linked


@pytest.fixture
def lock_directory() -> Iterator[LockDirectory]:
    """Deny every access to a directory until the test ends, pass or fail."""
    locked: list[Path] = []

    def lock(directory: Path) -> None:
        directory.chmod(0o000)
        locked.append(directory)

    yield lock
    for directory in locked:
        directory.chmod(0o700)


def a_missing_path(tmp_path: Path, lock: LockDirectory) -> Path:
    return tmp_path / "missing"


def a_file(tmp_path: Path, lock: LockDirectory) -> Path:
    file = tmp_path / "a-file"
    file.touch()
    return file


def a_directory_that_is_not_a_repository(tmp_path: Path, lock: LockDirectory) -> Path:
    directory = tmp_path / "plain"
    directory.mkdir()
    return directory


def a_directory_the_user_cannot_enter(tmp_path: Path, lock: LockDirectory) -> Path:
    directory = tmp_path / "unenterable"
    directory.mkdir()
    lock(directory)
    return directory


def a_path_under_a_parent_the_user_cannot_traverse(tmp_path: Path, lock: LockDirectory) -> Path:
    parent = tmp_path / "untraversable"
    inner = parent / "inner"
    inner.mkdir(parents=True)
    lock(parent)
    return inner


@pytest.mark.parametrize(
    "make_path",
    [
        pytest.param(a_missing_path, id="missing-path"),
        pytest.param(a_file, id="file"),
        pytest.param(a_directory_that_is_not_a_repository, id="plain-directory"),
        pytest.param(a_directory_the_user_cannot_enter, id="unenterable-directory",
                     marks=NEEDS_NON_ROOT),
        pytest.param(a_path_under_a_parent_the_user_cannot_traverse, id="untraversable-parent",
                     marks=NEEDS_NON_ROOT),
    ],
)
def test_a_path_that_is_not_a_checkout_is_refused_as_such(
    make_path: Callable[[Path, LockDirectory], Path],
    tmp_path: Path,
    lock_directory: LockDirectory,
) -> None:
    """defect:#1499 -- a path that is not a git checkout is refused as not a checkout."""
    path = make_path(tmp_path, lock_directory)

    with pytest.raises(CheckoutError, match="is not a git checkout"):
        main_checkout_elsewhere(path)


def test_the_main_checkout_has_no_other_main_checkout(main_checkout: Path) -> None:
    """defect:#1499 -- the main checkout itself reports no other main checkout."""
    assert main_checkout_elsewhere(main_checkout) is None


def test_a_linked_worktree_names_its_main_checkout(
    main_checkout: Path, linked_worktree: Path,
) -> None:
    """defect:#1499 -- a linked worktree names the main checkout it belongs to."""
    assert main_checkout_elsewhere(linked_worktree) == main_checkout.resolve()
