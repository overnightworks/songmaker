#!/usr/bin/env bash
# Fails when a duplicated test helper name is new, defined in more modules, or fell below the baseline.
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 - "$script_dir/.." "$@" <<'PY'
"""Hold each helper name defined in more than one test module, per tree, to its baseline."""

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
    r"(?:\s*:[^=\n]+)?\s*=\s*(?:(?:async\s+)?(?:"
    r"function\b|(?:<[^;\n]+>\s*)?\([^()]*\)\s*(?::[^=;\n]+)?=>"
    r"|[A-Za-z_$][\w$]*\s*=>)|\{)",
    re.MULTILINE,
)


def frontend_names(path):
    return {
        match["function"] or match["const"]
        for match in FRONTEND_HELPER.finditer(path.read_text())
    }


def duplicate_modules(tree, paths, read_names):
    definitions = defaultdict(set)
    for path in paths:
        for name in read_names(path):
            definitions[name].add(path)
    return {
        (tree, name): len(files) for name, files in definitions.items() if len(files) > 1
    }


def read_baseline(baseline):
    entries = {}
    for line in baseline.read_text().splitlines():
        fields = line.split()
        if (
            len(fields) != 3
            or fields[0] not in ("backend", "frontend")
            or not fields[2].isdecimal()
            or int(fields[2]) < 2
            or tuple(fields[:2]) in entries
        ):
            raise SystemExit(f"Expected 'tree name modules' lines (modules >= 2) in {baseline}: {line!r}")
        entries[tuple(fields[:2])] = int(fields[2])
    return entries


def describe(entry, stored, current):
    return f"{entry[0]} {entry[1]}: stored {stored}, current {current}"


def main():
    root = Path(sys.argv[1]).resolve()
    arguments = sys.argv[2:]
    if arguments not in ([], ["--update"]):
        raise SystemExit("Usage: test_helper_ratchet.sh [--update]")
    update = arguments == ["--update"]
    baseline = root / "scripts/test_helper_ratchet.txt"
    current = {
        **duplicate_modules("backend", (root / "tests").rglob("*.py"), backend_names),
        **duplicate_modules("frontend", (root / "frontend/src").rglob("*.test.ts"), frontend_names),
    }
    if not baseline.exists():
        raise SystemExit(f"Missing baseline {baseline}")
    stored = read_baseline(baseline)
    grown = sorted(entry for entry, count in current.items() if count > stored.get(entry, 0))
    stale = sorted(entry for entry, count in stored.items() if current.get(entry, 0) < count)
    for entry in grown:
        print(describe(entry, stored.get(entry, 0), current[entry]))
    for entry in stale:
        print(describe(entry, stored[entry], current.get(entry, 0)) + " (stale)")
    if grown:
        raise SystemExit("Duplicate test helpers increased; consolidate before updating the baseline.")
    if stale and not update:
        raise SystemExit("Duplicate test helpers fell; run scripts/test_helper_ratchet.sh --update.")
    if update and stale:
        baseline.write_text("".join(f"{tree} {name} {count}\n" for (tree, name), count in sorted(current.items())))
        print("Updated test helper baseline.")
    print(f"{len(current)} duplicated helper names")


main()
PY
