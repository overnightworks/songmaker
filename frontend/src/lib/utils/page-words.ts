import { words, type Key, type Words } from '#lib/words/en.ts';

/** What a key is read with: nothing for plain text, its gap names for a key with gaps, its count (then its gap names) for a plural family. */
type Values<K extends Key> = Words[K] extends (...values: infer V) => string ? V : [];

/** The page's one reader of its interface words: the text of a catalog key in the page's language. */
export function pageText<K extends Key>(key: K, ...values: Values<K>): string {
	const entry: Words[Key] = words[key];
	return typeof entry === 'string' ? entry : (entry as (...values: unknown[]) => string)(...values);
}
