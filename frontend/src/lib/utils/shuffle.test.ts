import { describe, expect, it } from 'vitest';
import { shuffled } from './shuffle';

const ITEMS = ['a', 'b', 'c', 'd', 'e', 'f'];

function alwaysDraws(value: number): () => number {
	return () => value;
}

describe('shuffled', () => {
	it.each([false, true])('returns a permutation of its input (keepFirst %s)', (keepFirst) => {
		const input = [...ITEMS];
		const result = shuffled(input, { keepFirst });
		expect([...result].sort()).toEqual(ITEMS);
		expect(input).toEqual(ITEMS);
	});

	it('orders deterministically for an injected random source', () => {
		expect(shuffled(ITEMS, { random: alwaysDraws(0) })).toEqual(['b', 'c', 'd', 'e', 'f', 'a']);
		expect(shuffled(ITEMS, { random: alwaysDraws(0.99) })).toEqual(ITEMS);
	});

	it('keeps the first item first and shuffles only the rest', () => {
		expect(shuffled(ITEMS, { keepFirst: true, random: alwaysDraws(0) })).toEqual([
			'a',
			'c',
			'd',
			'e',
			'f',
			'b'
		]);
		expect(shuffled(ITEMS, { keepFirst: true, random: alwaysDraws(0.99) })).toEqual(ITEMS);
	});

	it.each([
		['no items', [], false],
		['one item', ['a'], false],
		['no items with the first kept', [], true],
		['one item with the first kept', ['a'], true],
		['two items with the first kept', ['a', 'b'], true]
	])('leaves %s as given', (_name, items, keepFirst) => {
		expect(shuffled(items, { keepFirst, random: alwaysDraws(0) })).toEqual(items);
	});
});
