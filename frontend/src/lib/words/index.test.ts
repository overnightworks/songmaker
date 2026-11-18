import { expect, it } from 'vitest';
import { languages, loadWords, sourceLanguage } from '#lib/words/index.ts';

it.each(languages.filter((language) => language !== sourceLanguage))(
	'offers every sentence of the source language in %s',
	async (language) => {
		const source = await loadWords(sourceLanguage);
		const translated = await loadWords(language);
		expect(Object.keys(translated).sort()).toEqual(Object.keys(source).sort());
	}
);
