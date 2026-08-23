import { describe, expect, it } from 'vitest';
import goldenFixtures from './lyrics-align.fixtures.json';
import { SequenceMatcher } from './sequence-matcher';

describe('SequenceMatcher', () => {
	it('rates identical sequences as a perfect match', () => {
		expect(new SequenceMatcher('same text', 'same text').ratio()).toBe(1);
	});

	it('rates two empty sequences as a perfect match', () => {
		expect(new SequenceMatcher('', '').ratio()).toBe(1);
	});

	it('rates an empty sequence against a non-empty one as zero', () => {
		expect(new SequenceMatcher('', 'not empty').ratio()).toBe(0);
	});

	it('finds the longest common run inside both sequences', () => {
		const match = new SequenceMatcher('abcdef', 'xxabcdyy').findLongestMatch();
		expect(match).toEqual({ a: 0, b: 2, size: 4 });
	});

	it('returns matching blocks that fully cover any overlap, ending in the zero-size sentinel', () => {
		const blocks = new SequenceMatcher('abxcd', 'abycd').getMatchingBlocks();
		expect(blocks).toEqual([
			{ a: 0, b: 0, size: 2 },
			{ a: 3, b: 3, size: 2 },
			{ a: 5, b: 5, size: 0 }
		]);
	});

	it('is symmetric under argument order for a hand-checked pair', () => {
		expect(new SequenceMatcher('walking home', 'walking there').ratio()).toBeCloseTo(
			new SequenceMatcher('walking there', 'walking home').ratio(),
			10
		);
	});

	describe('golden Python ratios (scripts/lyric_alignment_golden.py)', () => {
		it.each(goldenFixtures.fixtures)(
			'matches Python bit-for-bit: $name',
			({ cue, line, ratio }) => {
				expect(new SequenceMatcher(cue, line).ratio()).toBe(ratio);
			}
		);
	});
});
