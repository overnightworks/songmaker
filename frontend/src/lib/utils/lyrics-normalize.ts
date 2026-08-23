// Normalizes a single lyrics/transcript token (or line) so that punctuation
// and casing differences never register as sung deviations — only an
// actually different word does. Contract from issue #45: unify curly
// apostrophe variants to a straight one, NFKC-normalize, casefold, strip
// punctuation (keeping an apostrophe that sits between two word
// characters, e.g. "don't"), then collapse whitespace. Casefold must match
// Python's `str.casefold()` (issue #133), which JS has no native
// equivalent for — `String.prototype.toLowerCase()` only implements
// Unicode *simple* case mapping, not *full* case folding.
const CURLY_APOSTROPHES = /[‘’‛ʼ]/g;
const WORD_CHAR = /[\p{L}\p{N}_]/u;

// After NFKC + toLowerCase(), the only full-case-folding entries left that
// this product's lyrics can plausibly contain are German eszett and Greek
// final sigma — every other Unicode CaseFolding.txt entry that diverges
// from toLowerCase() either belongs to a script this product doesn't
// serve (Cherokee, Georgian Mtavruli/Nuskhuri, Old Hungarian, Kayah Li,
// Vithkuqi, Garay, …) or is already resolved by NFKC before this table
// runs (e.g. the ligatures ﬁ/ﬂ/ß-adjacent Fraktur long s ſ, and the
// micro sign µ all NFKC-decompose to their casefold-equivalent form
// already). U+0130 İ (LATIN CAPITAL LETTER I WITH DOT ABOVE), the other
// classically-cited casefold trap, needs no entry: toLowerCase('İ') and
// 'İ'.casefold() already agree (both produce U+0069 U+0307).
const FULL_CASEFOLD_OVERRIDES: ReadonlyMap<string, string> = new Map([
	['ß', 'ss'], // U+00DF LATIN SMALL LETTER SHARP S; toLowerCase('ẞ') also yields 'ß'
	['ς', 'σ'] // U+03C2 GREEK SMALL LETTER FINAL SIGMA
]);
const FULL_CASEFOLD_PATTERN = new RegExp(`[${[...FULL_CASEFOLD_OVERRIDES.keys()].join('')}]`, 'g');

function casefold(text: string): string {
	return text
		.toLowerCase()
		.replace(FULL_CASEFOLD_PATTERN, (char) => FULL_CASEFOLD_OVERRIDES.get(char) as string);
}

function isWordInternalApostrophe(text: string, index: number): boolean {
	const prev = text[index - 1];
	const next = text[index + 1];
	return Boolean(prev && next && WORD_CHAR.test(prev) && WORD_CHAR.test(next));
}

function stripPunctuation(text: string): string {
	let result = '';
	for (let i = 0; i < text.length; i++) {
		const char = text[i];
		if (char === "'" && isWordInternalApostrophe(text, i)) {
			result += char;
			continue;
		}
		if (/\p{P}/u.test(char)) continue;
		result += char;
	}
	return result;
}

export function normalizeLyricsToken(text: string): string {
	const straightened = text.replace(CURLY_APOSTROPHES, "'");
	const casefolded = casefold(straightened.normalize('NFKC'));
	const stripped = stripPunctuation(casefolded);
	return stripped.replace(/\s+/g, ' ').trim();
}
