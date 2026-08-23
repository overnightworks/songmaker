// Deterministic lyric↔Whisper-cue alignment (issue #45, contract confirmed
// on #52). Pure and offline-testable: no player state, no DOM coupling. The
// Now Playing lyrics column is the sole consumer.
//
// greedy_monotone: cues are assigned to lyric lines in playback-time order,
// each cue to at most one still-unassigned line, never revisiting an
// earlier line. A cue is skipped (no match) when its best candidate falls
// below MIN_RATIO, or when the best and the best differently-worded
// competitor are too close to call (AMBIGUITY_MARGIN) — identical-text
// repeats (e.g. a chorus) are never competitors to each other, so a
// repeated line is never blocked from matching by its own echo.
import type { WhisperCue } from '$lib/api/types';
import { normalizeLyricsToken } from './lyrics-normalize';
import { SequenceMatcher } from './sequence-matcher';

export const MIN_RATIO = 0.72;
export const AMBIGUITY_MARGIN = 0.12;

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
}

export function splitLyricsLines(lyrics: string): string[] {
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
			normalizedText: normalizeLyricsToken(cue.text)
		}))
		.filter((cue) => cue.normalizedText.length > 0);
}

function ratio(cueText: string, lineText: string): number {
	return new SequenceMatcher(cueText, lineText).ratio();
}

// Searches candidateLineIndices from floorPos onward for the best-matching
// line for one cue. Returns the winning position within candidateLineIndices
// (not the line index itself), or null when no line clears MIN_RATIO or the
// match is ambiguous.
function chooseCandidatePosition(
	candidateLineIndices: number[],
	floorPos: number,
	normalizedLines: string[],
	cueNormalizedText: string
): number | null {
	let bestPos: number | null = null;
	let bestScore = -Infinity;
	for (let pos = floorPos; pos < candidateLineIndices.length; pos++) {
		const score = ratio(cueNormalizedText, normalizedLines[candidateLineIndices[pos]]);
		if (score > bestScore) {
			bestScore = score;
			bestPos = pos;
		}
	}
	if (bestPos === null || bestScore < MIN_RATIO) return null;

	const bestText = normalizedLines[candidateLineIndices[bestPos]];
	let secondBestScore = -Infinity;
	for (let pos = floorPos; pos < candidateLineIndices.length; pos++) {
		if (normalizedLines[candidateLineIndices[pos]] === bestText) continue;
		const score = ratio(cueNormalizedText, normalizedLines[candidateLineIndices[pos]]);
		if (score > secondBestScore) secondBestScore = score;
	}
	if (secondBestScore !== -Infinity && bestScore - secondBestScore < AMBIGUITY_MARGIN) return null;

	return bestPos;
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

	const intervals: (LyricLineInterval | null)[] = new Array(rawLines.length).fill(null);
	const preparedCues = prepareCues(cues);

	let floorPos = 0;
	for (const cue of preparedCues) {
		if (floorPos >= candidateLineIndices.length) break;
		const chosenPos = chooseCandidatePosition(
			candidateLineIndices,
			floorPos,
			normalizedLines,
			cue.normalizedText
		);
		if (chosenPos === null) continue;
		intervals[candidateLineIndices[chosenPos]] = { start: cue.start, end: cue.end };
		floorPos = chosenPos + 1;
	}

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
