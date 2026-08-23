"""Tests for ``scripts/lyric_alignment_golden.py``."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import lyric_alignment_golden as golden  # noqa: E402


def test_golden_ratio_generation_is_deterministic():
    first = golden.compute_golden_ratios()
    second = golden.compute_golden_ratios()

    assert first == second


def test_committed_fixture_file_matches_current_generator_output():
    assert golden.FIXTURES_PATH.exists(), (
        "frontend/src/lib/utils/lyrics-align.fixtures.json is missing — run "
        "`python scripts/lyric_alignment_golden.py` to (re)generate it"
    )

    committed = json.loads(golden.FIXTURES_PATH.read_text())

    assert committed == {"fixtures": golden.compute_golden_ratios()}


def test_every_fixture_pins_an_invented_non_empty_name():
    for fixture in golden.FIXTURES:
        assert fixture.name
