"""CI smell-checker for the no-silent-fallbacks invariants.

Run from the project root:

    python scripts/check_no_silent_fallbacks.py src/

Each rule is a regex over a physical line or an AST walk, scoped to the
files whose role it governs. There is no exemption list: a hit is a
defect to fix, and a legitimate exception is expressed in the code
itself — as the file's role (a settings module owns env reads,
``env_override.py`` owns the one save-and-restore idiom) or as a named
type (``ComputedTimestamp`` owns a timestamp whose None is real;
``getattr(..., None)`` is the honest absent answer, while a literal
string or number default invents a value the code cannot know).

Every run prints how many sites each rule inspected, so a clean report
is distinguishable from a rule that never ran.

The rules encode the lessons of the no-silent-fallbacks-v2 cleanup:

* W1 — env vars are read once via Settings, never via os.environ.* in
  application code.
* W2 — domain dicts go through typed Pydantic models. ``next(iter(...))``
  on dict-like collections is forbidden (the 2026-04-08 surface).
* W2 — generic ``dict[str, Any]`` in function parameters masks domain
  shapes. Use a Pydantic model. Return annotations and nested forms are
  not this rule. Exempt: ``cowriter/tools.py`` — ``execute_cowriter_tool``
  dispatches raw MCP tool-call JSON across ten heterogeneous handlers
  whose only shared shape is the per-tool JSON Schema already carried in
  ``CowriterTool.parameters``; turning that into ten named argument
  models is a multi-file rework, tracked as a follow-up rather than
  fixed by this checker slice.
* W3 — silent dict-fallback patterns like ``cfg.get("key", "default")``
  on domain variables hide config drift.
* W4 — ``Optional`` on timestamp fields lies about non-null DB columns.
* getattr with a literal default invents a value the code cannot know.
  No default, a named constant, or ``None`` is honest.
* Engine isolation — ``acestep_engine`` / ``audio_engine`` /
  ``acestep_worker`` must never import from ``songmaker_cli`` (the
  dependency flows one way; violating this crashed the worker container
  during W1).
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

PACKAGE_SETTINGS_MODULE = r"^src/[^/]+/settings\.py$"
ALEMBIC_ENV_MODULE = r"^src/[^/]+/db/migrations/env\.py$"
ENV_OVERRIDE_MODULE = r"^src/[^/]+/env_override\.py$"
COWRITER_TOOL_DISPATCH_MODULE = r"^src/songmaker_cli/cowriter/tools\.py$"

SITE_UNIT_FILES: Final = "files"
SITE_UNIT_FUNCTIONS: Final = "functions"
SITE_UNIT_CALLS: Final = "calls"
CHECKED_LABEL: Final = "checked"
DICT_ANY_IN_SIGNATURE: Final = "dict-any-in-signature"
GETATTR_LITERAL_DEFAULT: Final = "getattr-literal-default"
GETATTR_NAME: Final = "getattr"
BUILTINS_MODULE: Final = "builtins"
GETATTR_DEFAULT_KEYWORD: Final = "default"
DICT_TYPE_NAMES: Final = frozenset({"dict", "Dict"})
STR_TYPE_NAME: Final = "str"
ANY_TYPE_NAME: Final = "Any"

InspectTree = Callable[[ast.AST, Sequence[str]], tuple[list[tuple[int, str]], int]]


@dataclass
class Rule:
    name: str
    description: str
    pattern: str | None = None
    inspect_tree: InspectTree | None = None
    site_unit: str = SITE_UNIT_FILES
    paths: tuple[str, ...] = ()
    exempt_roles: tuple[str, ...] = ()
    _compiled: re.Pattern[str] | None = field(init=False)
    _exempt: tuple[re.Pattern[str], ...] = field(init=False)

    def __post_init__(self) -> None:
        self._compiled = re.compile(self.pattern) if self.pattern is not None else None
        self._exempt = tuple(re.compile(role) for role in self.exempt_roles)

    def applies_to(self, rel_path: str) -> bool:
        if any(role.search(rel_path) for role in self._exempt):
            return False
        if not self.paths:
            return True
        return any(rel_path.startswith(p) for p in self.paths)


def _source_line(lines: Sequence[str], lineno: int) -> str:
    if 1 <= lineno <= len(lines):
        return lines[lineno - 1]
    return ""


def _name_or_attr_is(node: ast.expr, name: str) -> bool:
    if isinstance(node, ast.Name):
        return node.id == name
    if isinstance(node, ast.Attribute):
        return node.attr == name
    return False


def _is_dict_type(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id in DICT_TYPE_NAMES
    if isinstance(node, ast.Attribute):
        return node.attr in DICT_TYPE_NAMES
    return False


def _is_dict_str_any(node: ast.expr) -> bool:
    if not isinstance(node, ast.Subscript):
        return False
    if not _is_dict_type(node.value):
        return False
    slice_node = node.slice
    if not isinstance(slice_node, ast.Tuple) or len(slice_node.elts) != 2:
        return False
    key_node, value_node = slice_node.elts
    return (
        _name_or_attr_is(key_node, STR_TYPE_NAME)
        and _name_or_attr_is(value_node, ANY_TYPE_NAME)
    )


def _bitor_alternatives(node: ast.expr) -> list[ast.expr]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return [*_bitor_alternatives(node.left), *_bitor_alternatives(node.right)]
    return [node]


def _annotation_flags_dict_str_any(node: ast.expr | None) -> bool:
    if node is None:
        return False
    return any(_is_dict_str_any(alternative) for alternative in _bitor_alternatives(node))


def _iter_parameters(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterable[ast.arg]:
    args = fn.args
    yield from args.posonlyargs
    yield from args.args
    if args.vararg is not None:
        yield args.vararg
    yield from args.kwonlyargs
    if args.kwarg is not None:
        yield args.kwarg


def _inspect_dict_any_in_signature(
    tree: ast.AST, lines: Sequence[str],
) -> tuple[list[tuple[int, str]], int]:
    hits: list[tuple[int, str]] = []
    functions = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        functions += 1
        for param in _iter_parameters(node):
            if _annotation_flags_dict_str_any(param.annotation):
                lineno = param.lineno
                hits.append((lineno, _source_line(lines, lineno)))
    return hits, functions


def _is_getattr_func(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return func.id == GETATTR_NAME
    if isinstance(func, ast.Attribute) and func.attr == GETATTR_NAME:
        return isinstance(func.value, ast.Name) and func.value.id == BUILTINS_MODULE
    return False


def _getattr_default(node: ast.Call) -> ast.expr | None:
    if len(node.args) >= 3:
        return node.args[2]
    for keyword in node.keywords:
        if keyword.arg == GETATTR_DEFAULT_KEYWORD:
            return keyword.value
    return None


def _is_signed_numeric_constant(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.UAdd, ast.USub))
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, (int, float))
    )


def _is_non_none_constant(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return node.value is not None
    return _is_signed_numeric_constant(node)


def _inspect_getattr_literal_default(
    tree: ast.AST, lines: Sequence[str],
) -> tuple[list[tuple[int, str]], int]:
    hits: list[tuple[int, str]] = []
    calls = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_getattr_func(node.func):
            continue
        calls += 1
        default = _getattr_default(node)
        if default is not None and _is_non_none_constant(default):
            lineno = node.lineno
            hits.append((lineno, _source_line(lines, lineno)))
    return hits, calls


RULES: list[Rule] = [
    Rule(
        name="env-read-outside-settings",
        pattern=(
            r"os\.(environ\.(get|pop|setdefault)|getenv)\("
            r"|^(?!\s*del\s).*os\.environ\[[^\]]+\](?!\s*[-+*/|&^]?=[^=])"
        ),
        description=(
            "Env vars must be read via the settings module of the package "
            "that needs them — including the reads that carry a fallback "
            "(get/pop/setdefault). Three roles are out of scope: the "
            "package's settings.py, the Alembic migration env.py (it runs "
            "before Settings exists), and env_override.py, which owns the "
            "one idiom that legitimately reads and writes live process "
            "state. Plain writes and deletes are process state, not "
            "configuration, and are not reported."
        ),
        exempt_roles=(
            PACKAGE_SETTINGS_MODULE,
            ALEMBIC_ENV_MODULE,
            ENV_OVERRIDE_MODULE,
        ),
    ),
    Rule(
        name="next-iter-fallback",
        pattern=r"next\(iter\(",
        description=(
            "next(iter(some_dict)) returns whatever happens to come first "
            "in dict insertion order — exactly the 2026-04-08 surface. "
            "Use an explicit lookup or raise."
        ),
    ),
    Rule(
        name="dict-get-domain-fallback",
        pattern=(
            r"(config|params|defaults|preset_params|generation_params)"
            r"\.get\([^,)]+,\s*([\"'\[{]|\d|False|True)"
        ),
        description=(
            "Silent dict-get fallback on a domain variable. Use a typed "
            "Pydantic model whose missing fields are explicit None."
        ),
    ),
    Rule(
        name=DICT_ANY_IN_SIGNATURE,
        inspect_tree=_inspect_dict_any_in_signature,
        site_unit=SITE_UNIT_FUNCTIONS,
        description=(
            "Function signature uses dict[str, Any] for what should be a "
            "domain object. Define a Pydantic model."
        ),
        exempt_roles=(COWRITER_TOOL_DISPATCH_MODULE,),
    ),
    Rule(
        name="optional-on-default-utcnow-column",
        pattern=r"(created_at|updated_at|attempted_at|expires_at):\s*(str|datetime)\s*\|\s*None",
        description=(
            "Timestamp field marked Optional but the underlying DB column "
            "is NOT NULL with default=_utcnow. Drop the | None and the "
            "matching `if x else None` in from_orm. A timestamp the "
            "response computes, whose None is a real answer, is declared "
            "as ComputedTimestamp (api_models/fields.py)."
        ),
    ),
    Rule(
        name="engine-isolation-violation",
        pattern=r"^\s*(from|import)\s+songmaker_cli",
        description=(
            "Engine packages must not import from songmaker_cli — the "
            "dependency flows one way. Violating this crashed the worker "
            "container during W1."
        ),
        paths=(
            "src/acestep_engine/",
            "src/audio_engine/",
            "src/acestep_worker/",
        ),
    ),
    Rule(
        name=GETATTR_LITERAL_DEFAULT,
        inspect_tree=_inspect_getattr_literal_default,
        site_unit=SITE_UNIT_CALLS,
        description=(
            "getattr with a literal default invents a value the code cannot "
            "know. Omit the default so a missing attribute raises, pass a "
            "named constant, or pass None as the honest absent answer."
        ),
    ),
]


@dataclass
class _Hit:
    rule: Rule
    rel_path: str
    lineno: int
    line: str


def _try_parse(text: str, filename: str) -> ast.AST | None:
    try:
        return ast.parse(text, filename=filename)
    except SyntaxError:
        return None


def _scan_file(
    path: Path, rel_path: str, rules: Iterable[Rule],
) -> tuple[list[_Hit], dict[str, int]]:
    hits: list[_Hit] = []
    applicable = [rule for rule in rules if rule.applies_to(rel_path)]
    counts = {rule.name: 0 for rule in applicable}
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return hits, counts
    lines = text.splitlines()
    for lineno, line in enumerate(lines, start=1):
        for rule in applicable:
            compiled = rule._compiled
            if compiled is not None and compiled.search(line):
                hits.append(_Hit(rule=rule, rel_path=rel_path, lineno=lineno, line=line))
    for rule in applicable:
        if rule._compiled is not None:
            counts[rule.name] = 1
    tree = _try_parse(text, rel_path)
    if tree is not None:
        for rule in applicable:
            if rule.inspect_tree is None:
                continue
            ast_hits, n_sites = rule.inspect_tree(tree, lines)
            counts[rule.name] = n_sites
            for lineno, line in ast_hits:
                hits.append(_Hit(rule=rule, rel_path=rel_path, lineno=lineno, line=line))
    return hits, counts


def _walk_python_files(roots: Iterable[Path], project_root: Path) -> Iterable[tuple[Path, str]]:
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if any(part == "__pycache__" for part in path.parts):
                continue
            rel = path.relative_to(project_root).as_posix()
            yield path, rel


def _checked_summary(checked: dict[str, int]) -> str:
    parts = [
        f"{rule.name}={checked[rule.name]} {rule.site_unit}"
        for rule in RULES
    ]
    return f"{CHECKED_LABEL}: {', '.join(parts)}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "roots", nargs="*", default=["src/"],
        help="Directories to scan (default: src/)",
    )
    args = parser.parse_args(argv)

    project_root = Path.cwd()
    roots = [project_root / r for r in args.roots]
    missing = [r for r in roots if not r.exists()]
    if missing:
        for r in missing:
            print(f"error: {r} does not exist", file=sys.stderr)
        return 2

    all_hits: list[_Hit] = []
    checked = {rule.name: 0 for rule in RULES}
    for path, rel in _walk_python_files(roots, project_root):
        hits, counts = _scan_file(path, rel, RULES)
        all_hits.extend(hits)
        for name, n in counts.items():
            checked[name] += n

    summary = _checked_summary(checked)
    if not all_hits:
        print(f"No silent-fallback smells in {', '.join(str(r) for r in roots)}.")
        print(summary)
        return 0

    by_rule: dict[str, list[_Hit]] = {}
    for hit in all_hits:
        by_rule.setdefault(hit.rule.name, []).append(hit)

    for name in sorted(by_rule):
        hits = by_rule[name]
        rule = hits[0].rule
        print(f"\n[{name}] {len(hits)} violation(s)")
        print(f"  {rule.description}")
        for hit in hits:
            print(f"    {hit.rel_path}:{hit.lineno}: {hit.line.strip()}")

    print(f"\n{len(all_hits)} total violation(s) across {len(by_rule)} rule(s).")
    print(summary)
    return 1


if __name__ == "__main__":
    sys.exit(main())
