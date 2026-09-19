import { describe, expect, it } from 'vitest';
import { compareByCreatedAt } from './recency';

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
