import type { Key, Words } from '#lib/words/en.ts';
import { loadWords, type Language } from '#lib/words/index.ts';

/** What a key is read with: nothing for plain text, its gap names for a key with gaps, its count (then its gap names) for a plural family. */
type Values<K extends Key> = Words[K] extends (...values: infer V) => string ? V : [];

class PageWordsNotLoadedError extends Error {
	override name = 'PageWordsNotLoadedError';
	constructor() {
		super('The page words are read before they are loaded; the root layout load loads them.');
	}
}

let loadedWords: Words | undefined;

/** Loads the page's words once at start, from the root layout's `load`, so the readers stay synchronous. */
export async function loadPageWords(language: Language): Promise<void> {
	loadedWords = await loadWords(language);
}

/** The keys whose sentence has a marked part: the generated entry is a function of its gaps that returns the sentence as parts. */
type MarkedKey = {
	[K in Key]: Words[K] extends (...values: never[]) => readonly unknown[] ? K : never;
}[Key];

/** The keys `pageText` reads: every key but the marked ones. */
export type TextKey = Exclude<Key, MarkedKey>;

type Parts<K extends MarkedKey> = Words[K] extends (...values: never[]) => infer P ? P : never;
type PartsGaps<K extends MarkedKey> = Words[K] extends (...values: infer V) => unknown ? V : never;

function loadedEntry<K extends Key>(key: K): Words[K] {
	if (loadedWords === undefined) throw new PageWordsNotLoadedError();
	return loadedWords[key];
}

/** The page's one reader of its interface words: the text of a catalog key in the page's language; a marked sentence is read with `pageParts`. */
export function pageText<K extends TextKey>(key: K, ...values: Values<K>): string {
	const entry: Words[Key] = loadedEntry(key);
	return typeof entry === 'string' ? entry : (entry as (...values: unknown[]) => string)(...values);
}

/** The page's reader of a sentence with a marked part: its parts in the page's language, which the kit's `Marked` renders. */
export function pageParts<K extends MarkedKey>(key: K, ...gaps: PartsGaps<K>): Parts<K> {
	return (loadedEntry(key) as (...gaps: unknown[]) => Parts<K>)(...gaps);
}

/**
 * The text of the catalog key a server refusal names, filled with the refusal's values, or null when the page has no such
 * entry or the entry does not yield a sentence (a marked sentence returns parts). The caller shows its own fallback and names the key.
 */
export function refusalText(key: string, values: Readonly<Record<string, string>>): string | null {
	if (loadedWords === undefined) throw new PageWordsNotLoadedError();
	if (!Object.hasOwn(loadedWords, key)) return null;
	const entry: unknown = (loadedWords as Record<string, unknown>)[key];
	if (typeof entry === 'string') return entry;
	if (typeof entry !== 'function') return null;
	const sentence: unknown = entry(values);
	return typeof sentence === 'string' ? sentence : null;
}
