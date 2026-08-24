import { describe, expect, it } from 'vitest';

import { nowPlayingTakeLabel, nowPlayingTakeMeta } from './now-playing';

describe('nowPlayingTakeLabel', () => {
	it('names the version and the take', () => {
		expect(nowPlayingTakeLabel(1, 3)).toBe('v1 · take 3');
	});

	it('names only the take when the row carries no version', () => {
		expect(nowPlayingTakeLabel(null, 3)).toBe('take 3');
	});
});

describe('nowPlayingTakeMeta', () => {
	// #163/5: the playlist row wrote its separators in markup, where the one
	// before the duration sat at the start of an {#if} and lost its leading
	// space — "Fable · v1 · take 1· 3:15".
	const cases = [
		{
			name: 'artist, take and duration',
			parts: { artist: 'Fable', versionNumber: 1, generationNumber: 1, durationSec: 195 },
			line: 'Fable · v1 · take 1 · 3:15'
		},
		{
			name: 'no duration on a take that has none',
			parts: { artist: 'Fable', versionNumber: 1, generationNumber: 1, durationSec: null },
			line: 'Fable · v1 · take 1'
		},
		{
			name: 'no duration on a zero-length take',
			parts: { artist: 'Fable', versionNumber: 2, generationNumber: 4, durationSec: 0 },
			line: 'Fable · v2 · take 4'
		},
		{
			name: 'no version on a library-pool take',
			parts: { artist: 'Fable', versionNumber: null, generationNumber: 7, durationSec: 61 },
			line: 'Fable · take 7 · 1:01'
		},
		{
			name: 'no artist',
			parts: { artist: null, versionNumber: 1, generationNumber: 1, durationSec: 195 },
			line: 'v1 · take 1 · 3:15'
		}
	];

	it.each(cases)('writes $name', ({ parts, line }) => {
		expect(nowPlayingTakeMeta(parts)).toBe(line);
	});
});
