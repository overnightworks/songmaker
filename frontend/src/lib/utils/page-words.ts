import { words, type Key, type Words } from '#lib/words/en.ts';

type GapKey = {
	[K in Key]: Words[K] extends (gaps: never) => string ? K : never;
}[Key];

/** No values for a key whose entry is plain text, exactly the entry's gap names for one with gaps. */
type Gaps<K extends Key> = [K] extends [GapKey] ? [gaps: Parameters<Words[K]>[0]] : [];

/** The page's one reader of its interface words: the text of a catalog key in the page's language. */
export function pageText<K extends Key>(key: K, ...[gaps]: Gaps<K>): string {
	const entry: Words[Key] = words[key];
	return typeof entry === 'string' ? entry : (entry as (values?: object) => string)(gaps);
}
