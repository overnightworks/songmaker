"""Generates golden difflib.SequenceMatcher ratios for the TypeScript
SequenceMatcher port's test fixtures (issue #45).

Every fixture is an already-normalised (cue, line) string pair — invented
text, never real lyrics — so the ratio is computed directly by Python's
difflib on exactly the same characters the TypeScript port receives. This
keeps the fixture from depending on the TypeScript normalisation pipeline
matching the Python one; see the #45 plan-review note.

Run from the project root to (re)write the committed fixture:

    python scripts/lyric_alignment_golden.py
"""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Final, NamedTuple

FIXTURES_PATH: Final = (
    Path(__file__).resolve().parent.parent
    / "frontend"
    / "src"
    / "lib"
    / "utils"
    / "lyrics-align.fixtures.json"
)


class RatioFixture(NamedTuple):
    name: str
    cue: str
    line: str


FIXTURES: Final[tuple[RatioFixture, ...]] = (
    RatioFixture("identical short strings", "hello there my friend", "hello there my friend"),
    RatioFixture(
        "completely different strings",
        "hello there my friend",
        "the quick brown fox jumps",
    ),
    RatioFixture("empty cue", "", "hello there"),
    RatioFixture("empty line", "hello there", ""),
    RatioFixture("both empty", "", ""),
    RatioFixture(
        "single word difference",
        "walking down the road today",
        "walking down the road tomorrow",
    ),
    RatioFixture(
        "word order swapped",
        "sun and moon and stars above",
        "stars above and moon and sun",
    ),
    RatioFixture(
        "near duplicate with a dropped letter",
        "i will remember this forever",
        "i will rember this forever",
    ),
    RatioFixture("short substring match", "hi", "oh hi there my friend"),
    RatioFixture(
        "one long common run plus a distinct tail",
        "distinctive closing phrase right here",
        "z" * 205 + " distinctive closing phrase right here",
    ),
    RatioFixture(
        "one long common run with no shared tail",
        "totally unrelated short line",
        "q" * 220 + " something else entirely different",
    ),
)


def compute_golden_ratios() -> list[dict[str, object]]:
    return [
        {
            "name": fixture.name,
            "cue": fixture.cue,
            "line": fixture.line,
            "ratio": SequenceMatcher(None, fixture.cue, fixture.line).ratio(),
        }
        for fixture in FIXTURES
    ]


def write_fixtures() -> None:
    payload = {"fixtures": compute_golden_ratios()}
    FIXTURES_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    write_fixtures()
