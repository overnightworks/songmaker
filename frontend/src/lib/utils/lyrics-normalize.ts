// Normalizes a single lyrics/transcript token (or line) so that punctuation
// and casing differences never register as sung deviations — only an
// actually different word does. Contract from issue #45, extended on
// #1030: unify curly apostrophe variants to a straight one, NFKC-normalize,
// strip punctuation (keeping an apostrophe that sits between two word
// characters, e.g. "don't"), collapse whitespace, spell out numbers as German
// words, casefold, then spell out umlauts as ae/oe/ue. Casefold must match
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

function casefold(text: string): string {
	return Array.from(text.toLowerCase())
		.map((char) => FULL_CASEFOLD_OVERRIDES.get(char) ?? char)
		.join('');
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

// Typed German lyrics often spell out umlauts ("glueht") where Whisper writes
// them ("glüht"); folding both to the spelled-out form makes them one key.
// Eszett already folds to "ss" with the casefold above.
const UMLAUT_SPELLINGS: ReadonlyMap<string, string> = new Map([
	['ä', 'ae'],
	['ö', 'oe'],
	['ü', 'ue']
]);

function spellOutUmlauts(text: string): string {
	return text.replace(/[äöü]/g, (umlaut) => UMLAUT_SPELLINGS.get(umlaut) ?? umlaut);
}

// Whisper writes a sung number as digits ("17") where the lyrics spell it
// ("siebzehn"). Digits are spelled out as German number words, the language
// the lyrics that carry numbers are written in; for any other language the
// digits simply stay as unmatched as they were.
const UNITS = [
	'null',
	'eins',
	'zwei',
	'drei',
	'vier',
	'fünf',
	'sechs',
	'sieben',
	'acht',
	'neun',
	'zehn',
	'elf',
	'zwölf',
	'dreizehn',
	'vierzehn',
	'fünfzehn',
	'sechzehn',
	'siebzehn',
	'achtzehn',
	'neunzehn'
];
const TENS = [
	'',
	'',
	'zwanzig',
	'dreißig',
	'vierzig',
	'fünfzig',
	'sechzig',
	'siebzig',
	'achtzig',
	'neunzig'
];
const LARGEST_SPELLED_NUMBER = 9999;

function numberPrefix(count: number): string {
	return count === 1 ? 'ein' : UNITS[count];
}

function spellGermanNumber(value: number): string {
	if (value < UNITS.length) return UNITS[value];
	if (value < 100) {
		const unit = value % 10;
		const tens = TENS[Math.floor(value / 10)];
		return unit === 0 ? tens : `${numberPrefix(unit)}und${tens}`;
	}
	const [scale, word] = value < 1000 ? [100, 'hundert'] : [1000, 'tausend'];
	const rest = value % scale;
	return `${numberPrefix(Math.floor(value / scale))}${word}${rest === 0 ? '' : spellGermanNumber(rest)}`;
}

function spellOutNumbers(text: string): string {
	return text
		.split(' ')
		.map((token) => {
			if (!/^\d+$/.test(token)) return token;
			const value = Number(token);
			return value <= LARGEST_SPELLED_NUMBER ? spellGermanNumber(value) : token;
		})
		.join(' ');
}

export function normalizeLyricsToken(text: string): string {
	const straightened = text.replace(CURLY_APOSTROPHES, "'").normalize('NFKC');
	const words = stripPunctuation(straightened).replace(/\s+/g, ' ').trim();
	return spellOutUmlauts(casefold(spellOutNumbers(words)));
}
