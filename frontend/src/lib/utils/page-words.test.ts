import { expect, it, vi } from 'vitest';
import { pageParts, pageText } from '#lib/utils/page-words.ts';
import { words } from '#lib/words/en.ts';
import { sourceLanguage } from '#lib/words/index.ts';

it('reads a key without gaps as its text', () => {
	expect(pageText('homeWrite.label')).toBe(words['homeWrite.label']);
});

it('fills the gaps of a key with its named values', () => {
	expect(pageText('homeWrite.openSong', { title: 'Quiet Fire' })).toBe(
		words['homeWrite.openSong']({ title: 'Quiet Fire' })
	);
});

it('reads a family with a count as the sentence of its plural category', () => {
	expect(pageText('rail.trackTakes', 1)).toBe(words['rail.trackTakes'](1));
	expect(pageText('rail.trackTakes', 3)).toBe(words['rail.trackTakes'](3));
	expect(pageText('rail.trackTakes', 1)).not.toBe(pageText('rail.trackTakes', 2));
});

it('reads a sentence with a marked part as its parts, filled with the gap values', () => {
	expect(pageParts('newPlace.heading', { library: 'Library' })).toEqual(
		words['newPlace.heading']({ library: 'Library' })
	);
});

it('refuses, at type check, values for a plain key and a missing or misnamed gap', () => {
	// @ts-expect-error a plain key takes no values
	void (() => pageText('homeWrite.label', { title: 'x' }));
	// @ts-expect-error a key with a gap requires its values
	void (() => pageText('homeWrite.openSong'));
	// @ts-expect-error the values name exactly the entry's gaps
	void (() => pageText('homeWrite.openSong', { time: 'today' }));
	// @ts-expect-error a family requires its count
	void (() => pageText('rail.trackTakes'));
	// @ts-expect-error a family's count is a number
	void (() => pageText('rail.trackTakes', 'two'));
	// @ts-expect-error a plain key takes no count
	void (() => pageText('rail.retry', 1));
	// @ts-expect-error parts are read for a marked sentence only
	void (() => pageParts('homeWrite.label'));
	// @ts-expect-error a marked sentence requires its gaps
	void (() => pageParts('newPlace.heading'));
	// @ts-expect-error a marked sentence is read with its parts, never as text
	void (() => pageText('newPlace.heading'));
	expect(() => pageText('homeWrite.label')).not.toThrow();
});

it('refuses a read before the words are loaded and answers after the load', async () => {
	vi.resetModules();
	const fresh = await import('#lib/utils/page-words.ts');
	expect(() => fresh.pageText('homeWrite.label')).toThrow(/read before .* loaded/);
	expect(() => fresh.pageParts('newPlace.heading', { library: 'Library' })).toThrow(
		/read before .* loaded/
	);
	await fresh.loadPageWords(sourceLanguage);
	expect(fresh.pageText('homeWrite.label')).toBe(words['homeWrite.label']);
});
