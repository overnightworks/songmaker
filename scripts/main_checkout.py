#!/usr/bin/env python3
"""Whether a checkout is the main one, the checkout that is not disposable.

A linked worktree's admin directory lives inside the main checkout's ``.git``,
so git's common dir names the main checkout. Whatever must outlive a worktree
asks here: a permanent unit's ExecStart, and the stack compose names after the
checkout it was started from. Both sides of the comparison are resolved, so a
checkout reached through a symlink is the checkout it points at.

Each caller words its own refusal; this module only answers. Stdlib only,
imported as a sibling module by the Python scripts beside it and run as a
command by the shell ones:

    scripts/main_checkout.py PROJECT_ROOT

prints the main checkout when PROJECT_ROOT is a linked worktree of it, and
nothing when PROJECT_ROOT is the main checkout itself.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


class CheckoutError(Exception):
    """The question cannot be answered; the message is safe to print."""


def _is_enterable_directory(path: Path) -> bool:
    """Whether git can start in ``path``; unlike ``Path.is_dir``, never raises for a denied path."""
    return os.path.isdir(path) and os.access(path, os.X_OK)


def main_checkout_elsewhere(project_root: Path) -> Path | None:
    """The main checkout when ``project_root`` is a linked worktree of it, else ``None``."""
    not_a_checkout = CheckoutError(f"{project_root} is not a git checkout")
    if not _is_enterable_directory(project_root):
        raise not_a_checkout
    try:
        common_dir = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=project_root, capture_output=True, text=True, check=False,
        )
    except OSError as exc:
        raise CheckoutError("git is needed to tell the main checkout from a worktree") from exc
    if common_dir.returncode != 0:
        raise not_a_checkout
    main_checkout = Path(common_dir.stdout.strip()).resolve().parent
    return None if main_checkout == project_root.resolve() else main_checkout


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: main_checkout.py PROJECT_ROOT", file=sys.stderr)
        return 2
    try:
        main_checkout = main_checkout_elsewhere(Path(sys.argv[1]))
    except CheckoutError as error:
        print(f"ERROR: {error}.", file=sys.stderr)
        return 1
    if main_checkout is not None:
        print(main_checkout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
