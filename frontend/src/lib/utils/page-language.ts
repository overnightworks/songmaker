/** The page's language is required configuration: `<html lang>` names it, and nothing stands in for a missing one. */
class PageLanguageError extends Error {
	constructor(tag: string) {
		super(`The page language must be a valid language tag in <html lang>, got "${tag}".`);
		this.name = 'PageLanguageError';
	}
}

/** The canonical tag of the language `<html lang>` names. */
export function pageLanguage(): string {
	const tag = document.documentElement.lang;
	try {
		const [canonical] = Intl.getCanonicalLocales(tag);
		if (canonical === undefined) throw new PageLanguageError(tag);
		return canonical;
	} catch (error) {
		if (error instanceof PageLanguageError) throw error;
		throw new PageLanguageError(tag);
	}
}
