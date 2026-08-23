"""Generates the golden fixtures the TypeScript lyric alignment is pinned to
(issues #45 and #142).

Two kinds, both written to one committed fixture file:

`fixtures` — already-normalised (cue, line) string pairs scored by Python's
difflib, so the TypeScript SequenceMatcher port is checked against difflib on
exactly the characters it receives, independent of the normalisation pipeline;
see the #45 plan-review note.

`alignments` — whole takes run through the reference implementation of the
alignment contract below, covering both the word-timestamp path and the cue
window fallback. Python is the reference: frontend/src/lib/utils/lyrics-align.ts
must reproduce these intervals exactly.

All fixture text is invented, never real lyrics, and ASCII-only so that
case folding cannot differ between the two implementations.

Run from the project root to (re)write the committed fixture; Prettier owns
its final layout, so hand it the file afterwards:

    python scripts/lyric_alignment_golden.py
    cd frontend && pnpm exec prettier --write src/lib/utils/lyrics-align.fixtures.json
"""

from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Final, NamedTuple

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


# ── reference alignment ─────────────────────────────────────────────
# Mirrors frontend/src/lib/utils/lyrics-align.ts; that file's header owns the
# prose contract. Kept deliberately parallel so a drift in either shows up as
# a failing golden fixture rather than as a silently wrong highlight.

MIN_RATIO: Final = 0.72
AMBIGUITY_MARGIN: Final = 0.12
MAX_WINDOW_LINES: Final = 3
WORD_STREAM_LOOKAHEAD: Final = 24
RELEVANT_RATIO: Final = MIN_RATIO - AMBIGUITY_MARGIN
LENGTH_FACTOR_MIN: Final = RELEVANT_RATIO / (2 - RELEVANT_RATIO)
LENGTH_FACTOR_MAX: Final = (2 - RELEVANT_RATIO) / RELEVANT_RATIO

SECTION_MARKER: Final = re.compile(r"^\[[^\[\]]+\]$")
CURLY_APOSTROPHES: Final = re.compile("[‘’‛ʼ]")


class WordCue(NamedTuple):
    start: float
    end: float
    text: str


class Cue(NamedTuple):
    start: float
    end: float
    text: str
    words: tuple[WordCue, ...] | None = None


class Interval(NamedTuple):
    start: float
    end: float


class Candidate(NamedTuple):
    first: int
    last: int
    text: str
    score: float


class AlignmentFixture(NamedTuple):
    name: str
    lyrics: str
    cues: tuple[Cue, ...]


def _is_word_char(char: str) -> bool:
    return char == "_" or unicodedata.category(char)[0] in "LN"


def _is_word_internal_apostrophe(text: str, index: int) -> bool:
    if index == 0 or index + 1 >= len(text):
        return False
    return _is_word_char(text[index - 1]) and _is_word_char(text[index + 1])


def normalize_lyrics_token(text: str) -> str:
    casefolded = unicodedata.normalize("NFKC", CURLY_APOSTROPHES.sub("'", text)).casefold()
    stripped = "".join(
        char
        for index, char in enumerate(casefolded)
        if not unicodedata.category(char).startswith("P")
        or (char == "'" and _is_word_internal_apostrophe(casefolded, index))
    )
    return re.sub(r"\s+", " ", stripped).strip()


def ratio(transcribed_text: str, lyric_text: str) -> float:
    return SequenceMatcher(None, transcribed_text, lyric_text).ratio()


def collect_candidates(
    unit_texts: list[str],
    first_start: int,
    start_limit: int,
    max_units: int,
    target_length: int,
    score: Callable[[str], float],
) -> list[Candidate]:
    min_length = target_length * LENGTH_FACTOR_MIN
    max_length = target_length * LENGTH_FACTOR_MAX
    candidates: list[Candidate] = []

    for first in range(first_start, start_limit):
        text = ""
        for last in range(first, min(len(unit_texts), first + max_units)):
            text = unit_texts[last] if last == first else f"{text} {unit_texts[last]}"
            if len(text) > max_length:
                break
            if len(text) < min_length:
                continue
            candidates.append(Candidate(first, last, text, score(text)))
    return candidates


def matched_word_range(
    unit_texts: list[str], run: Candidate, lyric_text: str,
) -> tuple[int, int]:
    blocks = [
        block
        for block in SequenceMatcher(None, run.text, lyric_text).get_matching_blocks()
        if block.size > 0
    ]

    first = -1
    last = -1
    word_start = 0
    for index in range(run.first, run.last + 1):
        word_end = word_start + len(unit_texts[index])
        participates = any(
            block.a < word_end and block.a + block.size > word_start for block in blocks
        )
        if participates:
            if first == -1:
                first = index
            last = index
        word_start = word_end + 1
    return (run.first, run.last) if first == -1 else (first, last)


def _overlaps(candidate: Candidate, other: Candidate) -> bool:
    return candidate.first <= other.last and candidate.last >= other.first


def _echoes(candidate_text: str, best_text: str) -> bool:
    return candidate_text in best_text or best_text in candidate_text


def choose_candidate(candidates: list[Candidate]) -> Candidate | None:
    best: Candidate | None = None
    for candidate in candidates:
        if best is None or candidate.score > best.score:
            best = candidate
    if best is None or best.score < MIN_RATIO:
        return None

    rival_score = float("-inf")
    for candidate in candidates:
        if _overlaps(candidate, best) or _echoes(candidate.text, best.text):
            continue
        rival_score = max(rival_score, candidate.score)
    if rival_score != float("-inf") and best.score - rival_score < AMBIGUITY_MARGIN:
        return None

    return best


def align_against_words(
    words: list[WordCue], line_texts: list[str],
) -> dict[int, Interval]:
    word_texts = [normalize_lyrics_token(word.text) for word in words]
    intervals: dict[int, Interval] = {}

    cursor = 0
    for line_position, line_text in enumerate(line_texts):
        chosen = choose_candidate(collect_candidates(
            word_texts,
            cursor,
            min(len(word_texts), cursor + WORD_STREAM_LOOKAHEAD),
            len(word_texts),
            len(line_text),
            lambda candidate_text, line=line_text: ratio(candidate_text, line),
        ))
        if chosen is None:
            continue
        first, last = matched_word_range(word_texts, chosen, line_text)
        intervals[line_position] = Interval(words[first].start, words[last].end)
        cursor = last + 1
    return intervals


def align_against_cue_windows(
    cues: list[Cue], line_texts: list[str],
) -> dict[int, Interval]:
    intervals: dict[int, Interval] = {}

    floor_position = 0
    for cue in cues:
        if floor_position >= len(line_texts):
            break
        cue_text = normalize_lyrics_token(cue.text)
        chosen = choose_candidate(collect_candidates(
            line_texts,
            floor_position,
            len(line_texts),
            MAX_WINDOW_LINES,
            len(cue_text),
            lambda candidate_text, text=cue_text: ratio(text, candidate_text),
        ))
        if chosen is None:
            continue
        intervals.update(split_cue_span(cue, line_texts, chosen))
        floor_position = chosen.last + 1
    return intervals


def split_cue_span(
    cue: Cue, line_texts: list[str], window: Candidate,
) -> dict[int, Interval]:
    total_length = sum(
        len(line_texts[position]) for position in range(window.first, window.last + 1)
    )
    span = cue.end - cue.start
    intervals: dict[int, Interval] = {}

    consumed_length = 0
    for position in range(window.first, window.last + 1):
        start = (
            cue.start if position == window.first
            else cue.start + (span * consumed_length) / total_length
        )
        consumed_length += len(line_texts[position])
        end = (
            cue.end if position == window.last
            else cue.start + (span * consumed_length) / total_length
        )
        intervals[position] = Interval(start, end)
    return intervals


def align_lyrics_to_cues(lyrics: str, cues: tuple[Cue, ...]) -> list[Interval | None]:
    raw_lines = re.split(r"\r?\n", lyrics)
    normalized_lines = [
        normalize_lyrics_token(line)
        if line.strip() and not SECTION_MARKER.match(line.strip())
        else ""
        for line in raw_lines
    ]
    candidate_line_indices = [
        index for index, text in enumerate(normalized_lines) if text
    ]
    line_texts = [normalized_lines[index] for index in candidate_line_indices]

    sorted_cues = [
        cue for cue in sorted(cues, key=lambda cue: (cue.start, cue.end))
        if normalize_lyrics_token(cue.text)
    ]
    words = [
        word for cue in sorted_cues for word in (cue.words or ())
        if normalize_lyrics_token(word.text)
    ]
    by_position = (
        align_against_words(words, line_texts) if words
        else align_against_cue_windows(sorted_cues, line_texts)
    )

    intervals: list[Interval | None] = [None] * len(raw_lines)
    for position, interval in by_position.items():
        intervals[candidate_line_indices[position]] = interval
    return intervals


# ── alignment fixtures ──────────────────────────────────────────────

LINE_1: Final = "the lantern hums quietly tonight"
LINE_2: Final = "we count the fading city lights"
LINE_3: Final = "another mile of rusted signs"
CHORUS: Final = "hold the line until the morning"


def _words(start: float, per_word: float, text: str) -> tuple[WordCue, ...]:
    """Word cues for `text`, one every `per_word` seconds from `start`."""
    return tuple(
        WordCue(
            round(start + index * per_word, 3),
            round(start + (index + 1) * per_word, 3),
            word,
        )
        for index, word in enumerate(text.split())
    )


def _sung_cue(start: float, per_word: float, text: str) -> Cue:
    words = _words(start, per_word, text)
    return Cue(words[0].start, words[-1].end, text, words)


ALIGNMENT_FIXTURES: Final[tuple[AlignmentFixture, ...]] = (
    AlignmentFixture(
        "word path: one segment spanning three lines lights each line separately",
        "\n".join([LINE_1, LINE_2, LINE_3]),
        (_sung_cue(0.5, 0.4, f"{LINE_1} {LINE_2} {LINE_3}"),),
    ),
    AlignmentFixture(
        "word path: a line the singer skipped stays dark",
        "\n".join([LINE_1, LINE_2, LINE_3]),
        (_sung_cue(1.0, 0.35, f"{LINE_1} {LINE_3}"),),
    ),
    AlignmentFixture(
        "word path: adlib words between two lines belong to no line",
        "\n".join([LINE_1, LINE_2]),
        (_sung_cue(0.0, 0.3, f"{LINE_1} ooh yeah come on {LINE_2}"),),
    ),
    AlignmentFixture(
        "word path: a repeated chorus line takes its own repeat in order",
        "\n".join(["[verse]", LINE_1, "[chorus]", CHORUS, "", "[verse]", LINE_3, CHORUS]),
        (_sung_cue(2.0, 0.45, f"{LINE_1} {CHORUS} {LINE_3} {CHORUS}"),),
    ),
    AlignmentFixture(
        "word path: words that match no line leave every line dark",
        "\n".join([LINE_1, LINE_2]),
        (_sung_cue(0.0, 0.4, "a totally unrelated kitchen inventory list"),),
    ),
    AlignmentFixture(
        "word path: section markers and blank lines never take an interval",
        "\n".join(["[intro]", "", LINE_1, "[verse]", LINE_2]),
        (_sung_cue(0.2, 0.4, f"{LINE_1} {LINE_2}"),),
    ),
    AlignmentFixture(
        "word path: a run padded with foreign words starts at the line's own first word",
        "\n".join([LINE_1, LINE_2]),
        (_sung_cue(0.0, 0.4, f"{LINE_1} {' '.join(['la'] * 30)} {LINE_2}"),),
    ),
    AlignmentFixture(
        "word path: a phrase sung twice takes the clearly better reading",
        LINE_1,
        (_sung_cue(0.0, 0.4, f"{LINE_1} the lantern hums calmly tonight"),),
    ),
    AlignmentFixture(
        "word path: two readings too alike to tell apart leave the line dark",
        LINE_1,
        (_sung_cue(0.0, 0.4, f"{LINE_1} the lantern hums quietly tonite"),),
    ),
    AlignmentFixture(
        "cue window: two lines too alike to tell apart stay dark",
        "\n".join(["silver rain falls on the roof", "silver rain calls on the roof"]),
        (Cue(0.0, 3.0, "silver rain falls on the roof"),),
    ),
    AlignmentFixture(
        "cue window: a segment covering two lines splits its span between them",
        "\n".join([LINE_1, LINE_2, LINE_3]),
        (
            Cue(0.0, 6.0, f"{LINE_1} {LINE_2}"),
            Cue(6.0, 9.5, LINE_3),
        ),
    ),
    AlignmentFixture(
        "cue window: a segment covering three lines splits its span three ways",
        "\n".join([LINE_1, LINE_2, LINE_3]),
        (Cue(1.0, 10.0, f"{LINE_1} {LINE_2} {LINE_3}"),),
    ),
    AlignmentFixture(
        "cue window: one cue per line keeps the cue span untouched",
        "\n".join([LINE_1, LINE_2]),
        (Cue(0.0, 3.25, LINE_1), Cue(3.25, 6.5, LINE_2)),
    ),
    AlignmentFixture(
        "cue window: a segment matching no line leaves every line dark",
        "\n".join([LINE_1, LINE_2]),
        (Cue(0.0, 4.0, "a totally unrelated kitchen inventory list"),),
    ),
    AlignmentFixture(
        "cue window: a skipped line stays dark and the next cue still lands",
        "\n".join([LINE_1, LINE_2, LINE_3]),
        (Cue(0.0, 3.0, LINE_1), Cue(3.0, 6.0, LINE_3)),
    ),
)


def _word_payload(word: WordCue) -> dict[str, object]:
    return {"start": word.start, "end": word.end, "text": word.text}


def _cue_payload(cue: Cue) -> dict[str, object]:
    payload: dict[str, object] = {"start": cue.start, "end": cue.end, "text": cue.text}
    if cue.words is not None:
        payload["words"] = [_word_payload(word) for word in cue.words]
    return payload


def compute_golden_alignments() -> list[dict[str, object]]:
    return [
        {
            "name": fixture.name,
            "lyrics": fixture.lyrics,
            "cues": [_cue_payload(cue) for cue in fixture.cues],
            "intervals": [
                None if interval is None else {"start": interval.start, "end": interval.end}
                for interval in align_lyrics_to_cues(fixture.lyrics, fixture.cues)
            ],
        }
        for fixture in ALIGNMENT_FIXTURES
    ]


def write_fixtures() -> None:
    payload = {
        "alignments": compute_golden_alignments(),
        "fixtures": compute_golden_ratios(),
    }
    # Tab indent to match the frontend's Prettier config, which keeps the
    # reformatting that follows down to short arrays it collapses.
    FIXTURES_PATH.write_text(json.dumps(payload, indent="\t", sort_keys=True) + "\n")


if __name__ == "__main__":
    write_fixtures()
