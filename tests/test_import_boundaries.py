"""The packages beside the application never import it, and CI proves it."""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
CONTRACT_FILE = REPOSITORY_ROOT / ".importlinter"
CONTRACT_SECTION = "importlinter:contract:independent-packages"
APPLICATION_PACKAGE = "songmaker_cli"
INDEPENDENT_PACKAGE = "agent_providers"
INJECTED_IMPORT = f"from {APPLICATION_PACKAGE} import constants\n"
FORBIDDEN_CHAIN = f"{INDEPENDENT_PACKAGE} -> {APPLICATION_PACKAGE}.constants"
UNCOPIED_ARTEFACTS = shutil.ignore_patterns("__pycache__", "*.egg-info")


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


def _linter_executable() -> str:
    beside_interpreter = Path(sys.executable).with_name("lint-imports")
    if beside_interpreter.exists():
        return str(beside_interpreter)
    on_path = shutil.which("lint-imports")
    if on_path is None:
        pytest.fail(
            "lint-imports is missing, so the import boundary is unproven. "
            "It ships with the dev extra: "
            "uv sync --extra server --extra dev",
        )
    return on_path


def _environment_pointing_at(source_root: Path) -> dict[str, str]:
    environment = dict(os.environ)
    inherited_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(source_root), *([inherited_path] if inherited_path else [])],
    )
    return environment


def _lint_imports(project_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_linter_executable(), "--no-cache"],
        cwd=project_root,
        env=_environment_pointing_at(project_root / "src"),
        text=True,
        capture_output=True,
        check=False,
    )


def _copy_of_this_tree(destination: Path) -> Path:
    shutil.copytree(SOURCE_ROOT, destination / "src", ignore=UNCOPIED_ARTEFACTS)
    shutil.copyfile(CONTRACT_FILE, destination / CONTRACT_FILE.name)
    return destination


def test_independent_packages_do_not_import_the_application() -> None:
    completed = _lint_imports(REPOSITORY_ROOT)

    assert completed.returncode == 0, (
        f"lint-imports reported a broken boundary.\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


def test_an_application_import_in_an_independent_package_breaks_the_contract(
    tmp_path: Path,
) -> None:
    project_root = _copy_of_this_tree(tmp_path)
    package_init = project_root / "src" / INDEPENDENT_PACKAGE / "__init__.py"
    package_init.write_text(
        package_init.read_text(encoding="utf-8") + INJECTED_IMPORT,
        encoding="utf-8",
    )

    completed = _lint_imports(project_root)

    assert completed.returncode == 1, (
        f"lint-imports accepted an application import in {INDEPENDENT_PACKAGE}.\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert FORBIDDEN_CHAIN in completed.stdout, completed.stdout


def test_every_package_beside_the_application_is_under_contract() -> None:
    packages = _source_packages()

    assert APPLICATION_PACKAGE in packages
    assert _named_modules("importlinter", "root_packages") == packages
    assert _named_modules(CONTRACT_SECTION, "source_modules") == packages - {
        APPLICATION_PACKAGE,
    }
    assert _named_modules(CONTRACT_SECTION, "forbidden_modules") == {APPLICATION_PACKAGE}
