"""The documented Go/Stay split of the provider constants is the real one."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import agent_providers.constants as library_constants
from songmaker_cli import constants as application_constants

PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]
ARCHITECTURE_DOC: Final = PROJECT_ROOT / "docs" / "architecture.md"
LIBRARY_MODULE: Final = PROJECT_ROOT / "src" / "agent_providers" / "constants.py"
APPLICATION_MODULE: Final = PROJECT_ROOT / "src" / "songmaker_cli" / "constants.py"
PROVIDER_SOURCES: Final = (
    PROJECT_ROOT / "src" / "songmaker_cli" / "agent_cli.py",
    PROJECT_ROOT / "src" / "songmaker_cli" / "claude",
    PROJECT_ROOT / "src" / "songmaker_cli" / "cowriter",
)

GO: Final = "Go"
STAY: Final = "Stay"
APPLICATION_PACKAGE: Final = "songmaker_cli"
CONSTANTS_MODULE: Final = "constants"
APPLICATION_CONSTANTS: Final = f"{APPLICATION_PACKAGE}.{CONSTANTS_MODULE}"


def _documented_names(side: str) -> set[str]:
    names = set()
    for line in ARCHITECTURE_DOC.read_text().splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) >= 5 and cells[2] == side:
            names.add(cells[1].strip("`"))
    return names


def _defined_names(module: Path) -> set[str]:
    names = set()
    for statement in ast.parse(module.read_text()).body:
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            names.add(statement.target.id)
        elif isinstance(statement, ast.Assign):
            names.update(t.id for t in statement.targets if isinstance(t, ast.Name))
    return names


def _application_constants_a_module_can_read(source: Path, forbidden: set[str]) -> set[str]:
    """What the module could read out of the application's constants.

    A ``from ... import NAME`` is judged name by name, because a provider module
    may still take a Stay constant. A handle on the module itself hides which
    constant is read behind an attribute access, so it counts whole.
    """
    reads = set()
    for node in ast.walk(ast.parse(source.read_text())):
        if isinstance(node, ast.Import):
            reads |= {alias.name for alias in node.names if alias.name == APPLICATION_CONSTANTS}
        elif isinstance(node, ast.ImportFrom) and node.module == APPLICATION_CONSTANTS:
            reads |= {alias.name for alias in node.names} & forbidden
        elif isinstance(node, ast.ImportFrom) and node.module == APPLICATION_PACKAGE:
            reads |= {
                APPLICATION_CONSTANTS
                for alias in node.names
                if alias.name == CONSTANTS_MODULE
            }
    return reads


def _provider_modules() -> list[Path]:
    modules = []
    for path in PROVIDER_SOURCES:
        modules.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path])
    return modules


def test_the_library_defines_every_go_constant_and_nothing_else() -> None:
    assert _defined_names(LIBRARY_MODULE) == _documented_names(GO)


def test_the_application_no_longer_defines_a_go_constant() -> None:
    assert _defined_names(APPLICATION_MODULE) & _documented_names(GO) == set()


def test_the_application_owns_every_stay_constant_alone() -> None:
    stay = _documented_names(STAY)

    assert stay <= _defined_names(APPLICATION_MODULE)
    assert {name for name in stay if hasattr(library_constants, name)} == set()


def test_every_go_constant_is_still_reachable_through_the_transitional_re_export() -> None:
    """A6 deletes this test together with the shim it guards."""
    go = _documented_names(GO)

    assert {name: getattr(application_constants, name) for name in go} == {
        name: getattr(library_constants, name) for name in go
    }


def test_no_provider_module_reaches_the_application_for_a_go_constant() -> None:
    go = _documented_names(GO)

    assert {
        module.name: sorted(reads)
        for module in _provider_modules()
        if (reads := _application_constants_a_module_can_read(module, go))
    } == {}
