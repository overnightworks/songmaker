"""Only `tests/conftest.py` names the PostgreSQL URL variable, so every PostgreSQL test gets its URL
from the one function there, which fails a test that `-m postgresql` would not select.

A computed environment key or a loop over `os.environ` gets past this check; only deliberate
obfuscation does that.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
OWNERS = frozenset({TESTS_ROOT / "conftest.py", Path(__file__).resolve()})
POSTGRESQL_URL_VARIABLE = "TEST_DATABASE_URL"
POSTGRESQL_URL_VARIABLE_BYTES = POSTGRESQL_URL_VARIABLE.encode()
DOCUMENTED_NODES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _docstrings(tree: ast.AST) -> set[int]:
    documented = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, DOCUMENTED_NODES) and body and isinstance(body[0], ast.Expr):
            documented.add(id(body[0].value))
    return documented


def url_variable_mentions(root: Path) -> list[str]:
    mentions = []
    for path in sorted(root.rglob("*.py")):
        if path in OWNERS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        documentation = _docstrings(tree)
        for node in ast.walk(tree):
            names_variable = isinstance(node, ast.Constant) and (
                (isinstance(node.value, str) and POSTGRESQL_URL_VARIABLE in node.value)
                or (isinstance(node.value, bytes) and POSTGRESQL_URL_VARIABLE_BYTES in node.value)
            )
            if names_variable and id(node) not in documentation:
                mentions.append(f"{path.relative_to(root)}:{node.lineno}")
    return mentions


def test_only_conftest_names_the_postgresql_url_variable():
    assert url_variable_mentions(TESTS_ROOT) == []
