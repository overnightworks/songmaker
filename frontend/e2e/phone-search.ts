import { expect, type Locator, type Page } from '@playwright/test';
import { RAIL_SEARCH_LABEL, SEARCH_OPEN_LABEL } from '../src/lib/constants';
import { appBar } from './helpers';

export function searchSheet(page: Page): Locator {
	return page.getByRole('dialog', { name: 'Search', exact: true });
}

export async function openSearchSheet(page: Page): Promise<Locator> {
	await appBar(page).getByRole('button', { name: SEARCH_OPEN_LABEL, exact: true }).click();
	await expect(searchSheet(page)).toBeVisible();
	return searchSheet(page);
}

export async function phoneSearchResult(
	page: Page,
	group: 'Albums' | 'Songs',
	query: string,
	name: string | RegExp
): Promise<Locator> {
	const sheet = await openSearchSheet(page);
	const search = sheet.getByRole('combobox', { name: RAIL_SEARCH_LABEL });
	// A repeated crossing must issue a fresh query rather than reuse old hits.
	await search.fill('');
	await search.fill(query);
	const result = sheet
		.getByRole('group', { name: group, exact: true })
		.getByRole('option', { name });
	await expect(result).toBeVisible();
	return result;
}
