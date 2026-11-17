import { describe, expect, it } from 'vitest';
import { pageLanguage } from './page-language.ts';
import { sourceLanguage } from '#lib/words/index.ts';

describe('pageLanguage', () => {
	it('the page language is the offered language html lang names', () => {
		document.documentElement.lang = sourceLanguage;
		expect(pageLanguage()).toBe(sourceLanguage);
	});

	it.each([
		['a page without a language', ''],
		['a language the app does not offer', 'tlh'],
		['a malformed language tag', 'not a tag'],
		['the unfilled placeholder', '%page-language%']
	])('%s fails loud', (_case, tag) => {
		document.documentElement.lang = tag;
		expect(() => pageLanguage()).toThrow(/language/i);
	});
});
