import { expect, type Locator, type Page } from '@playwright/test';
import { words } from '../src/lib/words/en';

export function searchSheet(page: Page): Locator {
	return page.getByRole('dialog', { name: words['phoneAppBar.searchSheet'], exact: true });
}

export async function openSearchSheet(page: Page): Promise<Locator> {
	await page
		.getByRole('banner')
		.getByRole('button', { name: words['phoneAppBar.searchOpen'], exact: true })
		.click();
	await expect(searchSheet(page)).toBeVisible();
	return searchSheet(page);
}

const GROUP_WORDS = {
	Albums: words['railSearch.groupAlbums'],
	Songs: words['railSearch.groupSongs']
};

export async function phoneSearchResult(
	page: Page,
	group: 'Albums' | 'Songs',
	query: string,
	name: string | RegExp
): Promise<Locator> {
	const sheet = await openSearchSheet(page);
	const search = sheet.getByRole('combobox', { name: words['railSearch.field'] });
	// A repeated crossing must issue a fresh query rather than reuse old hits.
	await search.fill('');
	await search.fill(query);
	const result = sheet
		.getByRole('group', { name: GROUP_WORDS[group], exact: true })
		.getByRole('option', { name });
	await expect(result).toBeVisible();
	return result;
}
