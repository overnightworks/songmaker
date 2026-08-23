import { describe, expect, it } from 'vitest';
import type { WhisperCue } from '$lib/api/types';
import golden from './lyrics-align.fixtures.json';
import { activeLyricLineIndex, alignLyricsToCues } from './lyrics-align';

// Invented lyric-like lines, never real lyrics. Deliberately far apart in
// SequenceMatcher.ratio() (verified by hand against Python's difflib) from
// one another so cross-line similarity never accidentally clears MIN_RATIO
// (0.72) — every test's outcome is driven by the specific pairing it names.
const LINE_1 = 'the lantern hums quietly tonight';
const LINE_2 = 'we count the fading city lights';
const LINE_3 = 'another mile of rusted signs';

const CHORUS = 'hold the line until the morning';

function cue(start: number, end: number, text: string): WhisperCue {
	return { start, end, text };
}

// A cue as a take scored with word timestamps carries it: one word every
// `secondsPerWord` seconds from `start`. Only powers of two are used as the
// pace so every expected boundary is an exact binary fraction.
function sungCue(start: number, secondsPerWord: number, text: string): WhisperCue {
	const words = text.split(' ').map((word, index) => ({
		start: start + index * secondsPerWord,
		end: start + (index + 1) * secondsPerWord,
		text: word
	}));
	return { start: words[0].start, end: words[words.length - 1].end, text, words };
}

describe('alignLyricsToCues without word timestamps (cue window fallback)', () => {
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
	it('splits a cue that covers two lines into a share for each, in order', () => {
		const lyrics = [LINE_1, LINE_2].join('\n');

		const aligned = alignLyricsToCues(lyrics, [cue(0, 6.3, `${LINE_1} ${LINE_2}`)]);
		const [first, second] = aligned.map((line) => line.interval);

		expect(first?.start).toBe(0);
		expect(second?.end).toBe(6.3);
		expect(first?.end).toBe(second?.start);
		expect(first?.end).toBeGreaterThan(0);
		expect(first?.end).toBeLessThan(6.3);
	});

	it('leaves the lines outside a cue window dark (false-positive precision)', () => {
		const lyrics = [LINE_1, LINE_2, LINE_3].join('\n');

		const aligned = alignLyricsToCues(lyrics, [cue(0, 3, LINE_1)]);

		expect(aligned.map((line) => line.interval)).toEqual([{ start: 0, end: 3 }, null, null]);
	});
});

describe('alignLyricsToCues with word timestamps', () => {
	it('gives every line the span of its own first and last sung word', () => {
		const lyrics = [LINE_1, LINE_2, LINE_3].join('\n');

		const aligned = alignLyricsToCues(lyrics, [sungCue(0, 0.5, `${LINE_1} ${LINE_2} ${LINE_3}`)]);

		expect(aligned.map((line) => line.interval)).toEqual([
			{ start: 0, end: 2.5 },
			{ start: 2.5, end: 5.5 },
			{ start: 5.5, end: 8 }
		]);
	});

	it('leaves a line the singer skipped dark and times the next one correctly', () => {
		const lyrics = [LINE_1, LINE_2, LINE_3].join('\n');

		const aligned = alignLyricsToCues(lyrics, [sungCue(0, 0.5, `${LINE_1} ${LINE_3}`)]);

		expect(aligned.map((line) => line.interval)).toEqual([
			{ start: 0, end: 2.5 },
			null,
			{ start: 2.5, end: 5 }
		]);
	});

	it('leaves adlib words between two lines out of both intervals', () => {
		const lyrics = [LINE_1, LINE_2].join('\n');

		const aligned = alignLyricsToCues(lyrics, [
			sungCue(0, 0.5, `${LINE_1} ooh yeah come on ${LINE_2}`)
		]);

		expect(aligned.map((line) => line.interval)).toEqual([
			{ start: 0, end: 2.5 },
			{ start: 4.5, end: 7.5 }
		]);
	});

	it('lights a repeated chorus line at each of its repeats', () => {
		const lyrics = [LINE_1, CHORUS, LINE_3, CHORUS].join('\n');

		const aligned = alignLyricsToCues(lyrics, [
			sungCue(0, 0.5, `${LINE_1} ${CHORUS} ${LINE_3} ${CHORUS}`)
		]);

		expect(aligned.map((line) => line.interval)).toEqual([
			{ start: 0, end: 2.5 },
			{ start: 2.5, end: 5.5 },
			{ start: 5.5, end: 8 },
			{ start: 8, end: 11 }
		]);
	});

	it('starts a line at its own first sung word, not at foreign words before it', () => {
		const lyrics = [LINE_1, LINE_2].join('\n');
		const filler = new Array(30).fill('la').join(' ');

		const aligned = alignLyricsToCues(lyrics, [sungCue(0, 0.5, `${LINE_1} ${filler} ${LINE_2}`)]);

		expect(aligned.map((line) => line.interval)).toEqual([
			{ start: 0, end: 2.5 },
			{ start: 17.5, end: 20.5 }
		]);
	});

	it('still finds the lines behind a long stretch of unmatched words', () => {
		const lyrics = [LINE_1, LINE_2, LINE_3].join('\n');
		const filler = new Array(96).fill('la').join(' ');

		const aligned = alignLyricsToCues(lyrics, [
			sungCue(0, 0.5, `${LINE_1} ${filler} ${LINE_2} ${LINE_3}`)
		]);

		expect(aligned.map((line) => line.interval)).toEqual([
			{ start: 0, end: 2.5 },
			{ start: 50.5, end: 53.5 },
			{ start: 53.5, end: 56 }
		]);
	});

	it('leaves a two-word line dark when the take only sings something like it', () => {
		const lyrics = ['yeah', LINE_1].join('\n');

		const aligned = alignLyricsToCues(lyrics, [sungCue(0, 0.5, `a year ago ${LINE_1}`)]);

		expect(aligned.map((line) => line.interval)).toEqual([null, { start: 1.5, end: 4 }]);
	});

	it('lights a two-word line where the take sings it word for word', () => {
		const lyrics = ['yeah', LINE_1].join('\n');

		const aligned = alignLyricsToCues(lyrics, [sungCue(0, 0.5, `yeah ${LINE_1}`)]);

		expect(aligned.map((line) => line.interval)).toEqual([
			{ start: 0, end: 0.5 },
			{ start: 0.5, end: 3 }
		]);
	});

	it('leaves both dark when a line is the opening of the next one and only one was sung', () => {
		const lyrics = ['hold the line', CHORUS].join('\n');

		const aligned = alignLyricsToCues(lyrics, [sungCue(0, 0.5, CHORUS)]);

		expect(aligned.map((line) => line.interval)).toEqual([null, null]);
	});

	it('never lights a line when no run of words matches it (false-positive precision)', () => {
		const lyrics = [LINE_1, LINE_2].join('\n');

		const aligned = alignLyricsToCues(lyrics, [
			sungCue(0, 0.5, 'a totally unrelated kitchen inventory list')
		]);

		expect(aligned.every((line) => line.interval === null)).toBe(true);
	});

	it('aligns against the words alone when only some segments carry them', () => {
		const lyrics = [LINE_1, LINE_2].join('\n');

		const aligned = alignLyricsToCues(lyrics, [sungCue(0, 0.5, LINE_1), cue(2.5, 5, LINE_2)]);

		expect(aligned.map((line) => line.interval)).toEqual([{ start: 0, end: 2.5 }, null]);
	});
});

describe('golden alignments from scripts/lyric_alignment_golden.py', () => {
	it.each(golden.alignments)('matches the reference implementation — $name', (fixture) => {
		const aligned = alignLyricsToCues(fixture.lyrics, fixture.cues as WhisperCue[]);

		expect(aligned.map((line) => line.interval)).toEqual(fixture.intervals);
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
