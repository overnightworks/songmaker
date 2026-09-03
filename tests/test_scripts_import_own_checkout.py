"""Regression tests for script imports from Git worktrees."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def test_script_imports_songmaker_cli_from_its_copied_checkout(tmp_path: Path) -> None:
    copied_checkout = tmp_path / "copied-checkout"
    copied_scripts = copied_checkout / "scripts"
    shutil.copytree(SCRIPTS, copied_scripts)
    package = copied_checkout / "src" / "songmaker_cli"
    database = package / "db"
    database.mkdir(parents=True)
    (package / "__init__.py").write_text("print(__file__)\n")
    (package / "api_helpers.py").write_text("def unique_album_id(*args):\n    return 'album'\n")
    (database / "__init__.py").write_text("")
    (database / "engine.py").write_text(
        "def connect_db(*args):\n    return None\n\ndef resolve_database_url():\n    return ''\n",
    )
    (database / "queries.py").write_text(
        "def create_album(*args):\n    return None\n\n"
        "def get_user_by_username(*args):\n    return None\n",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(copied_scripts / "seed_e2e_filler_albums.py"),
            "--help",
        ],
        check=True,
        capture_output=True,
        cwd=tmp_path,
        text=True,
    )

    assert str(package / "__init__.py") in result.stdout
