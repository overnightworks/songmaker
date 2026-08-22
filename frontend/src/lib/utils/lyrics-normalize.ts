// Normalizes a single lyrics/transcript token (or line) so that punctuation
// and casing differences never register as sung deviations — only an
// actually different word does. Contract from issue #45: unify curly
// apostrophe variants to a straight one, NFKC-normalize, casefold, strip
// punctuation (keeping an apostrophe that sits between two word
// characters, e.g. "don't"), then collapse whitespace.
const CURLY_APOSTROPHES = /[‘’‛ʼ]/g;
const WORD_CHAR = /[\p{L}\p{N}_]/u;

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
	const casefolded = straightened.normalize('NFKC').toLowerCase();
	const stripped = stripPunctuation(casefolded);
	return stripped.replace(/\s+/g, ' ').trim();
}
