"""Run mypy, ruff's ANN401 and a nested-Any scan over src/ against the committed baseline.

ANN401 covers a direct `Any` parameter or return; the nested-Any scan covers the rest of the
contract's debt: `Any` as the value type of a `dict[str, Any]` anywhere in an annotation,
alias or field, however deep inside another generic. Its finding names the enclosing class or
function (`module` at top level), so a repeated one repeats its line.

A finding is `path :: code :: message`, without its line number, so edits above it do not
change it; a repeated finding repeats its line. The check is red on a finding the baseline
lacks and on a baseline entry no longer found, so the baseline only shrinks.
"""
# ruff: noqa: T201 - this check reports its findings on stdout

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = Path(__file__).with_suffix(".txt")
REGENERATE = "python scripts/check_type_findings.py --regenerate"
SEPARATOR = " :: "
MYPY_LINE = re.compile(r"^(?P<path>[^:]+):\d+: error: (?P<message>.*) {2}\[(?P<code>[\w-]+)\]$")
LINE_REFERENCE = re.compile(r"\bline \d+")

type ToolRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


def run_tool(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True)  # noqa: S603 - the commands are built here from sys.executable and constants


def mypy_findings(root: Path, run: ToolRunner) -> list[str]:
    done = run(
        [sys.executable, "-m", "mypy", "--no-error-summary", "--show-error-codes", "--no-pretty"],
        root,
    )
    if done.returncode not in (0, 1):
        sys.exit(f"mypy failed to run:\n{done.stdout}{done.stderr}")
    findings = []
    for line in done.stdout.splitlines():
        match = MYPY_LINE.match(line)
        if match:
            message = LINE_REFERENCE.sub("line N", match["message"])
            findings.append(SEPARATOR.join((match["path"], match["code"], message)))
    return findings


def ann401_findings(root: Path, run: ToolRunner) -> list[str]:
    done = run(
        [sys.executable, "-m", "ruff", "check", "--select", "ANN401"]
        + ["--output-format=json", "src/"],
        root,
    )
    if done.returncode not in (0, 1):
        sys.exit(f"ruff failed to run:\n{done.stdout}{done.stderr}")
    return [
        SEPARATOR.join(
            (str(Path(item["filename"]).relative_to(root)), item["code"], item["message"])
        )
        for item in json.loads(done.stdout)
    ]


def is_any(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "Any") or (
        isinstance(node, ast.Attribute) and node.attr == "Any"
    )


def is_dict_of_any(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "dict"
        and isinstance(node.slice, ast.Tuple)
        and len(node.slice.elts) == 2
        and is_any(node.slice.elts[1])
    )


def nested_any_in(tree: ast.AST, scope: tuple[str, ...] = ()) -> list[str]:
    scopes = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            scopes += nested_any_in(node, (*scope, node.name))
        else:
            scopes += nested_any_in(node, scope)
        if is_dict_of_any(node):
            scopes.append(".".join(scope) or "module")
    return scopes


def nested_any_findings(root: Path) -> list[str]:
    return [
        SEPARATOR.join((str(path.relative_to(root)), "nested-any", f"dict[str, Any] in `{scope}`"))
        for path in sorted((root / "src").rglob("*.py"))
        for scope in nested_any_in(ast.parse(path.read_text()))
    ]


def current_findings(root: Path, run: ToolRunner) -> Counter[str]:
    return Counter(
        mypy_findings(root, run) + ann401_findings(root, run) + nested_any_findings(root)
    )


def main(argv: Sequence[str], root: Path, baseline: Path, run: ToolRunner) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--regenerate", action="store_true", help="rewrite the baseline from today's findings"
    )
    found = current_findings(root, run)
    if parser.parse_args(argv).regenerate:
        baseline.write_text("".join(f"{line}\n" for line in sorted(found.elements())))
        print(f"type_check: baseline holds {found.total()} findings")
        return 0
    known = Counter(baseline.read_text().splitlines())
    new, fixed = found - known, known - found
    for line in sorted(new.elements()):
        print(f"type_check: NEW {line}")
    for line in sorted(fixed.elements()):
        print(f"type_check: FIXED but still in the baseline {line}")
    if new or fixed:
        print(f"type_check: fix the new findings; after a real fix run: {REGENERATE}")
        return 1
    print(f"type_check: {found.total()} findings, all in the baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], ROOT, BASELINE, run_tool))
