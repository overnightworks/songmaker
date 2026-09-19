"""Find module symbols without a reference in another production Python file.

This conservative name scan is not a reachability proof: same-name references,
including forward annotations and dynamic lookup strings, can keep a symbol alive.
Allow entries are exact src-relative path:name pairs followed by # and a reason.
Local helpers also need an entry because same-file uses do not satisfy this gate.
"""

from __future__ import annotations

import argparse
import ast
import re
from collections import defaultdict
from pathlib import Path


def declarations(tree: ast.Module) -> set[str]:
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(
                target.id
                for target in targets
                if isinstance(target, ast.Name) and target.id.isupper()
            )
    return names


def references(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.update(re.findall(r"\b[A-Za-z_]\w*\b", node.value))
    return names


def unreferenced_symbols(source: Path) -> set[str]:
    symbols = {}
    users = defaultdict(set)
    paths = sorted(
        path
        for path in source.rglob("*.py")
        if "tests" not in path.relative_to(source).parts and not path.name.startswith("test_")
    )
    if not paths:
        raise ValueError(f"No production Python files found in {source}")
    for path in paths:
        tree = ast.parse(path.read_text(), filename=str(path))
        symbols[path] = declarations(tree)
        for name in references(tree):
            users[name].add(path)
    return {
        f"{path.relative_to(source).as_posix()}:{name}"
        for path, names in symbols.items()
        for name in names
        if not users[name] - {path}
    }


def read_allowlist(path: Path) -> set[str]:
    entries = set()
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        symbol, separator, reason = line.partition("#")
        symbol = symbol.strip()
        if not separator or not reason.strip() or ":" not in symbol or symbol in entries:
            raise ValueError(f"{path}:{number}: expected unique path:name # reason")
        entries.add(symbol)
    return entries


def main() -> int:
    repository = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=repository / "src")
    parser.add_argument("--allow", type=Path, default=repository / "scripts/dead-symbols.allow")
    args = parser.parse_args()
    try:
        missing = unreferenced_symbols(args.source) - read_allowlist(args.allow)
    except (OSError, SyntaxError, ValueError) as error:
        print(error)
        return 1
    for symbol in sorted(missing):
        print(f"No external production reference: {symbol}")
    if missing:
        return 1
    print("Dead-symbol gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
