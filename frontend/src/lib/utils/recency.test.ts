import { describe, expect, it } from 'vitest';
import { compareByCreatedAt, formatExactLocalTime, formatRelativeAge } from './recency';

const NOW = new Date('2026-08-20T12:00:00.000Z');

describe('formatRelativeAge', () => {
	it('formats seconds', () => {
		expect(formatRelativeAge('2026-08-20T11:59:20.000Z', NOW)).toBe('40s');
	});

	it('formats minutes', () => {
		expect(formatRelativeAge('2026-08-20T11:50:00.000Z', NOW)).toBe('10m');
	});

	it('formats hours', () => {
		expect(formatRelativeAge('2026-08-20T09:00:00.000Z', NOW)).toBe('3h');
	});

	it('formats days', () => {
		expect(formatRelativeAge('2026-08-18T12:00:00.000Z', NOW)).toBe('2d');
	});

	it('labels a future timestamp', () => {
		expect(formatRelativeAge('2026-08-21T12:00:00.000Z', NOW)).toBe('soon');
	});

	it('labels invalid and missing timestamps', () => {
		expect(formatRelativeAge('not-a-date', NOW)).toBe('unknown');
		expect(formatRelativeAge(null, NOW)).toBe('unknown');
		expect(formatRelativeAge(undefined, NOW)).toBe('unknown');
	});
});

describe('formatExactLocalTime', () => {
	it('returns a non-empty locale string for a valid time', () => {
		expect(formatExactLocalTime('2026-08-20T12:00:00.000Z').length).toBeGreaterThan(0);
	});

	it('labels invalid timestamps for assistive text', () => {
		expect(formatExactLocalTime('nope')).toBe('unknown time');
	});
});

describe('compareByCreatedAt', () => {
	const older = { id: 'a', title: 'Beta', created_at: '2026-01-01T00:00:00.000Z' };
	const newer = { id: 'b', title: 'Alpha', created_at: '2026-06-01T00:00:00.000Z' };
	const sameTimeA = { id: 'c', title: 'Same', created_at: '2026-03-01T00:00:00.000Z' };
	const sameTimeB = { id: 'd', title: 'Same', created_at: '2026-03-01T00:00:00.000Z' };
	const missing = { id: 'z', title: 'Zebra', created_at: null };

	it('sorts newest first with id tie-break', () => {
		expect([older, newer].sort((a, b) => compareByCreatedAt(a, b, 'newest'))).toEqual([
			newer,
			older
		]);
		expect(
			[sameTimeB, sameTimeA]
				.sort((a, b) => compareByCreatedAt(a, b, 'newest'))
				.map((item) => item.id)
		).toEqual(['c', 'd']);
	});

	it('sorts oldest first', () => {
		expect([newer, older].sort((a, b) => compareByCreatedAt(a, b, 'oldest'))).toEqual([
			older,
			newer
		]);
	});

	it('sorts by title then id', () => {
		expect([older, newer].sort((a, b) => compareByCreatedAt(a, b, 'title'))).toEqual([
			newer,
			older
		]);
	});

	it('places missing or invalid dates last', () => {
		expect(
			[missing, older, { id: 'bad', title: 'Bad', created_at: 'nope' }].sort((a, b) =>
				compareByCreatedAt(a, b, 'newest')
			)
		).toEqual([older, { id: 'bad', title: 'Bad', created_at: 'nope' }, missing]);
	});
});
