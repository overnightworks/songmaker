import type { LayoutLoad } from './$types';
import { loadPageKitWords } from '#lib/utils/kit-words.ts';
import { loadPageWords } from '#lib/utils/page-words.ts';
import { sourceLanguage } from '#lib/words/index.ts';

export const ssr = false;
export const prerender = false;

// The one place that decides the page's language; the page's and the kit's words load together before any route renders.
export const load: LayoutLoad = async () => {
	await Promise.all([loadPageWords(sourceLanguage), loadPageKitWords(sourceLanguage)]);
};
