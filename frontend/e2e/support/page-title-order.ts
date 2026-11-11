import { expect, type Page } from '../coverage-test';
import { titleComparatorFor } from '../../src/lib/utils/recency';

/** The A–Z comparator in the language the loaded page carries: Playwright's Node process has no document to ask. */
export async function pageTitleOrder(page: Page): Promise<(a: string, b: string) => number> {
	const language = await page.locator('html').getAttribute('lang');
	expect(language, 'the page names its language in <html lang>').toBeTruthy();
	return titleComparatorFor(language ?? '');
}

/** The items in A–Z order of their titles, in the language the loaded page carries. */
export async function titledInPageOrder<Titled extends { title: string }>(
	page: Page,
	items: readonly Titled[]
): Promise<Titled[]> {
	const compareTitles = await pageTitleOrder(page);
	return items.toSorted((a, b) => compareTitles(a.title, b.title));
}
