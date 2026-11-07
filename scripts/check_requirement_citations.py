"""CI guard: every requirement a docs page defines is cited by a test, and only those.

A requirement is a ``### REQ-<AREA>-<NN>:`` heading in ``docs/*.md``. A test file
cites it by writing the ID anywhere in ``tests/**/*.py``,
``frontend/src/**/*.test.ts`` or ``frontend/e2e/**/*.ts``; a mention in a
production file counts as no citation.

Run from the project root:

    python scripts/check_requirement_citations.py
"""
# ruff: noqa: T201 - this check reports citation gaps on stderr

from __future__ import annotations

import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIRECTORY = REPOSITORY_ROOT / "docs"
TEST_GLOBS = (
    ("tests", "**/*.py"),
    ("frontend/src", "**/*.test.ts"),
    ("frontend/e2e", "**/*.ts"),
)
REQUIREMENT_ID = r"REQ-[A-Z]+-\d+"
HEADING_PATTERN = re.compile(rf"^### ({REQUIREMENT_ID}):", re.MULTILINE)
CITATION_PATTERN = re.compile(REQUIREMENT_ID)


def _occurrences(texts: Mapping[Path, str], pattern: re.Pattern[str]) -> dict[str, list[Path]]:
    """Map each ID to the file of every occurrence (a file repeats per heading)."""
    found: dict[str, list[Path]] = defaultdict(list)
    for path, text in texts.items():
        for requirement_id in pattern.findall(text):
            found[requirement_id].append(path)
    return found


def _paths(paths: Iterable[Path]) -> str:
    return ", ".join(str(path) for path in dict.fromkeys(paths))


def find_problems(page_texts: Mapping[Path, str], test_texts: Mapping[Path, str]) -> list[str]:
    """Return one message per uncited, unknown or doubly defined requirement ID."""
    defined = _occurrences(page_texts, HEADING_PATTERN)
    cited = _occurrences(test_texts, CITATION_PATTERN)
    problems = []
    for requirement_id, headings in sorted(defined.items()):
        if len(headings) > 1:
            problems.append(f"{requirement_id} is defined more than once, in {_paths(headings)}")
        if requirement_id not in cited:
            problems.append(f"{requirement_id} ({headings[0]}) is cited by no test file")
    for requirement_id, citing_files in sorted(cited.items()):
        if requirement_id not in defined:
            problems.append(
                f"{requirement_id} is cited by {_paths(citing_files)} but no docs page defines it"
            )
    return problems


def _read_all(paths: Iterable[Path], root: Path) -> dict[Path, str]:
    return {path.relative_to(root): path.read_text() for path in paths}


def run(root: Path) -> int:
    pages = _read_all(sorted((root / "docs").glob("*.md")), root)
    test_paths = [
        path for directory, glob in TEST_GLOBS for path in sorted((root / directory).glob(glob))
    ]
    problems = find_problems(pages, _read_all(test_paths, root))
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


def main() -> int:
    return run(REPOSITORY_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
