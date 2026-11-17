import type { LayoutLoad } from './$types';
import { loadPageKitWords } from '#lib/utils/kit-words.ts';
import { loadPageWords } from '#lib/utils/page-words.ts';
import { pageLanguage } from '#lib/utils/page-language.ts';

export const ssr = false;
export const prerender = false;

// The one place that loads the page's words, for the language the server wrote into `<html lang>`; the page's and the kit's words load together before any route renders.
export const load: LayoutLoad = async () => {
	const language = pageLanguage();
	await Promise.all([loadPageWords(language), loadPageKitWords(language)]);
};
