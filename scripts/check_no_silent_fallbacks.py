"""CI smell-checker for the no-silent-fallbacks invariants.

Run from the project root:

    python scripts/check_no_silent_fallbacks.py src/

Each rule is a regex with a per-rule allowlist of legitimate exceptions.
A new instance of any pattern outside the allowlist fails the build —
the contributor must either fix the code or extend the allowlist with a
brief justification in the commit message.

The rules encode the lessons of the no-silent-fallbacks-v2 cleanup:

* W1 — env vars are read once via Settings, never via os.environ.* in
  application code.
* W2 — domain dicts go through typed Pydantic models. ``next(iter(...))``
  on dict-like collections is forbidden (the 2026-04-08 surface).
* W2 — generic ``dict[str, Any]`` in function signatures masks domain
  shapes. Use a Pydantic model.
* W3 — silent dict-fallback patterns like ``cfg.get("key", "default")``
  on domain variables hide config drift.
* W4 — ``Optional`` on timestamp fields lies about non-null DB columns.
* Engine isolation — ``acestep_engine`` / ``audio_engine`` /
  ``acestep_worker`` must never import from ``songmaker_cli`` (the
  dependency flows one way; violating this crashed the worker container
  during W1).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Rule:
    name: str
    pattern: str
    description: str
    paths: tuple[str, ...] = ()
    allowlist: set[str] = field(default_factory=set)
    _compiled: re.Pattern[str] = field(init=False)

    def __post_init__(self) -> None:
        self._compiled = re.compile(self.pattern)

    def applies_to(self, rel_path: str) -> bool:
        if not self.paths:
            return True
        return any(rel_path.startswith(p) for p in self.paths)

    def is_allowlisted(self, rel_path: str, lineno: int) -> bool:
        if rel_path in self.allowlist:
            return True
        return f"{rel_path}:{lineno}" in self.allowlist


RULES: list[Rule] = [
    Rule(
        name="env-read-outside-settings",
        pattern=r"os\.(environ\.get|environ\[|getenv)\(",
        description=(
            "Env vars must be read via Settings (settings.py / "
            "acestep_engine/settings.py / acestep_worker/settings.py)."
        ),
        allowlist={
            "src/songmaker_cli/settings.py",
            "src/songmaker_cli/db/migrations/env.py",
            "src/songmaker_cli/scoring/audiobox_aesthetics.py",
            "src/songmaker_cli/claude/provider.py",
            "src/acestep_worker/settings.py",
            "src/acestep_worker/subprocess_runner.py",
            "src/acestep_engine/settings.py",
        },
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
        name="dict-any-in-signature",
        pattern=r"def\s+\w+\([^)]*:\s*(dict|Dict)\[str,\s*Any\]",
        description=(
            "Function signature uses dict[str, Any] for what should be a "
            "domain object. Define a Pydantic model."
        ),
        allowlist={
            "src/acestep_worker/task_store.py",
        },
    ),
    Rule(
        name="optional-on-default-utcnow-column",
        pattern=r"(created_at|updated_at|attempted_at|expires_at):\s*(str|datetime)\s*\|\s*None",
        description=(
            "Timestamp field marked Optional but the underlying DB column "
            "is NOT NULL with default=_utcnow. Drop the | None and the "
            "matching `if x else None` in from_orm."
        ),
        allowlist={
            # GenerationResponse.expires_at is a computed field, not a DB
            # column — returns None for picked/kept generations since they
            # never expire. Legitimate nullable.
            "src/songmaker_cli/api_models/songs.py:140",
            "src/songmaker_cli/api_models/songs.py:182",
            # An absent memory row is represented as an empty scope with no
            # update timestamp; this is a computed response field.
            "src/songmaker_cli/api_models/settings.py:237",
        },
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
]


@dataclass
class _Hit:
    rule: Rule
    rel_path: str
    lineno: int
    line: str


def _scan_file(path: Path, rel_path: str, rules: Iterable[Rule]) -> list[_Hit]:
    hits: list[_Hit] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return hits
    for lineno, line in enumerate(text.splitlines(), start=1):
        for rule in rules:
            if not rule.applies_to(rel_path):
                continue
            if rule.is_allowlisted(rel_path, lineno):
                continue
            if rule._compiled.search(line):
                hits.append(_Hit(rule=rule, rel_path=rel_path, lineno=lineno, line=line))
    return hits


def _walk_python_files(roots: Iterable[Path], project_root: Path) -> Iterable[tuple[Path, str]]:
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if any(part == "__pycache__" for part in path.parts):
                continue
            rel = path.relative_to(project_root).as_posix()
            yield path, rel


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
    for path, rel in _walk_python_files(roots, project_root):
        all_hits.extend(_scan_file(path, rel, RULES))

    if not all_hits:
        print(f"No silent-fallback smells in {', '.join(str(r) for r in roots)}.")
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
    return 1


if __name__ == "__main__":
    sys.exit(main())
