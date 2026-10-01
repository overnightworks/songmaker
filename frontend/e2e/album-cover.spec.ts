// Album cover suggestions are deliberately started by a person: tapping the
// dashed Add cover place grows the header cover into its editor and asks for
// the first suggestion (#1154). Since #822 the
// one dispatch owner is asked inside the cover job, not in a request
// preflight: the isolated E2E stack mounts no Codex CLI, so the POST succeeds
// and creates a job, and it is that job which ends failed with the named
// reason the album never gets its covers. A seeded suggestion is optional:
// this stack cannot manufacture one without the unavailable image route, but a
// local stack that already has one proves selection, and removal from the
// cover editor that the album ⋯ Cover row opens, below.

import { expect, test, type Page } from '@playwright/test';
import { readSeededLibrary } from './seed';
import { workspace } from './helpers';

// What a stack without the mounted Codex CLI puts on the failed job:
// cover_image_capability() names CLI_BINARY_UNAVAILABLE, which the runner
// reports as the generic image failure. Which provider route was unusable, and
// why, is answered by GET /api/settings/providers, not by this job.
const COVER_JOB_FAILURE = 'Cover suggestion could not be generated';

interface CoverJobOutcome {
	id: string;
	status: string;
	error: string | null;
}

test('Add cover makes one suggestion in place that ends in a named job failure at desktop and 375 px', async ({
	page,
	isMobile
}) => {
	const library = readSeededLibrary();
	const surface = workspace(page);
	if (isMobile) await page.setViewportSize({ width: 375, height: 844 });

	await page.goto(`/album/${library.albumId}`);
	await expect(surface.getByRole('heading', { name: library.albumTitle })).toBeVisible();
	await expect(surface.getByText('Choose a cover')).toHaveCount(0);

	const createdJob = page.waitForResponse(
		(response) =>
			response.request().method() === 'POST' &&
			new URL(response.url()).pathname === `/api/albums/${library.albumId}/cover-suggestions`
	);
	await surface.getByRole('button', { name: 'Add cover' }).click();
	const response = await createdJob;
	expect(response.status()).toBe(200);
	const job = (await response.json()) as { id: string };

	const namedFailure: CoverJobOutcome = {
		id: job.id,
		status: 'failed',
		error: COVER_JOB_FAILURE
	};
	await expect
		.poll(() => coverJobOutcome(page, library.albumId), { timeout: 60_000 })
		.toEqual(namedFailure);

	const editing = surface.getByRole('group', { name: 'Cover editing' });
	const failure = editing.getByRole('alert');
	await expect(failure).toContainText('Couldn’t make a cover suggestion');
	await expect(failure).toContainText(COVER_JOB_FAILURE);
	await expect(editing.getByRole('progressbar')).toHaveCount(0);
	await expect(surface.getByRole('heading', { name: library.albumTitle })).toBeVisible();

	const albumAddress = page.url();
	if (isMobile) await editing.getByRole('button', { name: 'Close cover editing' }).click();
	else await page.keyboard.press('Escape');
	await expect(editing).toHaveCount(0);
	await expect(page).toHaveURL(albumAddress);
	await expect(surface.getByRole('button', { name: 'Add cover' })).toBeVisible();
});

async function coverJobOutcome(page: Page, albumId: string): Promise<CoverJobOutcome | null> {
	const response = await page.request.get(`/api/albums/${albumId}/cover-suggestions`);
	expect(response.ok()).toBe(true);
	const { job } = (await response.json()) as { job: CoverJobOutcome | null };
	return job && { id: job.id, status: job.status, error: job.error };
}

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
	await surface.getByRole('button', { name: /^(Add|Edit) cover$/ }).click();
	const editing = surface.getByRole('group', { name: 'Cover editing' });
	const use = editing.getByRole('button', { name: 'Use', exact: true });
	await expect(use).toBeEnabled();
	await use.click();
	await expect(editing).toHaveCount(0);
	await expect(surface.locator('.header-cover img')).toBeVisible();

	await surface.getByRole('button', { name: 'More' }).click();
	await surface.getByRole('button', { name: 'Cover', exact: true }).click();
	await editing.getByRole('button', { name: 'Remove', exact: true }).click();
	await expect(surface.locator('.header-cover img')).toHaveCount(0);
});
