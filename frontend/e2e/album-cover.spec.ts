// Album cover suggestions are deliberately started by a person: tapping the
// dashed Add cover place grows the header cover into its editor, which makes
// nothing until Suggest is tapped (#1186). Since #822 the
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
import {
	ALBUM_COVER_EDITING_LABEL,
	ALBUM_COVER_SUGGESTIONS_RETRY_LABEL,
	HITBOX_FREQUENT_PX,
	UNREACHABLE_RELOAD_DELAYS_MS
} from '../src/lib/constants';

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

test('Add cover asks for nothing until Suggest, whose one suggestion ends in a named failure shown once, at desktop and 390 px', async ({
	page,
	isMobile
}) => {
	const library = readSeededLibrary();
	const surface = workspace(page);
	if (isMobile) await page.setViewportSize({ width: 390, height: 844 });
	const suggestionsPath = `/api/albums/${library.albumId}/cover-suggestions`;
	const isSuggestionAsk = (method: string, url: string): boolean =>
		method === 'POST' && new URL(url).pathname === suggestionsPath;
	let suggestionAsks = 0;
	page.on('request', (request) => {
		if (isSuggestionAsk(request.method(), request.url())) suggestionAsks += 1;
	});

	await page.goto(`/album/${library.albumId}`);
	await expect(surface.getByRole('heading', { name: library.albumTitle })).toBeVisible();
	await expect(surface.getByText('Choose a cover')).toHaveCount(0);

	const editing = surface.getByRole('group', { name: 'Cover editing' });
	await surface.getByRole('button', { name: 'Add cover' }).click();
	await expect(editing.getByRole('button', { name: 'Suggest', exact: true })).toBeEnabled();
	await expect(editing.getByText(/left today$/)).toBeVisible();
	const leftBeforeMistap = await editing.getByText(/left today$/).textContent();
	await editing.getByRole('button', { name: 'Close cover editing' }).click();
	await expect(editing).toHaveCount(0);
	await surface.getByRole('button', { name: 'Add cover' }).click();
	await expect(editing.getByText(/left today$/)).toHaveText(leftBeforeMistap ?? '');
	expect(suggestionAsks).toBe(0);

	const createdJob = page.waitForResponse((response) =>
		isSuggestionAsk(response.request().method(), response.url())
	);
	await editing.getByRole('button', { name: 'Suggest', exact: true }).click();
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

	const failure = editing.getByRole('alert');
	await expect(failure).toContainText('Couldn’t make a cover suggestion');
	await expect(failure).toContainText(COVER_JOB_FAILURE);
	await expect(page.getByText(COVER_JOB_FAILURE)).toHaveCount(1);
	await expect(editing.getByRole('progressbar')).toHaveCount(0);
	expect(suggestionAsks).toBe(1);
	await expect(surface.getByRole('heading', { name: library.albumTitle })).toBeVisible();

	const albumAddress = page.url();
	if (isMobile) await editing.getByRole('button', { name: 'Close cover editing' }).click();
	else await page.keyboard.press('Escape');
	await expect(editing).toHaveCount(0);
	await expect(page).toHaveURL(albumAddress);
	await expect(surface.getByRole('button', { name: 'Add cover' })).toBeVisible();
});

test.describe('cover suggestions retry', () => {
	test('keeps a quiet touch target and reloads suggestions after bounded failures (1160-F8-hitbox)', async ({
		page,
		isMobile
	}, testInfo) => {
		const retryBudget =
			UNREACHABLE_RELOAD_DELAYS_MS.reduce((sum, delay) => sum + delay, 0) + 10_000;
		test.setTimeout(retryBudget + 15_000);
		await page.setViewportSize(
			isMobile ? { width: 390, height: 844 } : { width: 1440, height: 900 }
		);
		const library = readSeededLibrary();
		const suggestionsPath = `/api/albums/${library.albumId}/cover-suggestions`;
		const suggestionsRoute = `**${suggestionsPath}`;
		await page.route(suggestionsRoute, (route) =>
			route.request().method() === 'GET' ? route.abort('failed') : route.continue()
		);
		await page.goto(`/album/${library.albumId}`);
		await workspace(page)
			.getByRole('button', { name: /^(Add|Edit) cover$/ })
			.click();
		const editing = workspace(page).getByRole('group', { name: ALBUM_COVER_EDITING_LABEL });
		const retry = editing.getByRole('button', { name: ALBUM_COVER_SUGGESTIONS_RETRY_LABEL });
		await expect(retry).toBeVisible({ timeout: retryBudget });
		const box = await retry.boundingBox();
		if (!box) throw new Error('retry button has no bounding box');
		expect(box.width).toBeGreaterThanOrEqual(HITBOX_FREQUENT_PX);
		expect(box.height).toBeGreaterThanOrEqual(HITBOX_FREQUENT_PX);
		await testInfo.attach('cover-retry', {
			body: await page.screenshot(),
			contentType: 'image/png'
		});

		await page.unroute(suggestionsRoute);
		const loaded = page.waitForResponse(
			(response) =>
				new URL(response.url()).pathname === suggestionsPath &&
				response.request().method() === 'GET'
		);
		await retry.click();
		expect((await loaded).ok()).toBeTruthy();
		await expect(editing.getByText(/left today$/)).toBeVisible();
		await expect(retry).toHaveCount(0);
		await testInfo.attach('cover-retry-loaded', {
			body: await page.screenshot(),
			contentType: 'image/png'
		});
	});
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
		// Only a stack that serves cover suggestions can drive this flow.
		test.skip(true, 'The isolated stack cannot list cover suggestions.');
	}
	const suggestions = (await suggestionsResponse.json()) as {
		suggestions: Array<{ id: string; url: string }>;
	};
	if (suggestions.suggestions.length === 0) {
		// Only a stack seeded with a cover suggestion can drive this flow.
		test.skip(true, 'The isolated stack has no API-seeded cover suggestion to select.');
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
