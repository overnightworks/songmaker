// Deterministic lyric↔Whisper-cue alignment (issue #45, contract confirmed
// on #52, word timestamps added on #142). Pure and offline-testable: no
// player state, no DOM coupling. The Now Playing lyrics column is the sole
// consumer. scripts/lyric_alignment_golden.py holds the reference
// implementation both paths are pinned against.
//
// Two paths, chosen by what the take was scored with:
//
// words — a take scored with word timestamps carries a word stream. Lyric
// lines are walked in order and each one takes the best-matching run of
// still-unconsumed words, so the interval is the line's own first…last sung
// word. The cursor never moves backwards.
//
// cue windows (fallback) — a take scored before word timestamps carries only
// segment cues, and a segment follows breathing pauses rather than line
// breaks, so one cue routinely covers up to three lyric lines. Cues are
// walked in playback order and each takes the best-matching run of up to
// three still-unconsumed lines, whose intervals split the cue span in
// proportion to their length. That split is an approximation within a span
// we know was sung — only a re-score buys real per-line timing.
//
// Both paths share the same accept rule: the best candidate must clear
// MIN_RATIO, and it must beat every rival — a candidate that neither
// overlaps it nor merely echoes its words — by AMBIGUITY_MARGIN. An echo is
// a candidate whose text contains the winner's or is contained in it: the
// same phrase sung twice, or the same phrase with a shifted boundary. Those
// cannot say where the line was sung, and under a forward-only cursor the
// earliest reading is the right one, so a repeated chorus is never blocked
// by its own repeat. Anything short of that leaves the line dark: a missed
// highlight is a gap, a wrong one is a lie.
import type { WhisperCue } from '$lib/api/types';
import { normalizeLyricsToken } from './lyrics-normalize';
import { SequenceMatcher } from './sequence-matcher';

const MIN_RATIO = 0.72;
const AMBIGUITY_MARGIN = 0.12;
const MAX_WINDOW_LINES = 3;
// A line whose rendition does not begin within this many transcript words of
// the previous line's last word counts as not sung. Consecutive lines follow
// each other directly in the stream, so this is room for roughly three lines
// of adlibs or skipped text — and it keeps the search linear in the length of
// the take instead of quadratic.
const WORD_STREAM_LOOKAHEAD = 24;
// A candidate scoring below this can neither win nor, as a rival, block the
// winner, so it never has to be looked at. ratio() is 2 · matched /
// (lengthA + lengthB), which bounds that score by length alone: only
// candidates within these factors of the text they are scored against can
// reach it. Skipping the rest is exact, not a heuristic.
const RELEVANT_RATIO = MIN_RATIO - AMBIGUITY_MARGIN;
const LENGTH_FACTOR_MIN = RELEVANT_RATIO / (2 - RELEVANT_RATIO);
const LENGTH_FACTOR_MAX = (2 - RELEVANT_RATIO) / RELEVANT_RATIO;

const SECTION_MARKER = /^\[[^[\]]+\]$/;

export interface LyricLineInterval {
	start: number;
	end: number;
}

export interface AlignedLyricLine {
	text: string;
	interval: LyricLineInterval | null;
}

interface PreparedCue {
	start: number;
	end: number;
	normalizedText: string;
	words: PreparedWord[];
}

interface PreparedWord {
	start: number;
	end: number;
	normalizedText: string;
}

// One run of consecutive units (words, or lyric lines) scored against the
// text it is a candidate for. `from` and `to` are inclusive unit indices.
interface Candidate {
	from: number;
	to: number;
	text: string;
	score: number;
}

function splitLyricsLines(lyrics: string): string[] {
	return lyrics.split(/\r?\n/);
}

function isAlignableLine(rawLine: string): boolean {
	const trimmed = rawLine.trim();
	return trimmed.length > 0 && !SECTION_MARKER.test(trimmed);
}

function prepareCues(cues: WhisperCue[]): PreparedCue[] {
	return cues
		.map((cue, index) => ({ cue, index }))
		.sort(
			(left, right) =>
				left.cue.start - right.cue.start || left.cue.end - right.cue.end || left.index - right.index
		)
		.map(({ cue }) => ({
			start: cue.start,
			end: cue.end,
			normalizedText: normalizeLyricsToken(cue.text),
			words: prepareWords(cue)
		}))
		.filter((cue) => cue.normalizedText.length > 0);
}

function prepareWords(cue: WhisperCue): PreparedWord[] {
	if (!cue.words) return [];
	return cue.words
		.map((word) => ({
			start: word.start,
			end: word.end,
			normalizedText: normalizeLyricsToken(word.text)
		}))
		.filter((word) => word.normalizedText.length > 0);
}

function ratio(transcribedText: string, lyricText: string): number {
	return new SequenceMatcher(transcribedText, lyricText).ratio();
}

// Every run of up to `maxUnits` consecutive units starting at or after
// `firstStart` and before `startLimit`, scored against a text of
// `targetLength` characters — runs that length alone rules out are skipped.
function collectCandidates(
	unitTexts: string[],
	firstStart: number,
	startLimit: number,
	maxUnits: number,
	targetLength: number,
	score: (candidateText: string) => number
): Candidate[] {
	const minLength = targetLength * LENGTH_FACTOR_MIN;
	const maxLength = targetLength * LENGTH_FACTOR_MAX;
	const candidates: Candidate[] = [];

	for (let from = firstStart; from < startLimit; from++) {
		let text = '';
		for (let to = from; to < unitTexts.length && to - from < maxUnits; to++) {
			text = to === from ? unitTexts[to] : `${text} ${unitTexts[to]}`;
			if (text.length > maxLength) break;
			if (text.length < minLength) continue;
			candidates.push({ from, to, text, score: score(text) });
		}
	}
	return candidates;
}

// The words of a run that take part in a matching block against the lyric
// line are the ones the line was actually sung on; a run can begin or end on
// foreign words when the line's own opening lies beyond the search window.
// The interval is derived from the first and last of the line's own words.
function matchedWordRange(
	unitTexts: string[],
	run: Candidate,
	lyricText: string
): { from: number; to: number } {
	const blocks = new SequenceMatcher(run.text, lyricText)
		.getMatchingBlocks()
		.filter((block) => block.size > 0);

	let first = -1;
	let last = -1;
	let wordStart = 0;
	for (let index = run.from; index <= run.to; index++) {
		const wordEnd = wordStart + unitTexts[index].length;
		const participates = blocks.some(
			(block) => block.a < wordEnd && block.a + block.size > wordStart
		);
		if (participates) {
			if (first === -1) first = index;
			last = index;
		}
		wordStart = wordEnd + 1;
	}
	return first === -1 ? { from: run.from, to: run.to } : { from: first, to: last };
}

function overlaps(candidate: Candidate, other: Candidate): boolean {
	return candidate.from <= other.to && candidate.to >= other.from;
}

function echoes(candidateText: string, bestText: string): boolean {
	return bestText.includes(candidateText) || candidateText.includes(bestText);
}

function chooseCandidate(candidates: Candidate[]): Candidate | null {
	let best: Candidate | null = null;
	for (const candidate of candidates) {
		if (best === null || candidate.score > best.score) best = candidate;
	}
	if (best === null || best.score < MIN_RATIO) return null;

	let rivalScore = -Infinity;
	for (const candidate of candidates) {
		if (overlaps(candidate, best) || echoes(candidate.text, best.text)) continue;
		if (candidate.score > rivalScore) rivalScore = candidate.score;
	}
	if (rivalScore !== -Infinity && best.score - rivalScore < AMBIGUITY_MARGIN) return null;

	return best;
}

function alignAgainstWords(
	words: PreparedWord[],
	lineTexts: string[],
	assign: (linePosition: number, interval: LyricLineInterval) => void
): void {
	const wordTexts = words.map((word) => word.normalizedText);

	let cursor = 0;
	for (let linePosition = 0; linePosition < lineTexts.length; linePosition++) {
		const lineText = lineTexts[linePosition];
		const chosen = chooseCandidate(
			collectCandidates(
				wordTexts,
				cursor,
				Math.min(wordTexts.length, cursor + WORD_STREAM_LOOKAHEAD),
				wordTexts.length,
				lineText.length,
				(candidateText) => ratio(candidateText, lineText)
			)
		);
		if (chosen === null) continue;
		const sung = matchedWordRange(wordTexts, chosen, lineText);
		assign(linePosition, { start: words[sung.from].start, end: words[sung.to].end });
		cursor = sung.to + 1;
	}
}

function alignAgainstCueWindows(
	cues: PreparedCue[],
	lineTexts: string[],
	assign: (linePosition: number, interval: LyricLineInterval) => void
): void {
	let floorPosition = 0;
	for (const cue of cues) {
		if (floorPosition >= lineTexts.length) break;
		const chosen = chooseCandidate(
			collectCandidates(
				lineTexts,
				floorPosition,
				lineTexts.length,
				MAX_WINDOW_LINES,
				cue.normalizedText.length,
				(candidateText) => ratio(cue.normalizedText, candidateText)
			)
		);
		if (chosen === null) continue;
		splitCueSpan(cue, lineTexts, chosen, assign);
		floorPosition = chosen.to + 1;
	}
}

function splitCueSpan(
	cue: PreparedCue,
	lineTexts: string[],
	window: Candidate,
	assign: (linePosition: number, interval: LyricLineInterval) => void
): void {
	let totalLength = 0;
	for (let position = window.from; position <= window.to; position++) {
		totalLength += lineTexts[position].length;
	}
	const span = cue.end - cue.start;

	let consumedLength = 0;
	for (let position = window.from; position <= window.to; position++) {
		const start =
			position === window.from ? cue.start : cue.start + (span * consumedLength) / totalLength;
		consumedLength += lineTexts[position].length;
		const end =
			position === window.to ? cue.end : cue.start + (span * consumedLength) / totalLength;
		assign(position, { start, end });
	}
}

// Maps whisper_cues onto the display lines of `lyrics` (split with the same
// /\r?\n/ regex the normalisation contract specifies). Every display line
// is returned, in order, including blank and [section] lines — those are
// simply never alignable and always carry a null interval.
export function alignLyricsToCues(lyrics: string, cues: WhisperCue[]): AlignedLyricLine[] {
	const rawLines = splitLyricsLines(lyrics);
	const normalizedLines = rawLines.map((line) =>
		isAlignableLine(line) ? normalizeLyricsToken(line) : ''
	);
	const candidateLineIndices = rawLines
		.map((_, index) => index)
		.filter((index) => normalizedLines[index].length > 0);
	const lineTexts = candidateLineIndices.map((index) => normalizedLines[index]);

	const intervals: (LyricLineInterval | null)[] = new Array(rawLines.length).fill(null);
	const assign = (linePosition: number, interval: LyricLineInterval) => {
		intervals[candidateLineIndices[linePosition]] = interval;
	};

	const preparedCues = prepareCues(cues);
	const words = preparedCues.flatMap((cue) => cue.words);
	if (words.length > 0) alignAgainstWords(words, lineTexts, assign);
	else alignAgainstCueWindows(preparedCues, lineTexts, assign);

	return rawLines.map((text, index) => ({ text, interval: intervals[index] }));
}

// The active line at `currentTime`, or null between cues / before the first
// / after the last — a gap is never a guess. Interval is half-open [start,
// end): a boundary time belongs to the line that starts there.
export function activeLyricLineIndex(
	lines: AlignedLyricLine[],
	currentTime: number
): number | null {
	for (let index = 0; index < lines.length; index++) {
		const interval = lines[index].interval;
		if (interval && currentTime >= interval.start && currentTime < interval.end) return index;
	}
	return null;
}
