"""The import boundaries hold, and CI proves it.

The packages beside the application never import it, and persistence never
imports the HTTP contract.
"""

from __future__ import annotations

import configparser
import importlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from packaging.version import Version

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
CONTRACT_FILE = REPOSITORY_ROOT / ".importlinter"
CONTRACT_SECTION = "importlinter:contract:independent-packages"
APPLICATION_PACKAGE = "songmaker_cli"
INDEPENDENT_PACKAGE = "acestep_engine"
INDEPENDENT_PACKAGES = ("agent_providers", "webauth")
UNCOPIED_ARTEFACTS = shutil.ignore_patterns("__pycache__", "*.egg-info")


@dataclass(frozen=True)
class Breach:
    importer: str
    injected_import: str
    forbidden_chain: str


BREACHES_BY_CONTRACT = {
    "independent-packages": Breach(
        importer=f"{INDEPENDENT_PACKAGE}/__init__.py",
        injected_import=f"from {APPLICATION_PACKAGE} import constants\n",
        forbidden_chain=f"{INDEPENDENT_PACKAGE} -> {APPLICATION_PACKAGE}.constants",
    ),
    "persistence-below-http-contract": Breach(
        importer=f"{APPLICATION_PACKAGE}/db/__init__.py",
        injected_import=f"from {APPLICATION_PACKAGE}.api_models import fields\n",
        forbidden_chain=f"{APPLICATION_PACKAGE}.db -> {APPLICATION_PACKAGE}.api_models.fields",
    ),
}


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


def test_real_tree_satisfies_both_import_contracts() -> None:
    """925_M1_G1 -- the real source tree satisfies both contracts: the independent
    packages never import the application, and persistence never imports the HTTP contract."""
    completed = _lint_imports(REPOSITORY_ROOT)

    assert completed.returncode == 0, (
        f"lint-imports reported a broken boundary.\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


@pytest.mark.parametrize(
    "breach",
    BREACHES_BY_CONTRACT.values(),
    ids=BREACHES_BY_CONTRACT.keys(),
)
def test_a_forbidden_import_breaks_its_contract_and_names_the_chain(
    breach: Breach,
    tmp_path: Path,
) -> None:
    """925_M1_G1 -- an import across either contracted boundary breaks
    lint-imports, and the output names the chain."""
    project_root = _copy_of_this_tree(tmp_path)
    importer = project_root / "src" / breach.importer
    importer.write_text(
        importer.read_text(encoding="utf-8") + breach.injected_import,
        encoding="utf-8",
    )

    completed = _lint_imports(project_root)

    assert completed.returncode == 1, (
        f"lint-imports accepted {breach.injected_import!r} in {breach.importer}.\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert breach.forbidden_chain in completed.stdout, completed.stdout


def test_every_package_beside_the_application_is_under_contract() -> None:
    packages = _source_packages()

    assert APPLICATION_PACKAGE in packages
    assert _named_modules("importlinter", "root_packages") == packages
    assert _named_modules(CONTRACT_SECTION, "source_modules") == packages - {
        APPLICATION_PACKAGE,
    }
    assert _named_modules(CONTRACT_SECTION, "forbidden_modules") == {APPLICATION_PACKAGE}


@pytest.mark.parametrize("package_name", INDEPENDENT_PACKAGES)
def test_the_independent_package_exposes_a_pep440_version(package_name: str) -> None:
    independent_package = importlib.import_module(package_name)

    Version(independent_package.__version__)
