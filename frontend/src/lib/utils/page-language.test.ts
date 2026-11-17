import { describe, expect, it } from 'vitest';
import { pageLanguage } from './page-language.ts';
import { sourceLanguage } from '#lib/words/index.ts';

describe('pageLanguage', () => {
	it('the page language is the offered language html lang names', () => {
		document.documentElement.lang = sourceLanguage;
		expect(pageLanguage()).toBe(sourceLanguage);
	});

	it('a page without a language fails loud', () => {
		document.documentElement.lang = '';
		expect(() => pageLanguage()).toThrow(/language/i);
	});

	it('a language the app does not offer fails loud', () => {
		document.documentElement.lang = 'tlh';
		expect(() => pageLanguage()).toThrow(/language/i);
	});

	it('a malformed language tag fails loud', () => {
		document.documentElement.lang = 'not a tag';
		expect(() => pageLanguage()).toThrow(/language/i);
	});
});
