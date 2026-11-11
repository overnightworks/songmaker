import { expect, it } from 'vitest';
import { pageText } from '#lib/utils/page-words.ts';
import { words } from '#lib/words/en.ts';

it('reads a key without gaps as its text', () => {
	expect(pageText('homeWrite.label')).toBe(words['homeWrite.label']);
});

it('fills the gaps of a key with its named values', () => {
	expect(pageText('homeWrite.openSong', { title: 'Quiet Fire' })).toBe(
		words['homeWrite.openSong']({ title: 'Quiet Fire' })
	);
});

it('refuses, at type check, values for a plain key and a missing or misnamed gap', () => {
	// @ts-expect-error a plain key takes no values
	void (() => pageText('homeWrite.label', { title: 'x' }));
	// @ts-expect-error a key with a gap requires its values
	void (() => pageText('homeWrite.openSong'));
	// @ts-expect-error the values name exactly the entry's gaps
	void (() => pageText('homeWrite.openSong', { time: 'today' }));
	expect(() => pageText('homeWrite.label')).not.toThrow();
});
