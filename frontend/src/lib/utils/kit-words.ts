import { loadKitWords, type KitLanguage, type KitWords } from 'overnightworks-design';
import { languages, type Language } from '#lib/words/index.ts';

// The type check fails when the app offers a language the kit lacks.
const _kitCoversPageLanguages = languages satisfies readonly KitLanguage[];

class KitWordsNotLoadedError extends Error {
	override name = 'KitWordsNotLoadedError';
	constructor() {
		super('The kit words are read before they are loaded; the root layout load loads them.');
	}
}

let loadedKitWords: KitWords | undefined;

/** Loads the kit's words in the page's language once at start, from the root layout's `load`. */
export async function loadPageKitWords(language: Language): Promise<void> {
	loadedKitWords = await loadKitWords(language);
}

/** The kit's words the page passes to every kit component as `words`. */
export function kitWords(): KitWords {
	if (loadedKitWords === undefined) throw new KitWordsNotLoadedError();
	return loadedKitWords;
}
