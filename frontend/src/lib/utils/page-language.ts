import { languages, type Language } from '#lib/words/index.ts';

/** The page's language is required configuration: the server writes one of the app's languages into `<html lang>`, and nothing stands in for a missing or foreign one. */
class PageLanguageError extends Error {
	constructor(tag: string) {
		super(`The page language must be one of ${languages.join(', ')} in <html lang>, got "${tag}".`);
		this.name = 'PageLanguageError';
	}
}

/** The language the server wrote into `<html lang>`. */
export function pageLanguage(): Language {
	const tag = document.documentElement.lang;
	const language = languages.find((offered) => offered === tag);
	if (language === undefined) throw new PageLanguageError(tag);
	return language;
}
