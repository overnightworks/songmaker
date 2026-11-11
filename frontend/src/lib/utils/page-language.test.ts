import { describe, expect, it } from 'vitest';
import { pageLanguage } from './page-language.ts';

describe('pageLanguage', () => {
	it('the page language is the tag html lang names', () => {
		document.documentElement.lang = 'sv-se';
		expect(pageLanguage()).toBe('sv-SE');
	});

	it('a page without a language fails loud', () => {
		document.documentElement.lang = '';
		expect(() => pageLanguage()).toThrow(/language/i);
	});

	it('a malformed language tag fails loud', () => {
		document.documentElement.lang = 'not a tag';
		expect(() => pageLanguage()).toThrow(/language/i);
	});
});
