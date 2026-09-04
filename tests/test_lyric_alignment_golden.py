"""Tests for ``scripts/lyric_alignment_golden.py``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import lyric_alignment_golden as golden  # noqa: E402


@pytest.mark.parametrize(
    "generate",
    [golden.compute_golden_ratios, golden.compute_golden_alignments],
    ids=["ratios", "alignments"],
)
def test_golden_generation_is_deterministic(generate):
    first = generate()
    second = generate()
    assert first == second


def test_committed_fixture_file_matches_current_generator_output():
    assert golden.FIXTURES_PATH.exists(), (
        "frontend/src/lib/utils/lyrics-align.fixtures.json is missing — run "
        "`python scripts/lyric_alignment_golden.py` to (re)generate it"
    )

    committed = json.loads(golden.FIXTURES_PATH.read_text())

    assert committed == {
        "alignments": golden.compute_golden_alignments(),
        "fixtures": golden.compute_golden_ratios(),
    }
