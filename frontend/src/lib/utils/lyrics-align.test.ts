import { describe, expect, it } from 'vitest';
import type { WhisperCue } from '$lib/api/types';
import { activeLyricLineIndex, alignLyricsToCues } from './lyrics-align';

// Invented lyric-like lines, never real lyrics. Deliberately far apart in
// SequenceMatcher.ratio() (verified by hand against Python's difflib) from
// one another so cross-line similarity never accidentally clears MIN_RATIO
// (0.72) — every test's outcome is driven by the specific pairing it names.
const LINE_1 = 'the lantern hums quietly tonight';
const LINE_2 = 'we count the fading city lights';
const LINE_3 = 'another mile of rusted signs';

function cue(start: number, end: number, text: string): WhisperCue {
	return { start, end, text };
}

describe('alignLyricsToCues', () => {
	it('maps exact-text cues onto their lines in playback order', () => {
		const lyrics = [LINE_1, LINE_2, LINE_3].join('\n');
		const cues = [cue(0, 1.2, LINE_1), cue(1.2, 2.5, LINE_2), cue(2.5, 3.8, LINE_3)];

		const aligned = alignLyricsToCues(lyrics, cues);

		expect(aligned.map((line) => line.interval)).toEqual([
			{ start: 0, end: 1.2 },
			{ start: 1.2, end: 2.5 },
			{ start: 2.5, end: 3.8 }
		]);
	});

	it('never highlights a line for a cue whose text deviates from all of them (false-positive precision)', () => {
		const lyrics = [LINE_1, LINE_2, LINE_3].join('\n');
		const cues = [cue(0, 1, 'a totally unrelated kitchen inventory list')];

		const aligned = alignLyricsToCues(lyrics, cues);

		expect(aligned.every((line) => line.interval === null)).toBe(true);
	});

	it('skips an unmatched adlib cue without breaking later matches', () => {
		const lyrics = [LINE_1, LINE_2, LINE_3].join('\n');
		const cues = [
			cue(0, 1, LINE_1),
			cue(1, 1.4, 'ooh yeah come on'),
			cue(1.4, 2.6, LINE_2),
			cue(2.6, 3.8, LINE_3)
		];

		const aligned = alignLyricsToCues(lyrics, cues);

		expect(aligned.map((line) => line.interval)).toEqual([
			{ start: 0, end: 1 },
			{ start: 1.4, end: 2.6 },
			{ start: 2.6, end: 3.8 }
		]);
	});

	it('leaves an omitted lyric line unmatched and still matches the one after it', () => {
		const lyrics = [LINE_1, LINE_2, LINE_3].join('\n');
		const cues = [cue(0, 1, LINE_1), cue(1, 2, LINE_3)];

		const aligned = alignLyricsToCues(lyrics, cues);

		expect(aligned.map((line) => line.interval)).toEqual([
			{ start: 0, end: 1 },
			null,
			{ start: 1, end: 2 }
		]);
	});

	it('never highlights an ambiguous cue where two differently-worded lines score within the margin', () => {
		const cueText = 'silver rain falls on the roof';
		const lineA = 'silver rain falls on the roof';
		const lineB = 'silver rain calls on the roof';
		const lyrics = [lineA, lineB].join('\n');

		const aligned = alignLyricsToCues(lyrics, [cue(0, 1, cueText)]);

		expect(aligned.every((line) => line.interval === null)).toBe(true);
	});

	it('does not treat an identically-worded repeated line (chorus) as an ambiguity competitor', () => {
		const lyrics = [
			'[verse]',
			LINE_1,
			'[chorus]',
			LINE_2,
			'',
			'[verse]',
			LINE_3,
			'[chorus]',
			LINE_2
		].join('\n');
		const cues = [cue(0, 1, LINE_1), cue(1, 2, LINE_2), cue(2, 3, LINE_3), cue(3, 4, LINE_2)];

		const aligned = alignLyricsToCues(lyrics, cues);
		const lines = lyrics.split('\n');

		expect(aligned[lines.indexOf(LINE_1)].interval).toEqual({ start: 0, end: 1 });
		expect(aligned[lines.indexOf(LINE_2)].interval).toEqual({ start: 1, end: 2 });
		expect(aligned[lines.indexOf(LINE_3)].interval).toEqual({ start: 2, end: 3 });
		expect(aligned[lines.lastIndexOf(LINE_2)].interval).toEqual({ start: 3, end: 4 });
	});

	it('drops section markers and blank lines from matching but keeps them as static display lines', () => {
		const lyrics = ['[verse]', LINE_1, '', '[chorus]', LINE_2].join('\n');

		const aligned = alignLyricsToCues(lyrics, [cue(0, 1, LINE_1), cue(1, 2, LINE_2)]);

		expect(aligned.map((line) => line.text)).toEqual(['[verse]', LINE_1, '', '[chorus]', LINE_2]);
		expect(aligned[0].interval).toBeNull();
		expect(aligned[2].interval).toBeNull();
		expect(aligned[3].interval).toBeNull();
		expect(aligned[1].interval).toEqual({ start: 0, end: 1 });
		expect(aligned[4].interval).toEqual({ start: 1, end: 2 });
	});

	it('stops assigning once every line has already been used (monotone, never revisited)', () => {
		const aligned = alignLyricsToCues(LINE_1, [cue(0, 1, LINE_1), cue(1, 2, LINE_1)]);

		expect(aligned).toEqual([{ text: LINE_1, interval: { start: 0, end: 1 } }]);
	});

	it('leaves every line unmatched when there are no cues', () => {
		const lyrics = [LINE_1, LINE_2].join('\n');

		expect(alignLyricsToCues(lyrics, []).every((line) => line.interval === null)).toBe(true);
	});

	it('sorts cues by (start, end, index) before assigning, regardless of input order', () => {
		const lyrics = [LINE_1, LINE_2].join('\n');
		const cues = [cue(1, 2, LINE_2), cue(0, 1, LINE_1)];

		const aligned = alignLyricsToCues(lyrics, cues);

		expect(aligned.map((line) => line.interval)).toEqual([
			{ start: 0, end: 1 },
			{ start: 1, end: 2 }
		]);
	});

	it('drops a cue with empty normalised text instead of consuming a line', () => {
		const lyrics = [LINE_1, LINE_2].join('\n');

		const aligned = alignLyricsToCues(lyrics, [cue(0, 1, '...'), cue(1, 2, LINE_1)]);

		expect(aligned[0].interval).toEqual({ start: 1, end: 2 });
		expect(aligned[1].interval).toBeNull();
	});
});

describe('activeLyricLineIndex', () => {
	const lines = [
		{ text: LINE_1, interval: { start: 0, end: 1 } },
		{ text: '', interval: null },
		{ text: LINE_2, interval: { start: 1.5, end: 2.5 } }
	];

	it('is active exactly at an interval start (inclusive)', () => {
		expect(activeLyricLineIndex(lines, 0)).toBe(0);
	});

	it('is not active exactly at an interval end (exclusive)', () => {
		expect(activeLyricLineIndex(lines, 1)).toBeNull();
	});

	it('has no active line in the gap between two intervals', () => {
		expect(activeLyricLineIndex(lines, 1.2)).toBeNull();
	});

	it('has no active line before the first interval', () => {
		expect(activeLyricLineIndex(lines, -1)).toBeNull();
	});

	it('has no active line after the last interval', () => {
		expect(activeLyricLineIndex(lines, 5)).toBeNull();
	});

	it('is active in the middle of an interval', () => {
		expect(activeLyricLineIndex(lines, 2)).toBe(2);
	});

	it('has no active line for an alignment with no matched lines at all', () => {
		expect(activeLyricLineIndex([{ text: LINE_1, interval: null }], 0)).toBeNull();
	});
});
