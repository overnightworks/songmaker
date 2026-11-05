"""Every test that needs PostgreSQL is visible to collection, so `-m postgresql` selects it.

Collection sees the fixture closure and the marks on parameters. It cannot see a dynamic
`getfixturevalue` of a PostgreSQL fixture or a direct read of `TEST_DATABASE_URL`; both are
refused outside `tests/conftest.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
CONFTEST = TESTS_ROOT / "conftest.py"
POSTGRESQL_URL_VARIABLE = "TEST_DATABASE_URL"
POSTGRESQL_FIXTURES = frozenset(
    {"postgresql_url", "pg_factory", "database_postgresql_url", "database_pg_factory"}
)
ENVIRONMENT_READERS = frozenset({"get", "getenv"})


def _string_value(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _is_environment_read(node: ast.AST) -> bool:
    """`os.environ[NAME]`, `os.environ.get(NAME)` or `os.getenv(NAME)` of the PostgreSQL URL."""
    if isinstance(node, ast.Subscript):
        reads_environment = "environ" in ast.unparse(node.value)
        return reads_environment and _string_value(node.slice) == POSTGRESQL_URL_VARIABLE
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        reads = node.func.attr in ENVIRONMENT_READERS
        return reads and bool(node.args) and _string_value(node.args[0]) == POSTGRESQL_URL_VARIABLE
    return False


def _is_dynamic_fixture_request(node: ast.AST) -> bool:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    requested = _string_value(node.args[0]) if node.args else None
    return node.func.attr == "getfixturevalue" and requested in POSTGRESQL_FIXTURES


def invisible_postgresql_paths(root: Path) -> list[str]:
    breaches = []
    for path in sorted(root.rglob("*.py")):
        if path == CONFTEST:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if _is_environment_read(node) or _is_dynamic_fixture_request(node):
                breaches.append(f"{path.relative_to(root)}:{node.lineno}: {ast.unparse(node)}")
    return breaches


def test_no_test_reaches_postgresql_by_a_path_collection_cannot_see():
    assert invisible_postgresql_paths(TESTS_ROOT) == []
