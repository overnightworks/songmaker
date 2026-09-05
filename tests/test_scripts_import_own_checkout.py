"""Regression tests for script imports from Git worktrees."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.mark.parametrize(
    "script_name",
    ["archive_e2e_albums.py", "seed_e2e_filler_albums.py"],
)
def test_script_imports_songmaker_cli_from_its_copied_checkout(
    tmp_path: Path, script_name: str,
) -> None:
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
    (database / "models.py").write_text("class Album:\n    pass\n")

    result = subprocess.run(
        [
            sys.executable,
            str(copied_scripts / script_name),
            "--help",
        ],
        check=True,
        capture_output=True,
        cwd=tmp_path,
        text=True,
    )

    assert str(package / "__init__.py") in result.stdout
