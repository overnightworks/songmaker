"""Generates the golden fixtures the TypeScript lyric alignment is pinned to
(issues #45 and #142).

Two kinds, both written to one committed fixture file:

`fixtures` — already-normalised (cue, line) string pairs scored by Python's
difflib, so the TypeScript SequenceMatcher port is checked against difflib on
exactly the characters it receives, independent of the normalisation pipeline;
see the #45 plan-review note.

`alignments` — whole takes run through the reference implementation of the
global word alignment below (#1030), covering takes with word timestamps and
segments without them. Python is the reference:
frontend/src/lib/utils/lyrics-align.ts must reproduce these intervals exactly.

All fixture text is invented, never real lyrics, and ASCII-only so that
case folding cannot differ between the two implementations — except the one
fixture that pins umlaut and number spelling, whose umlauts both casefold
alike. The operator's measured takes live in
frontend/src/lib/utils/fixtures/lyrics-align-takes.json and are pinned by
coverage in lyrics-align.test.ts, not here.

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
from enum import IntEnum
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
# prose contract. Kept deliberately parallel — the same scores, added in the
# same order, the same preference between equal scores — so a drift in
# either shows up as a failing golden fixture rather than as a silently
# wrong highlight.

SKIP_LYRIC_WORD: Final = -0.6
OPEN_HEARD_GAP: Final = -0.3
EXTEND_HEARD_GAP: Final = -0.02
BREAK_PAIR_RUN: Final = -0.1
ANCHOR_MIN_SIMILARITY: Final = 0.6
LINE_MIN_ANCHORED_SHARE: Final = 0.5
VERBATIM_MAX_TOKENS: Final = 2

SECTION_MARKER: Final = re.compile(r"^\[[^\[\]]+\]$")
CURLY_APOSTROPHES: Final = re.compile("[‘’‛ʼ]")
DIGITS: Final = re.compile(r"[0-9]+")

UMLAUT_SPELLINGS: Final = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue"})
UNITS: Final = (
    "null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun",
    "zehn", "elf", "zwölf", "dreizehn", "vierzehn", "fünfzehn", "sechzehn", "siebzehn",
    "achtzehn", "neunzehn",
)
TENS: Final = (
    "", "", "zwanzig", "dreißig", "vierzig", "fünfzig", "sechzig", "siebzig", "achtzig",
    "neunzig",
)
LARGEST_SPELLED_NUMBER: Final = 9999


class Ending(IntEnum):
    """What an alignment ends in; the order is the preference between equal scores."""

    HEARD_GAP = 0
    PAIR = 1
    LYRIC_GAP = 2


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


class HeardWord(NamedTuple):
    start: float
    end: float
    text: str


class LyricWord(NamedTuple):
    line_index: int
    text: str


class Anchor(NamedTuple):
    heard_index: int
    similarity: float


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


def _number_prefix(count: int) -> str:
    return "ein" if count == 1 else UNITS[count]


def spell_german_number(value: int) -> str:
    if value < len(UNITS):
        return UNITS[value]
    if value < 100:
        unit = value % 10
        tens = TENS[value // 10]
        return tens if unit == 0 else f"{_number_prefix(unit)}und{tens}"
    scale, word = (100, "hundert") if value < 1000 else (1000, "tausend")
    rest = value % scale
    return f"{_number_prefix(value // scale)}{word}{spell_german_number(rest) if rest else ''}"


def _spell_out_number(token: str) -> str:
    if not DIGITS.fullmatch(token) or int(token) > LARGEST_SPELLED_NUMBER:
        return token
    return spell_german_number(int(token))


def normalize_lyrics_token(text: str) -> str:
    straightened = unicodedata.normalize("NFKC", CURLY_APOSTROPHES.sub("'", text))
    stripped = "".join(
        char
        for index, char in enumerate(straightened)
        if not unicodedata.category(char).startswith("P")
        or (char == "'" and _is_word_internal_apostrophe(straightened, index))
    )
    words = re.sub(r"\s+", " ", stripped).strip()
    spelled = " ".join(_spell_out_number(token) for token in words.split(" "))
    return spelled.casefold().translate(UMLAUT_SPELLINGS)


def _tokens(text: str) -> list[str]:
    normalized = normalize_lyrics_token(text)
    return normalized.split(" ") if normalized else []


def _is_sung_line(raw_line: str) -> bool:
    trimmed = raw_line.strip()
    return bool(trimmed) and not SECTION_MARKER.match(trimmed)


def lyric_words(raw_lines: list[str]) -> list[LyricWord]:
    return [
        LyricWord(line_index, text)
        for line_index, line in enumerate(raw_lines)
        if _is_sung_line(line)
        for text in _tokens(line)
    ]


def join_hyphen_pieces(words: tuple[WordCue, ...]) -> list[WordCue]:
    joined: list[WordCue] = []
    for word in words:
        if joined and word.text.lstrip().startswith("-"):
            previous = joined[-1]
            joined[-1] = WordCue(previous.start, word.end, previous.text + word.text.strip())
        else:
            joined.append(word)
    return joined


def heard_words(cues: tuple[Cue, ...]) -> list[HeardWord]:
    timed: list[WordCue | Cue] = []
    for cue in sorted(cues, key=lambda cue: (cue.start, cue.end)):
        timed.extend(join_hyphen_pieces(cue.words) if cue.words else [cue])
    return [HeardWord(word.start, word.end, text) for word in timed for text in _tokens(word.text)]


def word_similarity(heard: str, lyric: str) -> float:
    return 1.0 if heard == lyric else SequenceMatcher(None, heard, lyric).ratio()


class AlignmentTable:
    """Gotoh's three-state Needleman–Wunsch table, one score per ending per cell."""

    def __init__(self, lyric_count: int, heard_count: int) -> None:
        self.width = heard_count + 1
        cells = (lyric_count + 1) * self.width
        self.score = [[float("-inf")] * cells for _ in Ending]
        self.previous = [[Ending.HEARD_GAP] * cells for _ in Ending]

    def set(self, ending: Ending, cell: int, score: float, previous: Ending) -> None:
        self.score[ending][cell] = score
        self.previous[ending][cell] = previous

    def best_ending(self, cell: int) -> Ending:
        best = Ending.HEARD_GAP
        for ending in Ending:
            if self.score[ending][cell] > self.score[best][cell]:
                best = ending
        return best

    def best(self, cell: int) -> float:
        return self.score[self.best_ending(cell)][cell]


def fill_alignment_table(
    lyrics: list[str], heard: list[str], similarity: Callable[[int, int], float]
) -> AlignmentTable:
    table = AlignmentTable(len(lyrics), len(heard))
    width = table.width
    for heard_index in range(len(heard) + 1):
        table.set(Ending.HEARD_GAP, heard_index, 0.0, Ending.HEARD_GAP)

    for lyric_index in range(1, len(lyrics) + 1):
        row = lyric_index * width
        is_outro = lyric_index == len(lyrics)
        open_gap = 0.0 if is_outro else OPEN_HEARD_GAP
        extend_gap = 0.0 if is_outro else EXTEND_HEARD_GAP

        for heard_index in range(len(heard) + 1):
            cell = row + heard_index
            above = cell - width
            skipped = table.best(above) + SKIP_LYRIC_WORD
            table.set(Ending.LYRIC_GAP, cell, skipped, table.best_ending(above))
            if heard_index == 0:
                continue

            left = cell - 1
            opened = table.best(left) + open_gap
            extended = table.score[Ending.HEARD_GAP][left] + extend_gap
            if extended >= opened:
                table.set(Ending.HEARD_GAP, cell, extended, Ending.HEARD_GAP)
            else:
                table.set(Ending.HEARD_GAP, cell, opened, table.best_ending(left))

            diagonal = above - 1
            pair_score = 2 * similarity(lyric_index - 1, heard_index - 1) - 1
            continued = table.score[Ending.PAIR][diagonal]
            broken = table.best(diagonal) + BREAK_PAIR_RUN
            if continued >= broken:
                table.set(Ending.PAIR, cell, continued + pair_score, Ending.PAIR)
            else:
                table.set(Ending.PAIR, cell, broken + pair_score, table.best_ending(diagonal))
    return table


def align_words(lyrics: list[str], heard: list[str]) -> list[Anchor | None]:
    cache: dict[tuple[str, str], float] = {}

    def similarity(lyric_index: int, heard_index: int) -> float:
        key = (lyrics[lyric_index], heard[heard_index])
        if key not in cache:
            cache[key] = word_similarity(heard[heard_index], lyrics[lyric_index])
        return cache[key]

    table = fill_alignment_table(lyrics, heard, similarity)
    anchors: list[Anchor | None] = [None] * len(lyrics)
    lyric_index, heard_index = len(lyrics), len(heard)
    ending = table.best_ending(lyric_index * table.width + heard_index)
    while lyric_index > 0:
        cell = lyric_index * table.width + heard_index
        previous = table.previous[ending][cell]
        if ending == Ending.PAIR:
            pair_similarity = similarity(lyric_index - 1, heard_index - 1)
            if pair_similarity >= ANCHOR_MIN_SIMILARITY:
                anchors[lyric_index - 1] = Anchor(heard_index - 1, pair_similarity)
            lyric_index -= 1
            heard_index -= 1
        elif ending == Ending.LYRIC_GAP:
            lyric_index -= 1
        else:
            heard_index -= 1
        ending = previous
    return anchors


def _is_line_heard(line_anchors: list[Anchor | None]) -> bool:
    if len(line_anchors) <= VERBATIM_MAX_TOKENS:
        return all(anchor is not None and anchor.similarity == 1 for anchor in line_anchors)
    anchored = sum(anchor is not None for anchor in line_anchors)
    return anchored / len(line_anchors) >= LINE_MIN_ANCHORED_SHARE


def _line_interval(line_anchors: list[Anchor | None], heard: list[HeardWord]) -> Interval | None:
    if not line_anchors or not _is_line_heard(line_anchors):
        return None
    sung = [heard[anchor.heard_index] for anchor in line_anchors if anchor is not None]
    return Interval(sung[0].start, sung[-1].end)


def align_lyrics_to_cues(lyrics: str, cues: tuple[Cue, ...]) -> list[Interval | None]:
    raw_lines = re.split(r"\r?\n", lyrics)
    words = lyric_words(raw_lines)
    heard = heard_words(cues)
    anchors = align_words([word.text for word in words], [word.text for word in heard])

    anchors_by_line: list[list[Anchor | None]] = [[] for _ in raw_lines]
    for word, anchor in zip(words, anchors, strict=True):
        anchors_by_line[word.line_index].append(anchor)
    return [_line_interval(line_anchors, heard) for line_anchors in anchors_by_line]


# ── alignment fixtures ──────────────────────────────────────────────

LINE_1: Final = "the lantern hums quietly tonight"
LINE_2: Final = "we count the fading city lights"
LINE_3: Final = "another mile of rusted signs"
CHORUS: Final = "hold the line until the morning"
RIVER: Final = "the river carries every promise home"
CHORUS_TAIL: Final = "until the morning"
CHORUS_SLIP: Final = "hold the line until the mornin"
NESTED_LONG: Final = "i wanted you to stay tonight"
NESTED_SHORT: Final = "i wanted you to stay"
RAIN_FALLS: Final = "silver rain falls on the roof"
RAIN_CALLS: Final = "silver rain calls on the roof"
RAIN_WALLS: Final = "silver rain walls on the roof"


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
        "word path: a long stretch of unmatched words does not hide the lines behind it",
        "\n".join([LINE_1, LINE_2, LINE_3]),
        (_sung_cue(0.0, 0.4, f"{LINE_1} {' '.join(['la'] * 96)} {LINE_2} {LINE_3}"),),
    ),
    AlignmentFixture(
        "word path: a two-word line is not lit by words that merely resemble it",
        "\n".join(["yeah", LINE_1]),
        (_sung_cue(0.0, 0.4, f"a year ago {LINE_1}"),),
    ),
    AlignmentFixture(
        "word path: a two-word line is lit where the take sings it word for word",
        "\n".join(["yeah", LINE_1]),
        (_sung_cue(0.0, 0.4, f"yeah {LINE_1}"),),
    ),
    AlignmentFixture(
        "cue window: a two-word line is not lit by a cue that merely resembles it",
        "\n".join(["yeah", LINE_1]),
        (Cue(0.0, 0.5, "year"), Cue(0.5, 3.0, LINE_1)),
    ),
    AlignmentFixture(
        "word path: a line that opens the next one leaves those words to the sung line",
        "\n".join(["hold the line", CHORUS]),
        (_sung_cue(0.0, 0.4, CHORUS),),
    ),
    AlignmentFixture(
        "word path: two identical lines in a row take successive renditions",
        "\n".join([CHORUS, CHORUS]),
        (_sung_cue(0.0, 0.4, f"{CHORUS} {CHORUS}"),),
    ),
    AlignmentFixture(
        "word path: a line nested in its neighbour takes its own rendition",
        "\n".join([NESTED_LONG, NESTED_SHORT]),
        (_sung_cue(0.0, 0.4, f"{NESTED_LONG} {NESTED_SHORT}"),),
    ),
    AlignmentFixture(
        "word path: a near-duplicate line elsewhere never takes another line's rendition",
        "\n".join([RAIN_FALLS, LINE_3, RAIN_CALLS]),
        (_sung_cue(0.0, 0.4, f"{LINE_3} {RAIN_CALLS}"),),
    ),
    AlignmentFixture(
        "word path: a take built from repeated lines lights every one of them in order",
        "\n".join([RIVER, RIVER, CHORUS, CHORUS, RIVER, LINE_2, CHORUS, CHORUS]),
        (_sung_cue(0.0, 0.4, " ".join(
            [RIVER, RIVER, CHORUS, CHORUS, RIVER, LINE_2, CHORUS, CHORUS],
        )),),
    ),
    AlignmentFixture(
        "word path: a sub-phrase of a later line never steals that line's opening",
        "\n".join(["hold the line", LINE_3, CHORUS]),
        (_sung_cue(0.0, 0.4, f"{LINE_3} {CHORUS}"),),
    ),
    AlignmentFixture(
        "word path: a tail of a later line never steals that line's words",
        "\n".join([CHORUS_TAIL, CHORUS]),
        (_sung_cue(0.0, 0.4, CHORUS),),
    ),
    AlignmentFixture(
        "word path: a tail of a later line stays dark across a verse between them",
        "\n".join([CHORUS_TAIL, LINE_3, CHORUS]),
        (_sung_cue(0.0, 0.4, f"{LINE_3} {CHORUS}"),),
    ),
    AlignmentFixture(
        "word path: two renditions differing by a dropped letter light in order",
        "\n".join([CHORUS, CHORUS]),
        (_sung_cue(0.0, 0.4, f"{CHORUS_SLIP} {CHORUS}"),),
    ),
    AlignmentFixture(
        "word path: a prefix line stays dark when only the slipped long line was sung",
        "\n".join([NESTED_LONG, NESTED_SHORT, LINE_3, NESTED_LONG]),
        (_sung_cue(0.0, 0.4, f"{NESTED_LONG}x {LINE_3} {NESTED_LONG}"),),
    ),
    AlignmentFixture(
        "word path: of two near-identical lines the one sung word for word takes the run",
        "\n".join([RAIN_FALLS, RAIN_CALLS]),
        (_sung_cue(0.0, 0.4, RAIN_FALLS),),
    ),
    AlignmentFixture(
        "word path: of three near-identical lines the middle one sung takes the whole run",
        "\n".join([RAIN_FALLS, RAIN_CALLS, RAIN_WALLS]),
        (_sung_cue(0.0, 0.4, RAIN_CALLS),),
    ),
    AlignmentFixture(
        "word path: two near-identical chorus variants each light where they are sung",
        "\n".join([RAIN_FALLS, LINE_3, RAIN_CALLS]),
        (_sung_cue(0.0, 0.4, f"{RAIN_FALLS} {LINE_3} {RAIN_CALLS}"),),
    ),
    AlignmentFixture(
        "word path: a chorus line Whisper did not recognise leaves the verse behind it lit",
        "\n".join([CHORUS, LINE_1, LINE_2, CHORUS]),
        (_sung_cue(0.0, 0.4, f"ooh na na na ooh na {LINE_1} {LINE_2} {CHORUS}"),),
    ),
    AlignmentFixture(
        "word path: hyphen-led pieces of a spelled-out word read as that one word",
        "\n".join(["yeah, A-M-I-F", LINE_1]),
        (_sung_cue(0.0, 0.4, f"yeah A -M -I -F {LINE_1}"),),
    ),
    AlignmentFixture(
        "word path: a spelled-out umlaut and a sung number read as the words the lyrics spell",
        "\n".join(["die laterne glueht siebzehn mal", LINE_2]),
        (_sung_cue(0.0, 0.4, f"Die Laterne glüht 17 mal {LINE_2}"),),
    ),
    AlignmentFixture(
        "word path: a phrase sung twice takes the clearly better reading",
        LINE_1,
        (_sung_cue(0.0, 0.4, f"{LINE_1} the lantern hums calmly tonight"),),
    ),
    AlignmentFixture(
        "word path: of two readings of a line the closer one takes it, even the later one",
        LINE_1,
        (_sung_cue(0.0, 0.4, f"the lantern hums quietly tonite {LINE_1}"),),
    ),
    AlignmentFixture(
        "mixed: a segment without word timestamps among timed ones carries its whole span",
        "\n".join([LINE_1, LINE_2]),
        (_sung_cue(0.0, 0.5, LINE_1), Cue(2.5, 5.0, LINE_2)),
    ),
    AlignmentFixture(
        "cue window: a segment lights the line it reads word for word, not its near-twin",
        "\n".join([RAIN_FALLS, RAIN_CALLS]),
        (Cue(0.0, 3.0, RAIN_FALLS),),
    ),
    AlignmentFixture(
        "cue window: a line split across two segments spans both",
        "\n".join([LINE_1, LINE_2, LINE_3]),
        (
            Cue(0.0, 4.0, f"{LINE_1} we count the"),
            Cue(4.0, 8.0, f"fading city lights {LINE_3}"),
        ),
    ),
    AlignmentFixture(
        "cue window: both lines of a two-line window carry the whole cue span",
        "\n".join([LINE_1, LINE_2, LINE_3]),
        (
            Cue(0.0, 6.0, f"{LINE_1} {LINE_2}"),
            Cue(6.0, 9.5, LINE_3),
        ),
    ),
    AlignmentFixture(
        "cue window: all three lines of a three-line window carry the whole cue span",
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
