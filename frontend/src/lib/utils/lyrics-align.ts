// Deterministic lyric↔Whisper-cue alignment (issue #45, word timestamps on
// #142, one global alignment on #1030). Pure and offline-testable: no player
// state, no DOM coupling. The Now Playing lyrics column is the sole consumer.
// scripts/lyric_alignment_golden.py holds the reference implementation this
// file is pinned against.
//
// The lyrics and the take are two word streams in the same order: the words
// the lyrics ask for, and the words Whisper heard. One global alignment
// (Needleman–Wunsch) pairs them so that the whole song scores best, rather
// than letting each line grab the best-looking run on its own — a greedy line
// that guesses wrong strands every line behind it (#1029 measured 85 % of the
// lines lit that way, and 98 % with the global alignment on the same cues).
//
// A pair scores by how alike the two words read; leaving a lyric word unsung
// costs more than passing over a heard word, because Whisper hears adlibs and
// hallucinations the lyrics never carry. Heard words before the first and
// after the last lyric word are free: intros and outros are not lyrics.
//
// A line is lit from its first to its last anchored word once at least half
// of its words are anchored; a line of at most two words only where the take
// sings it word for word, since a character ratio cannot tell "yeah" from a
// sung "year". Anything less leaves the line dark: a gap, not a guess.
//
// A cue without word timestamps (a take scored before #142) contributes its
// text's words, each carrying the whole cue span: nothing in such a take
// says where inside a segment one line ends and the next begins, so the
// lines it covers light together rather than on invented timing (#45).
import type { WhisperCue, WhisperWordCue } from '$lib/api/types';
import { normalizeLyricsToken } from './lyrics-normalize';
import { SequenceMatcher } from './sequence-matcher';

const SKIP_LYRIC_WORD = -0.6;
// Passing over heard words costs once per stretch plus a little per word: an
// adlib, a hallucinated caption or a stretch Whisper garbled between two
// lines is one interruption however many words it holds, and the per-word
// part keeps a line on its nearest rendition.
const OPEN_HEARD_GAP = -0.3;
const EXTEND_HEARD_GAP = -0.02;
// A line is sung as one run of words. Every run of pairs that does not
// continue the one before costs this much, so the alignment keeps a line's
// words together rather than splitting them across two near-identical lines
// that would score the same word by word.
const BREAK_PAIR_RUN = -0.1;
const ANCHOR_MIN_SIMILARITY = 0.6;
const LINE_MIN_ANCHORED_SHARE = 0.5;
const VERBATIM_MAX_TOKENS = 2;

const SECTION_MARKER = /^\[[^[\]]+\]$/;

// What the alignment of the first i lyric words against the first j heard
// words ends in. The order is the preference between equal scores: of two
// equally good renditions a line takes the earlier one.
enum Ending {
	HeardGap,
	Pair,
	LyricGap
}
const ENDINGS = [Ending.HeardGap, Ending.Pair, Ending.LyricGap] as const;

interface LyricLineInterval {
	start: number;
	end: number;
}

export interface AlignedLyricLine {
	text: string;
	interval: LyricLineInterval | null;
}

interface HeardWord {
	start: number;
	end: number;
	text: string;
}

interface LyricWord {
	lineIndex: number;
	text: string;
}

interface Anchor {
	heardIndex: number;
	similarity: number;
}

function tokens(text: string): string[] {
	const normalized = normalizeLyricsToken(text);
	return normalized.length === 0 ? [] : normalized.split(' ');
}

function isSungLine(rawLine: string): boolean {
	const trimmed = rawLine.trim();
	return trimmed.length > 0 && !SECTION_MARKER.test(trimmed);
}

function lyricWords(rawLines: string[]): LyricWord[] {
	return rawLines.flatMap((line, lineIndex) =>
		isSungLine(line) ? tokens(line).map((text) => ({ lineIndex, text })) : []
	);
}

// Whisper splits a spelled-out or hyphenated word into pieces that open with
// a hyphen ("A", "-M", "-I", "-F"); together they are the one word the
// lyrics carry ("A-M-I-F").
function joinHyphenPieces(words: WhisperWordCue[]): WhisperWordCue[] {
	const joined: WhisperWordCue[] = [];
	for (const word of words) {
		const previous = joined[joined.length - 1];
		if (previous && word.text.trimStart().startsWith('-')) {
			joined[joined.length - 1] = {
				start: previous.start,
				end: word.end,
				text: previous.text + word.text.trim()
			};
		} else {
			joined.push(word);
		}
	}
	return joined;
}

function heardWords(cues: WhisperCue[]): HeardWord[] {
	return cues
		.map((cue, index) => ({ cue, index }))
		.sort(
			(left, right) =>
				left.cue.start - right.cue.start || left.cue.end - right.cue.end || left.index - right.index
		)
		.flatMap(({ cue }) => (cue.words?.length ? joinHyphenPieces(cue.words) : [cue]))
		.flatMap((word) =>
			tokens(word.text).map((text) => ({ start: word.start, end: word.end, text }))
		);
}

function wordSimilarity(heard: string, lyric: string): number {
	return heard === lyric ? 1 : new SequenceMatcher(heard, lyric).ratio();
}

// Songs repeat their words, so each distinct pair is scored once.
function similarityLookup(
	lyrics: string[],
	heard: string[]
): (lyric: number, heard: number) => number {
	const cache = new Map<string, number>();
	return (lyricIndex, heardIndex) => {
		const key = `${lyrics[lyricIndex]}\u0000${heard[heardIndex]}`;
		let similarity = cache.get(key);
		if (similarity === undefined) {
			similarity = wordSimilarity(heard[heardIndex], lyrics[lyricIndex]);
			cache.set(key, similarity);
		}
		return similarity;
	};
}

// The global alignment of the lyric words against the heard words (Gotoh's
// three-state Needleman–Wunsch). For every cell (i, j) and every way the
// alignment can end there, `score` holds the best score and `previous` the
// ending of the cell it came from.
class AlignmentTable {
	readonly width: number;
	private readonly score: Float64Array[];
	private readonly previous: Uint8Array[];

	constructor(lyricCount: number, heardCount: number) {
		this.width = heardCount + 1;
		const cells = (lyricCount + 1) * this.width;
		this.score = ENDINGS.map(() => new Float64Array(cells).fill(-Infinity));
		this.previous = ENDINGS.map(() => new Uint8Array(cells));
	}

	scoreOf(ending: Ending, cell: number): number {
		return this.score[ending][cell];
	}

	previousOf(ending: Ending, cell: number): Ending {
		return this.previous[ending][cell];
	}

	set(ending: Ending, cell: number, score: number, previous: Ending): void {
		this.score[ending][cell] = score;
		this.previous[ending][cell] = previous;
	}

	bestEnding(cell: number): Ending {
		let best = Ending.HeardGap;
		for (const ending of ENDINGS) {
			if (this.score[ending][cell] > this.score[best][cell]) best = ending;
		}
		return best;
	}

	best(cell: number): number {
		return this.score[this.bestEnding(cell)][cell];
	}
}

function fillAlignmentTable(
	lyricCount: number,
	heardCount: number,
	similarity: (lyric: number, heard: number) => number
): AlignmentTable {
	const table = new AlignmentTable(lyricCount, heardCount);
	const { width } = table;
	for (let heardIndex = 0; heardIndex <= heardCount; heardIndex++) {
		table.set(Ending.HeardGap, heardIndex, 0, Ending.HeardGap);
	}

	for (let lyricIndex = 1; lyricIndex <= lyricCount; lyricIndex++) {
		const row = lyricIndex * width;
		const isOutro = lyricIndex === lyricCount;
		const openGap = isOutro ? 0 : OPEN_HEARD_GAP;
		const extendGap = isOutro ? 0 : EXTEND_HEARD_GAP;

		for (let heardIndex = 0; heardIndex <= heardCount; heardIndex++) {
			const cell = row + heardIndex;
			const above = cell - width;
			table.set(
				Ending.LyricGap,
				cell,
				table.best(above) + SKIP_LYRIC_WORD,
				table.bestEnding(above)
			);
			if (heardIndex === 0) continue;

			const left = cell - 1;
			const opened = table.best(left) + openGap;
			const extended = table.scoreOf(Ending.HeardGap, left) + extendGap;
			if (extended >= opened) table.set(Ending.HeardGap, cell, extended, Ending.HeardGap);
			else table.set(Ending.HeardGap, cell, opened, table.bestEnding(left));

			const diagonal = above - 1;
			const pairScore = 2 * similarity(lyricIndex - 1, heardIndex - 1) - 1;
			const continued = table.scoreOf(Ending.Pair, diagonal);
			const broken = table.best(diagonal) + BREAK_PAIR_RUN;
			if (continued >= broken) table.set(Ending.Pair, cell, continued + pairScore, Ending.Pair);
			else table.set(Ending.Pair, cell, broken + pairScore, table.bestEnding(diagonal));
		}
	}
	return table;
}

// The anchor each lyric word takes in the heard stream, or null when the
// best global alignment leaves it unsung or pairs it with a word too unlike
// it to count.
function alignWords(lyrics: string[], heard: string[]): (Anchor | null)[] {
	const similarity = similarityLookup(lyrics, heard);
	const table = fillAlignmentTable(lyrics.length, heard.length, similarity);

	const anchors: (Anchor | null)[] = new Array(lyrics.length).fill(null);
	let lyricIndex = lyrics.length;
	let heardIndex = heard.length;
	let ending = table.bestEnding(lyricIndex * table.width + heardIndex);
	while (lyricIndex > 0) {
		const cell = lyricIndex * table.width + heardIndex;
		const previous = table.previousOf(ending, cell);
		if (ending === Ending.Pair) {
			const pairSimilarity = similarity(lyricIndex - 1, heardIndex - 1);
			if (pairSimilarity >= ANCHOR_MIN_SIMILARITY) {
				anchors[lyricIndex - 1] = { heardIndex: heardIndex - 1, similarity: pairSimilarity };
			}
			lyricIndex--;
			heardIndex--;
		} else if (ending === Ending.LyricGap) {
			lyricIndex--;
		} else {
			heardIndex--;
		}
		ending = previous;
	}
	return anchors;
}

function isLineHeard(lineAnchors: (Anchor | null)[]): boolean {
	if (lineAnchors.length <= VERBATIM_MAX_TOKENS) {
		return lineAnchors.every((anchor) => anchor?.similarity === 1);
	}
	const anchored = lineAnchors.filter((anchor) => anchor !== null).length;
	return anchored / lineAnchors.length >= LINE_MIN_ANCHORED_SHARE;
}

function lineInterval(
	lineAnchors: (Anchor | null)[],
	heard: HeardWord[]
): LyricLineInterval | null {
	if (!isLineHeard(lineAnchors)) return null;
	const sung = lineAnchors
		.filter((anchor) => anchor !== null)
		.map((anchor) => heard[anchor.heardIndex]);
	return { start: sung[0].start, end: sung[sung.length - 1].end };
}

// Maps whisper_cues onto the display lines of `lyrics` (split with the same
// /\r?\n/ regex the normalisation contract specifies). Every display line
// is returned, in order, including blank and [section] lines — those are
// simply never alignable and always carry a null interval.
export function alignLyricsToCues(lyrics: string, cues: WhisperCue[]): AlignedLyricLine[] {
	const rawLines = lyrics.split(/\r?\n/);
	const words = lyricWords(rawLines);
	const heard = heardWords(cues);
	const anchors = alignWords(
		words.map((word) => word.text),
		heard.map((word) => word.text)
	);

	const anchorsByLine = rawLines.map((): (Anchor | null)[] => []);
	words.forEach((word, index) => anchorsByLine[word.lineIndex].push(anchors[index]));

	return rawLines.map((text, index) => ({
		text,
		interval: anchorsByLine[index].length ? lineInterval(anchorsByLine[index], heard) : null
	}));
}

// Every line active at `currentTime`, in display order, and none at all
// between cues / before the first / after the last — a gap is never a guess.
// Interval is half-open [start, end): a boundary time belongs to the line
// that starts there. A cue window puts the same span on each of its lines, so
// those light together.
export function activeLyricLineIndices(lines: AlignedLyricLine[], currentTime: number): number[] {
	const active: number[] = [];
	for (let index = 0; index < lines.length; index++) {
		const interval = lines[index].interval;
		if (interval && currentTime >= interval.start && currentTime < interval.end) active.push(index);
	}
	return active;
}
