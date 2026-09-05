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
// candidate that overlaps neither the winner nor any word-for-word repeat of
// the winner's text. Overlapping candidates are one rendition seen through a
// shifted window, and a repeat of the same words is not independent evidence
// of where the line was sung (#45) — nor is a shifted window around such a
// repeat, which is why a chorus line is never blocked by its own repeats.
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
// How alike two runs of the same length must read to count as the same words
// sung twice, rather than as two different readings. Whisper drops a
// consonant on one rendition and not the other ("…until the mornin" against
// "…until the morning"), and a repeat is never independent evidence of where
// a line was sung — it only decides, in playback order, which rendition each
// line takes. The tolerance applies only where the lyrics really do ask for
// those words more than once; for a line the lyrics carry once, two readings
// that close are the ambiguity #45 refuses to guess at, and for lyric lines
// themselves (the cue window path) only word-for-word repetition counts —
// near-identical lines are different lines, not slips of a transcript.
const REPEAT_MIN_RATIO = 0.88;
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

// Runs of the same length that read the winner back, wherever they sit in
// the stream — read off the stream itself rather than off the candidates that
// happened to be collected, so a repeat just outside the search window still
// dominates the shifted views of it that reach inside. The scan reaches one
// run past the collected candidates, which is as far as a repeat can sit and
// still overlap one of them.
function repeatsOfWinner(
	unitTexts: string[],
	candidates: Candidate[],
	winner: Candidate,
	tolerateSlips: boolean
): Candidate[] {
	const length = winner.to - winner.from + 1;
	const { earliestStart, latestEnd } = candidateBounds(candidates, winner);

	const repeats: Candidate[] = [];
	const first = Math.max(0, earliestStart - length + 1);
	const last = Math.min(unitTexts.length - length, latestEnd);
	for (let from = first; from <= last; from++) {
		const text = unitTexts.slice(from, from + length).join(' ');
		if (!isRepeatOfWinner(text, winner.text, tolerateSlips)) continue;
		repeats.push({ ...winner, from, to: from + length - 1, text });
	}
	return repeats;
}

function candidateBounds(
	candidates: Candidate[],
	winner: Candidate
): {
	earliestStart: number;
	latestEnd: number;
} {
	let earliestStart = winner.from;
	let latestEnd = winner.to;
	for (const candidate of candidates) {
		if (candidate.from < earliestStart) earliestStart = candidate.from;
		if (candidate.to > latestEnd) latestEnd = candidate.to;
	}
	return { earliestStart, latestEnd };
}

function isRepeatOfWinner(text: string, winnerText: string, tolerateSlips: boolean): boolean {
	if (!tolerateSlips) return text === winnerText;

	const reach = (2 * Math.min(text.length, winnerText.length)) / (text.length + winnerText.length);
	return reach >= REPEAT_MIN_RATIO && ratio(text, winnerText) >= REPEAT_MIN_RATIO;
}

function chooseCandidate(
	unitTexts: string[],
	candidates: Candidate[],
	tolerateSlips: boolean
): Candidate | null {
	const best = highestScoringCandidate(candidates);
	if (best === null || best.score < MIN_RATIO) return null;

	const repeats = repeatsOfWinner(unitTexts, candidates, best, tolerateSlips);
	const rivalScore = highestIndependentRivalScore(candidates, repeats);
	if (rivalScore !== -Infinity && best.score - rivalScore < AMBIGUITY_MARGIN) return null;

	// Of several renditions of the same words, this line takes the earliest
	// still in reach; the later ones are left for the lines that come after.
	return earliestRepeatCandidate(candidates, repeats, best);
}

function highestScoringCandidate(candidates: Candidate[]): Candidate | null {
	let best: Candidate | null = null;
	for (const candidate of candidates) {
		if (best === null || candidate.score > best.score) best = candidate;
	}
	return best;
}

function highestIndependentRivalScore(candidates: Candidate[], repeats: Candidate[]): number {
	let rivalScore = -Infinity;
	for (const candidate of candidates) {
		if (repeats.some((repeat) => overlaps(candidate, repeat))) continue;
		if (candidate.score > rivalScore) rivalScore = candidate.score;
	}
	return rivalScore;
}

function earliestRepeatCandidate(
	candidates: Candidate[],
	repeats: Candidate[],
	best: Candidate
): Candidate {
	let earliest = best;
	for (const candidate of candidates) {
		if (candidate.score < MIN_RATIO || candidate.from >= earliest.from) continue;
		if (!repeats.some((repeat) => repeat.from === candidate.from && repeat.to === candidate.to)) {
			continue;
		}
		earliest = candidate;
	}
	return earliest;
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

// #52's rival definition covers lines, not only candidates: a run belongs to
// this line only while no other line still in play reads it just as well. In
// play means from the floor onwards — every line the take has not yet moved
// past, above this one as well as below, which is the same set the cue window
// path competes over. Scanning only downwards would hand a run that a group
// of lines read alike to whichever of them comes last, and lighting a line
// the take never sang is the one thing this alignment must not do. A line
// carrying the same text is never a rival: the take simply sings those words
// more than once, and the renditions are handed out in order.
function anotherLineReadsRunAsWell(
	lineTexts: string[],
	floorPosition: number,
	linePosition: number,
	run: Candidate
): boolean {
	for (let other = floorPosition; other < lineTexts.length; other++) {
		if (other === linePosition) continue;
		if (lineTexts[other] === lineTexts[linePosition]) continue;
		if (run.score - scoreAgainstLyrics(run.text, lineTexts[other]) < AMBIGUITY_MARGIN) return true;
	}
	return false;
}

// The converse of the rival test. This line's run can be a slice of a longer
// phrase that a line further down sings — its opening, its tail, or a piece
// in the middle. Every phrase that contains the run is therefore read back:
// any waiting line that reads such a phrase at MIN_RATIO and reads it better
// than this line does has a claim on those words. Lines carrying this line's
// own text are not contenders — the take simply sings them again.
function contestingLines(
	wordTexts: string[],
	lineTexts: string[],
	linePosition: number,
	run: Candidate,
	floor: number
): number[] {
	const waiting = waitingLinePositions(lineTexts, linePosition);
	if (waiting.length === 0) return [];
	const maxPhraseLength =
		Math.max(...waiting.map((other) => lineTexts[other].length)) * LENGTH_FACTOR_MAX;

	const contesting: number[] = [];
	for (const phrase of phrasesContainingRun(wordTexts, run, floor, maxPhraseLength)) {
		addContestingLinesForPhrase(phrase, lineTexts, linePosition, waiting, contesting);
	}
	return contesting;
}

function waitingLinePositions(lineTexts: string[], linePosition: number): number[] {
	const waiting: number[] = [];
	for (let other = linePosition + 1; other < lineTexts.length; other++) {
		if (lineTexts[other] !== lineTexts[linePosition]) waiting.push(other);
	}
	return waiting;
}

function* phrasesContainingRun(
	wordTexts: string[],
	run: Candidate,
	floor: number,
	maxPhraseLength: number
): Iterable<string> {
	let opening = '';
	for (let first = run.from; first >= floor; first--) {
		if (first < run.from) {
			opening = opening === '' ? wordTexts[first] : `${wordTexts[first]} ${opening}`;
		}
		const phrase = opening === '' ? run.text : `${opening} ${run.text}`;
		if (phrase.length > maxPhraseLength) break;

		yield* phraseExtensionsAfterRun(wordTexts, run, first, phrase, maxPhraseLength);
	}
}

function* phraseExtensionsAfterRun(
	wordTexts: string[],
	run: Candidate,
	first: number,
	phrase: string,
	maxPhraseLength: number
): Iterable<string> {
	for (let last = run.to; last < wordTexts.length; last++) {
		if (last > run.to) phrase = `${phrase} ${wordTexts[last]}`;
		if (phrase.length > maxPhraseLength) break;
		if (first === run.from && last === run.to) continue;
		yield phrase;
	}
}

function addContestingLinesForPhrase(
	phrase: string,
	lineTexts: string[],
	linePosition: number,
	waiting: number[],
	contesting: number[]
): void {
	const ownReading = scoreAgainstLyrics(phrase, lineTexts[linePosition]);
	for (const other of waiting) {
		if (contesting.includes(other)) continue;
		if (!canReadPhraseBetter(phrase, lineTexts[other], ownReading)) continue;
		const reading = scoreAgainstLyrics(phrase, lineTexts[other]);
		if (reading >= MIN_RATIO && reading > ownReading) contesting.push(other);
	}
}

function canReadPhraseBetter(phrase: string, lyricText: string, ownReading: number): boolean {
	// ratio() cannot exceed this, so a line whose length alone rules out both
	// MIN_RATIO and beating this line's own reading is skipped unscored. Exact,
	// not a heuristic.
	const reach =
		(2 * Math.min(phrase.length, lyricText.length)) / (phrase.length + lyricText.length);
	return reach >= MIN_RATIO && reach > ownReading;
}

// Lines take their runs in playback order, and a run is only handed over when
// nothing else explains it: no other waiting line reads that run as well, and
// no waiting line owns a longer phrase starting on it that taking these words
// would strand. That is what stops a line from swallowing the opening of a
// line further down — while a line that has a rendition of its own elsewhere
// never blocks this one.
function alignAgainstWords(
	words: PreparedWord[],
	lineTexts: string[],
	assign: (linePosition: number, interval: LyricLineInterval) => void
): void {
	const wordTexts = words.map((word) => word.normalizedText);
	// Whether the lyrics ask for this line's words more than once. Only then
	// are two near-identical readings two renditions rather than a choice the
	// take cannot make.
	const lyricsRepeatTheLine = lineTexts.map(
		(text) => lineTexts.filter((other) => other === text).length > 1
	);
	const claims = new Map<string, Candidate | null>();

	const claimOf = (linePosition: number, from: number): Candidate | null => {
		if (linePosition >= lineTexts.length) return null;
		const key = `${linePosition}:${from}`;
		const known = claims.get(key);
		if (known !== undefined) return known;
		const claim = chooseCandidate(
			wordTexts,
			collectWithGrowingWindow(wordTexts, from, lineTexts[linePosition]),
			lyricsRepeatTheLine[linePosition]
		);
		claims.set(key, claim);
		return claim;
	};

	let cursor = 0;
	// The first line the take has not moved past: assigning a line drops every
	// line above it out of the running, exactly as the cue window path's floor
	// does.
	let floorPosition = 0;

	for (let linePosition = 0; linePosition < lineTexts.length; linePosition++) {
		const claim = claimOf(linePosition, cursor);
		if (claim === null) continue;
		if (anotherLineReadsRunAsWell(lineTexts, floorPosition, linePosition, claim)) continue;

		const sung = matchedWordRange(wordTexts, claim, lineTexts[linePosition]);
		const stranded = contestingLines(wordTexts, lineTexts, linePosition, claim, cursor).some(
			(other) => claimOf(other, sung.to + 1) === null
		);
		if (stranded) continue;

		assign(linePosition, { start: words[sung.from].start, end: words[sung.to].end });
		floorPosition = linePosition + 1;
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
			lineTexts,
			collectCandidates(
				lineTexts,
				floorPosition,
				lineTexts.length,
				MAX_WINDOW_LINES,
				cue.normalizedText.length,
				(candidateText) => scoreAgainstLyrics(cue.normalizedText, candidateText)
			),
			false
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
