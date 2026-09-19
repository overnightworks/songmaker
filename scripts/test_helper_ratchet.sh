#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 - "$script_dir/.." "$@" <<'PY'
"""Cap helper names defined in more than one test module, separately per tree."""

import ast
import re
import sys
from collections import defaultdict
from pathlib import Path


def backend_names(path):
    return {
        node.name
        for node in ast.parse(path.read_text(), filename=str(path)).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("_")
    }


FRONTEND_HELPER = re.compile(
    r"^(?:export\s+)?(?:async\s+)?function\s+(?P<function>[A-Za-z_$][\w$]*)"
    r"|^(?:export\s+)?const\s+(?P<const>[A-Za-z_$][\w$]*)"
    r"(?:\s*:[^=\n]+)?\s*=\s*(?:async\s+)?(?:"
    r"function\b|(?:<[^;\n]+>\s*)?\([^()]*\)\s*(?::[^=;\n]+)?=>"
    r"|[A-Za-z_$][\w$]*\s*=>)",
    re.MULTILINE,
)


def frontend_names(path):
    return {
        match["function"] or match["const"]
        for match in FRONTEND_HELPER.finditer(path.read_text())
    }


def duplicate_count(paths, read_names):
    definitions = defaultdict(set)
    for path in paths:
        for name in read_names(path):
            definitions[name].add(path)
    return sum(len(files) > 1 for files in definitions.values())


def main():
    root = Path(sys.argv[1]).resolve()
    arguments = sys.argv[2:]
    if arguments not in ([], ["--update"]):
        raise SystemExit("Usage: test_helper_ratchet.sh [--update]")
    baseline = root / "scripts/test_helper_ratchet.txt"
    counts = (
        duplicate_count((root / "tests").rglob("*.py"), backend_names),
        duplicate_count((root / "frontend/src").rglob("*.test.ts"), frontend_names),
    )
    if not baseline.exists() and arguments == ["--update"]:
        limits = counts
    else:
        values = baseline.read_text().split()
        if len(values) != 2 or any(not value.isdecimal() for value in values):
            raise SystemExit(f"Expected two nonnegative counts in {baseline}")
        limits = tuple(map(int, values))
    for name, count, limit in zip(("backend", "frontend"), counts, limits):
        print(f"{name}: {count} duplicate helper names (limit {limit})")
    if any(count > limit for count, limit in zip(counts, limits)):
        raise SystemExit("Duplicate test helpers increased; consolidate before updating the baseline.")
    if arguments == ["--update"] and (not baseline.exists() or counts != limits):
        baseline.write_text(f"{counts[0]} {counts[1]}\n")
        print("Updated test helper baseline.")


main()
PY
