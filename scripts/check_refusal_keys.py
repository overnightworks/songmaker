"""CI check that every server refusal names a plain catalog key with exactly its gaps.

Run from the project root:

    python scripts/check_refusal_keys.py

It walks `src/songmaker_cli` for every `Refusal(...)` call and every call of
`songmaker_cli.words.text` (by import, or as the `words.text` attribute; SQLAlchemy's
`text` is another function and is not counted). It reads the entries of the generated
`words.py` and requires, for each call:

* the key is a string literal that is a plain entry of the source language, not a plural
  family;
* the keywords are exactly the sentence's gaps, with no `**` spread.

A `Refusal` call also needs an int literal status and a key of the form
`<resource>Refusal.<reason>`.

`words.py` (generated) and `refusals.py` (which forwards the key of its caller to `text`)
are not walked.
"""
# ruff: noqa: T201 - this check reports its violations on stdout

from __future__ import annotations

import argparse
import ast
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Final

DEFAULT_SOURCE: Final = "src/songmaker_cli"
WORDS_FILE: Final = "words.py"
REFUSALS_FILE: Final = "refusals.py"
WORDS_MODULE: Final = "songmaker_cli.words"
PACKAGE_MODULE: Final = "songmaker_cli"
WORDS_NAME: Final = "words"
TEXT_NAME: Final = "text"
REFUSAL_NAME: Final = "Refusal"
REFUSAL_KEY_PATTERN: Final = re.compile(r"^[a-z][A-Za-z0-9]*Refusal\.[a-z][A-Za-z0-9]*$")
KEY_INDEX_OF_TEXT: Final = 1
KEY_INDEX_OF_REFUSAL: Final = 1


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    message: str


def load_plain_gaps(words_file: Path) -> dict[str, frozenset[str]]:
    """Map each plain entry of the source language to the names of its gaps."""
    spec = importlib.util.spec_from_file_location("generated_words", words_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {words_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source_entries = module.WORDS[module.SOURCE_LANGUAGE]
    return {
        key: frozenset(name for _, name, _, _ in Formatter().parse(sentence) if name is not None)
        for key, sentence in source_entries.items()
        if isinstance(sentence, str)
    }


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return None if base is None else f"{base}.{node.attr}"
    return None


@dataclass(frozen=True)
class WordsBindings:
    """The names a module binds to `songmaker_cli.words.text` and to the words module."""

    functions: frozenset[str]
    modules: frozenset[str]

    def is_text_call(self, call: ast.Call) -> bool:
        if isinstance(call.func, ast.Name):
            return call.func.id in self.functions
        if isinstance(call.func, ast.Attribute) and call.func.attr == TEXT_NAME:
            return _dotted(call.func.value) in self.modules
        return False


def _from_import_names(tree: ast.Module, module: str, name: str) -> set[str]:
    return {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == module
        for alias in node.names
        if alias.name == name
    }


def _import_names(tree: ast.Module, module: str) -> set[str]:
    return {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == module
    }


def words_bindings(tree: ast.Module) -> WordsBindings:
    return WordsBindings(
        functions=frozenset(_from_import_names(tree, WORDS_MODULE, TEXT_NAME)),
        modules=frozenset(
            _from_import_names(tree, PACKAGE_MODULE, WORDS_NAME) | _import_names(tree, WORDS_MODULE)
        ),
    )


def _is_refusal_call(call: ast.Call) -> bool:
    if isinstance(call.func, ast.Name):
        return call.func.id == REFUSAL_NAME
    return isinstance(call.func, ast.Attribute) and call.func.attr == REFUSAL_NAME


def _literal_key(call: ast.Call, key_index: int) -> str | None:
    if len(call.args) <= key_index:
        return None
    key = call.args[key_index]
    if isinstance(key, ast.Constant) and isinstance(key.value, str):
        return key.value
    return None


def _gap_problem(call: ast.Call, expected: frozenset[str]) -> str | None:
    if any(keyword.arg is None for keyword in call.keywords):
        return "gaps are passed with a ** spread; name each one"
    given = {keyword.arg for keyword in call.keywords}
    missing, unexpected = sorted(expected - given), sorted(given - expected)
    if missing or unexpected:
        return f"gaps differ from the sentence's: missing {missing}, unexpected {unexpected}"
    return None


def _refusal_problem(call: ast.Call, key: str) -> str | None:
    status = call.args[0]
    if not (isinstance(status, ast.Constant) and type(status.value) is int):
        return "the status is not an int literal"
    if not REFUSAL_KEY_PATTERN.match(key):
        return f"{key!r} does not match <resource>Refusal.<reason>"
    return None


def call_problem(
    call: ast.Call, key_index: int, plain: dict[str, frozenset[str]], *, is_refusal: bool
) -> str | None:
    key = _literal_key(call, key_index)
    if key is None:
        return "the key is not a string literal passed as a positional argument"
    if key not in plain:
        return f"{key!r} is not a plain entry of words.py (a plural family is not a refusal key)"
    problem = _gap_problem(call, plain[key])
    if problem is not None or not is_refusal:
        return problem
    return _refusal_problem(call, key)


def check_file(
    path: Path, shown: str, plain: dict[str, frozenset[str]]
) -> tuple[list[Violation], int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=shown)
    bindings = words_bindings(tree)
    violations: list[Violation] = []
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_refusal_call(node):
            problem = call_problem(node, KEY_INDEX_OF_REFUSAL, plain, is_refusal=True)
        elif bindings.is_text_call(node):
            problem = call_problem(node, KEY_INDEX_OF_TEXT, plain, is_refusal=False)
        else:
            continue
        checked += 1
        if problem is not None:
            violations.append(Violation(shown, node.lineno, problem))
    return violations, checked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", default=DEFAULT_SOURCE, help="package to scan")
    source = Path(parser.parse_args(argv).source)
    words_file = source / WORDS_FILE
    if not words_file.is_file():
        print(f"error: {words_file} does not exist", file=sys.stderr)
        return 2
    plain = load_plain_gaps(words_file)
    violations: list[Violation] = []
    checked = 0
    for path in sorted(source.rglob("*.py")):
        if path in (words_file, source / REFUSALS_FILE):
            continue
        found, count = check_file(path, str(path), plain)
        violations.extend(found)
        checked += count
    for violation in violations:
        print(f"{violation.path}:{violation.line}: {violation.message}")
    print(f"checked: refusal and text calls={checked}, violations={len(violations)}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
