import { words, type Key } from '#lib/words/en.ts';

/** The page's one reader of its interface words: the text of a catalog key in the page's language. */
export function pageText(key: Key): string {
	return words[key];
}
