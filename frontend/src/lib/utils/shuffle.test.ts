import { describe, expect, it } from 'vitest';
import { shuffled } from './shuffle';

const ITEMS = ['a', 'b', 'c', 'd', 'e', 'f'];

function alwaysDraws(value: number): () => number {
	return () => value;
}

describe('shuffled', () => {
	it.each([false, true])(
		'defect:#1509 returns a permutation of its input (keepFirst %s)',
		(keepFirst) => {
			const input = [...ITEMS];
			const result = shuffled(input, { keepFirst });
			expect([...result].sort()).toEqual(ITEMS);
			expect(input).toEqual(ITEMS);
		}
	);

	it.each([
		['draws of 0', ITEMS, false, 0, ['b', 'c', 'd', 'e', 'f', 'a']],
		['draws of 0.99', ITEMS, false, 0.99, ITEMS],
		['draws of 0 with the first kept', ITEMS, true, 0, ['a', 'c', 'd', 'e', 'f', 'b']],
		['draws of 0.99 with the first kept', ITEMS, true, 0.99, ITEMS],
		['no items', [], false, 0, []],
		['one item', ['a'], false, 0, ['a']],
		['no items with the first kept', [], true, 0, []],
		['one item with the first kept', ['a'], true, 0, ['a']],
		['two items with the first kept', ['a', 'b'], true, 0, ['a', 'b']]
	])(
		'defect:#1509 orders %s from an injected random source',
		(_name, items, keepFirst, draw, expected) => {
			expect(shuffled(items, { keepFirst, random: alwaysDraws(draw) })).toEqual(expected);
		}
	);
});
