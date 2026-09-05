// Album cover suggestions are deliberately started by a person. The isolated
// E2E stack has no Codex CLI, so the real POST must fail visibly with the
// server's named detail instead of leaving the album on a pretend loading
// state. A seeded suggestion is optional: this stack cannot manufacture one
// without the unavailable image route, but a local stack that already has one
// proves selection and removal through the public API below.

import { expect, test } from '@playwright/test';
import { readSeededLibrary } from './seed';
import { workspace } from './helpers';

test('Suggest cover names the isolated stack failure at desktop and 375 px', async ({
	page,
	isMobile
}) => {
	const library = readSeededLibrary();
	const surface = workspace(page);
	if (isMobile) await page.setViewportSize({ width: 375, height: 844 });

	await page.goto(`/album/${library.albumId}`);
	await expect(surface.getByRole('heading', { name: library.albumTitle })).toBeVisible();

	const failedSuggestion = page.waitForResponse(
		(response) =>
			response.request().method() === 'POST' &&
			new URL(response.url()).pathname === `/api/albums/${library.albumId}/cover-suggestions`
	);
	await surface.getByRole('button', { name: 'Suggest cover' }).click();
	const response = await failedSuggestion;
	const body = (await response.json()) as { detail?: string };
	expect(response.status()).toBe(503);
	expect(body.detail).toBe('Codex cover generation is unavailable');

	const failure = surface.getByRole('alert');
	await expect(failure).toContainText('Couldn’t make cover suggestions');
	await expect(failure).toContainText('Codex cover generation is unavailable');
});

test('an API-seeded suggestion can be chosen and its selected cover removed', async ({ page }) => {
	const library = readSeededLibrary();
	const suggestionsResponse = await page.request.get(
		`/api/albums/${library.albumId}/cover-suggestions`
	);
	if (!suggestionsResponse.ok()) {
		test.skip(true, 'The isolated stack cannot list cover suggestions.'); // NOSONAR S1607: this stack intentionally lacks the route.
	}
	const suggestions = (await suggestionsResponse.json()) as {
		suggestions: Array<{ id: string; url: string }>;
	};
	if (suggestions.suggestions.length === 0) {
		test.skip(true, 'The isolated stack has no API-seeded cover suggestion to select.'); // NOSONAR S1607: the optional seed is unavailable here.
	}

	const surface = workspace(page);
	await page.goto(`/album/${library.albumId}`);
	const candidate = surface.getByRole('button', { name: 'Use this' }).first();
	await expect(candidate).toBeVisible();
	await candidate.click();
	await expect(surface.locator('.header-cover img')).toBeVisible();

	await surface.getByRole('button', { name: 'More' }).click();
	await surface.getByRole('button', { name: 'Remove cover' }).click();
	await expect(surface.locator('.header-cover img')).toHaveCount(0);
});
