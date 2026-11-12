import { expect, it, vi } from 'vitest';
import { loadKitWords } from 'overnightworks-design';
import { sourceLanguage } from '#lib/words/index.ts';

it('refuses a read before the kit words are loaded and answers with the kit text after the load', async () => {
	vi.resetModules();
	const fresh = await import('#lib/utils/kit-words.ts');
	expect(() => fresh.kitWords()).toThrow(/read before .* loaded/);
	await fresh.loadPageKitWords(sourceLanguage);
	expect(fresh.kitWords()).toEqual(await loadKitWords(sourceLanguage));
});

it('loads the app words and the kit words in the root layout load', async () => {
	vi.resetModules();
	const pageWords = await import('#lib/utils/page-words.ts');
	const kitWords = await import('#lib/utils/kit-words.ts');
	const { load } = await import('../../routes/+layout.ts');
	expect(() => pageWords.pageText('homeWrite.label')).toThrow();
	expect(() => kitWords.kitWords()).toThrow();
	await load({} as Parameters<typeof load>[0]);
	expect(pageWords.pageText('homeWrite.label')).toBeTypeOf('string');
	expect(kitWords.kitWords()['account.logOut']).toBeTypeOf('string');
});
