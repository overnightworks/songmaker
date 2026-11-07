"""Tests for ``scripts/check_requirement_citations.py``."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_requirement_citations as checker  # noqa: E402

PAGE = Path("docs/library.md")
OTHER_PAGE = Path("docs/sharing.md")
TEST_FILE = Path("tests/test_library.py")
# Built at run time so this file cites no requirement itself.
DEFINED_ID = "-".join(("REQ", "LIB", "01"))
UNDEFINED_ID = "-".join(("REQ", "LIB", "99"))


def _heading(requirement_id: str) -> str:
    return f"### {requirement_id}: A sentence.\n"


def test_cited_requirement_passes() -> None:
    problems = checker.find_problems(
        {PAGE: _heading(DEFINED_ID)},
        {TEST_FILE: f'"""Spec: {DEFINED_ID}"""\n'},
    )

    assert problems == []


def test_requirement_cited_by_no_test_fails_and_names_id_and_page() -> None:
    problems = checker.find_problems({PAGE: _heading(DEFINED_ID)}, {TEST_FILE: "no citation\n"})

    assert len(problems) == 1
    assert DEFINED_ID in problems[0]
    assert str(PAGE) in problems[0]


def test_citation_of_undefined_requirement_fails_and_names_id_and_file() -> None:
    problems = checker.find_problems(
        {PAGE: _heading(DEFINED_ID)},
        {TEST_FILE: f"{DEFINED_ID} {UNDEFINED_ID}\n"},
    )

    assert len(problems) == 1
    assert UNDEFINED_ID in problems[0]
    assert str(TEST_FILE) in problems[0]


@pytest.mark.parametrize(
    "pages",
    [
        pytest.param({PAGE: _heading(DEFINED_ID) + _heading(DEFINED_ID)}, id="twice_on_one_page"),
        pytest.param(
            {PAGE: _heading(DEFINED_ID), OTHER_PAGE: _heading(DEFINED_ID)}, id="on_two_pages"
        ),
    ],
)
def test_duplicate_definition_fails_and_names_id(pages: dict[Path, str]) -> None:
    problems = checker.find_problems(pages, {TEST_FILE: f"{DEFINED_ID}\n"})

    assert len(problems) == 1
    assert DEFINED_ID in problems[0]


def test_mention_in_page_body_defines_nothing() -> None:
    problems = checker.find_problems({PAGE: f"See {DEFINED_ID} for details.\n"}, {})

    assert problems == []
