import { describe, expect, it } from 'vitest';
import { computeDiff } from './diff';

describe('computeDiff', () => {
	it('returns empty for identical text', () => {
		const result = computeDiff('hello\nworld', 'hello\nworld');
		expect(result.every((d) => d.type === 'same')).toBe(true);
	});

	it('detects added lines', () => {
		const result = computeDiff('hello', 'hello\nworld');
		const added = result.filter((d) => d.type === 'add');
		expect(added).toHaveLength(1);
		expect(added[0].text).toBe('world');
	});

	it('detects removed lines', () => {
		const result = computeDiff('hello\nworld', 'hello');
		const removed = result.filter((d) => d.type === 'remove');
		expect(removed).toHaveLength(1);
		expect(removed[0].text).toBe('world');
	});

	it('handles empty strings', () => {
		expect(computeDiff('', '')).toEqual([]);
	});

	it('handles completely different text', () => {
		const result = computeDiff('aaa', 'bbb');
		expect(result.some((d) => d.type === 'remove')).toBe(true);
		expect(result.some((d) => d.type === 'add')).toBe(true);
	});

	it('trims trailing empty lines', () => {
		const result = computeDiff('hello\n\n', 'hello\n\n');
		expect(result).toHaveLength(1);
		expect(result[0].type).toBe('same');
	});
});
