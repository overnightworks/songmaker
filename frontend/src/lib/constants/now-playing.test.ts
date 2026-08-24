import { describe, expect, it } from 'vitest';

import { nowPlayingTakeLabel, nowPlayingTakeMeta, takeBatchReductionLabel } from './now-playing';

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

describe('takeBatchReductionLabel', () => {
	it('names both numbers when the server delivered fewer takes than asked', () => {
		expect(
			takeBatchReductionLabel({ batch_size: 2, delivered_batch_size: 1 })
		).toBe('1 of 2');
	});

	it('shows nothing when delivered matches requested', () => {
		expect(takeBatchReductionLabel({ batch_size: 2, delivered_batch_size: 2 })).toBeNull();
	});

	it('shows nothing without a requested batch size on record', () => {
		expect(takeBatchReductionLabel({ delivered_batch_size: 1 })).toBeNull();
	});

	it('shows nothing without a worker-reported delivered batch size', () => {
		expect(takeBatchReductionLabel({ batch_size: 2 })).toBeNull();
	});

	it('shows nothing for a take with no generation_params at all', () => {
		expect(takeBatchReductionLabel(null)).toBeNull();
	});
});
