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
// three still-unconsumed lines, and every line of that run carries the whole
// cue span. Nothing in such a take says where inside the cue one line ends
// and the next begins, so those lines light together rather than on invented
// per-line timing (#45); only a re-score buys real per-line intervals.
//
// Both paths share the same accept rule: the best candidate must clear
// MIN_RATIO, and it must beat every rival by AMBIGUITY_MARGIN. A rival is a
// candidate that does not overlap the winner and reads differently from it —
// overlapping candidates are the same rendition seen through a shifted
// window, and identical text cannot disambiguate anything, which is why a
// chorus line is never blocked by a word-for-word repeat of itself (#45).
// Anything short of that leaves the line dark: a missed highlight is a gap,
// a wrong one is a lie.
import type { WhisperCue } from '$lib/api/types';
import { normalizeLyricsToken } from './lyrics-normalize';
import { SequenceMatcher } from './sequence-matcher';

const MIN_RATIO = 0.72;
const AMBIGUITY_MARGIN = 0.12;
const MAX_WINDOW_LINES = 3;
// A lyric line of one or two words is too short for a character ratio to tell
// a real rendition from a coincidence — "yeah" already scores 0.75 against a
// sung "year". Such a line is lit only where the take sings it word for word.
const VERBATIM_MAX_TOKENS = 2;
// How far past the previous line's last word the search looks before it has
// to grow. Consecutive lines follow each other directly in the stream, so one
// step is already room for roughly three lines of adlibs or skipped text, and
// a line that sits right where it is expected costs only this one step.
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

function countTokens(text: string): number {
	return text.length === 0 ? 0 : text.split(' ').length;
}

function scoreAgainstLyrics(transcribedText: string, lyricText: string): number {
	if (countTokens(lyricText) <= VERBATIM_MAX_TOKENS && transcribedText !== lyricText) return 0;
	return ratio(transcribedText, lyricText);
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

function chooseCandidate(candidates: Candidate[]): Candidate | null {
	let best: Candidate | null = null;
	for (const candidate of candidates) {
		if (best === null || candidate.score > best.score) best = candidate;
	}
	if (best === null || best.score < MIN_RATIO) return null;

	let rivalScore = -Infinity;
	for (const candidate of candidates) {
		if (overlaps(candidate, best) || candidate.text === best.text) continue;
		if (candidate.score > rivalScore) rivalScore = candidate.score;
	}
	if (rivalScore !== -Infinity && best.score - rivalScore < AMBIGUITY_MARGIN) return null;

	return best;
}

// Candidates for one line, taken a horizon at a time until the take offers a
// plausible reading of it or the stream runs out. A stretch of adlibbed or
// mistranscribed words must not hide every line behind it, and only a line
// the take has no reading for at all pays for scanning the rest of the take.
function collectWithGrowingWindow(
	wordTexts: string[],
	cursor: number,
	lineText: string
): Candidate[] {
	const candidates: Candidate[] = [];
	let scanned = cursor;
	let plausible = false;

	while (scanned < wordTexts.length && !plausible) {
		const limit = Math.min(wordTexts.length, scanned + WORD_STREAM_LOOKAHEAD);
		for (const candidate of collectCandidates(
			wordTexts,
			scanned,
			limit,
			wordTexts.length,
			lineText.length,
			(candidateText) => scoreAgainstLyrics(candidateText, lineText)
		)) {
			candidates.push(candidate);
			if (candidate.score >= MIN_RATIO) plausible = true;
		}
		scanned = limit;
	}
	return candidates;
}

// Neighbouring lines are resolved as a pair whenever they claim the same
// words — a line that is the opening of the next one otherwise takes that
// opening for itself and leaves the line actually sung dark. The claim goes
// to whichever of the two wins by AMBIGUITY_MARGIN; if neither does, the take
// cannot say which line was sung there and both stay dark.
function alignAgainstWords(
	words: PreparedWord[],
	lineTexts: string[],
	assign: (linePosition: number, interval: LyricLineInterval) => void
): void {
	const wordTexts = words.map((word) => word.normalizedText);

	let cursor = 0;
	let lostToPredecessor = -1;
	let remembered: { linePosition: number; cursor: number; candidate: Candidate | null } | null =
		null;

	const claimOf = (linePosition: number): Candidate | null => {
		if (linePosition >= lineTexts.length) return null;
		if (remembered?.linePosition === linePosition && remembered.cursor === cursor) {
			return remembered.candidate;
		}
		const candidate = chooseCandidate(
			collectWithGrowingWindow(wordTexts, cursor, lineTexts[linePosition])
		);
		remembered = { linePosition, cursor, candidate };
		return candidate;
	};

	for (let linePosition = 0; linePosition < lineTexts.length; linePosition++) {
		if (linePosition === lostToPredecessor) continue;
		const claim = claimOf(linePosition);
		if (claim === null) continue;

		const nextClaim = claimOf(linePosition + 1);
		if (nextClaim !== null && overlaps(nextClaim, claim)) {
			if (nextClaim.score - claim.score >= AMBIGUITY_MARGIN) continue;
			if (claim.score - nextClaim.score < AMBIGUITY_MARGIN) {
				lostToPredecessor = linePosition + 1;
				continue;
			}
		}

		const sung = matchedWordRange(wordTexts, claim, lineTexts[linePosition]);
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
				(candidateText) => scoreAgainstLyrics(cue.normalizedText, candidateText)
			)
		);
		if (chosen === null) continue;
		for (let position = chosen.from; position <= chosen.to; position++) {
			assign(position, { start: cue.start, end: cue.end });
		}
		floorPosition = chosen.to + 1;
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
