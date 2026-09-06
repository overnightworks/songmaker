"""The packages beside the application never import it, and CI proves it."""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
CONTRACT_FILE = REPOSITORY_ROOT / ".importlinter"
CONTRACT_SECTION = "importlinter:contract:independent-packages"
APPLICATION_PACKAGE = "songmaker_cli"


def _contract() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(CONTRACT_FILE)
    return parser


def _named_modules(section: str, option: str) -> frozenset[str]:
    return frozenset(_contract()[section][option].split())


def _source_packages() -> frozenset[str]:
    return frozenset(
        directory.name
        for directory in SOURCE_ROOT.iterdir()
        if (directory / "__init__.py").exists()
    )


def _analyze_this_tree() -> dict[str, str]:
    environment = dict(os.environ)
    inherited_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(SOURCE_ROOT), *([inherited_path] if inherited_path else [])],
    )
    return environment


def test_independent_packages_do_not_import_the_application() -> None:
    linter = shutil.which("lint-imports")
    if linter is None:
        pytest.skip("import-linter is missing; install the dev extra to get lint-imports")

    completed = subprocess.run(
        [linter],
        cwd=REPOSITORY_ROOT,
        env=_analyze_this_tree(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, (
        f"lint-imports reported a broken boundary.\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


def test_every_package_beside_the_application_is_under_contract() -> None:
    packages = _source_packages()

    assert APPLICATION_PACKAGE in packages
    assert _named_modules("importlinter", "root_packages") == packages
    assert _named_modules(CONTRACT_SECTION, "source_modules") == packages - {
        APPLICATION_PACKAGE,
    }
    assert _named_modules(CONTRACT_SECTION, "forbidden_modules") == {APPLICATION_PACKAGE}
