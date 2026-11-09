// Album cover suggestions are deliberately started by a person: tapping the
// dashed Add cover place grows the header cover into its editor, which makes
// nothing until Suggest is tapped (#1186). Suggest asks the gateway's API group
// at the click (#2055 C1): the isolated E2E stack configures a gateway but its
// seeded session holds no refresh grant, so the real click is refused with
// "log in again" and makes no job. The other three of the agent's problems
// cannot come from this stack, so a run is seeded running and ended with each
// (scripts/seed_e2e_job_states.py) on a fresh album that is archived after.
// A seeded suggestion is optional: a local stack that already has one proves
// selection, and removal from the cover editor that the album ⋯ Cover row
// opens, below.

import { expect, test, type Locator, type Page, type TestInfo } from '@playwright/test';
import { archiveOwnedAlbum, readSeededLibrary } from './seed';
import { failCoverJob, seedRunningCoverJob } from './seed-cover';
import { sameOriginHeaders, workspace } from './helpers';
import { UNREACHABLE_RELOAD_DELAYS_MS } from '../src/lib/constants/connectivity';
import { HITBOX_FREQUENT_PX } from '../src/lib/constants/hitbox';
import {
	ALBUM_COVER_EDITING_LABEL,
	ALBUM_COVER_SUGGESTIONS_RETRY_LABEL
} from '../src/lib/constants/album';
import { COVER_PROBLEM_TEXTS } from '../src/lib/utils/cover-problem';

const PHONE_VIEWPORT = { width: 375, height: 844 };
// What a cover job's row may hold and no page may show (#2055 matrix cell 26).
const STORED_ERROR_CANARY = 'gateway detail sk-e2e-canary for session e2e-canary';
const BUSY_WAIT_SECONDS = 300;

interface ProblemLook {
	borderColor: string;
	borderStyle: string;
}

function problemLine(editing: Locator): Locator {
	return editing.getByRole('alert');
}

function suggestButton(editing: Locator): Locator {
	return editing.getByRole('button', { name: /^Suggest/ });
}

async function lookOf(line: Locator): Promise<ProblemLook> {
	return line.evaluate((el) => {
		const style = getComputedStyle(el);
		return { borderColor: style.borderLeftColor, borderStyle: style.borderLeftStyle };
	});
}

test('Add cover asks for nothing until Suggest, whose refused click says log in again in red and makes no job, at desktop and 375 px', async ({
	page,
	isMobile
}) => {
	const library = readSeededLibrary();
	const surface = workspace(page);
	if (isMobile) await page.setViewportSize(PHONE_VIEWPORT);
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
	await editing.getByRole('button', { name: 'Close cover editing' }).click();
	await expect(editing).toHaveCount(0);
	await surface.getByRole('button', { name: 'Add cover' }).click();
	expect(suggestionAsks).toBe(0);
	const latestJobBefore = await latestCoverJobId(page, library.albumId);

	const refused = page.waitForResponse((response) =>
		isSuggestionAsk(response.request().method(), response.url())
	);
	await editing.getByRole('button', { name: 'Suggest', exact: true }).click();
	const response = await refused;
	expect(response.status()).toBe(403);
	expect(await response.json()).toEqual({ detail: { problem: 'sign_in_again' } });

	const line = problemLine(editing);
	await expect(line).toContainText(COVER_PROBLEM_TEXTS.sign_in_again);
	await expect(line.getByRole('link', { name: 'Log in' })).toBeVisible();
	await expect(suggestButton(editing)).toBeDisabled();
	await expect(editing.getByRole('button', { name: 'Upload', exact: true })).toBeEnabled();
	expect(await latestCoverJobId(page, library.albumId)).toBe(latestJobBefore);
	expect(suggestionAsks).toBe(1);

	const albumAddress = page.url();
	if (isMobile) await editing.getByRole('button', { name: 'Close cover editing' }).click();
	else await page.keyboard.press('Escape');
	await expect(editing).toHaveCount(0);
	await expect(page).toHaveURL(albumAddress);
	await expect(surface.getByRole('button', { name: 'Add cover' })).toBeVisible();
});

test('a run that ends busy, not enabled or unavailable shows its own line in its own look, and only busy and a followed refusal close Suggest', async ({
	page,
	isMobile
}, testInfo) => {
	if (isMobile) await page.setViewportSize(PHONE_VIEWPORT);
	const looks: Record<string, ProblemLook> = {};
	for (const problem of ['busy', 'not_enabled', 'unavailable'] as const) {
		const album = await createFreshAlbum(page, `${problem} ${isMobile ? 'phone' : 'desktop'}`);
		try {
			const jobId = await seedRunningCoverJob(album.id);
			await page.goto(`/album/${album.id}`);
			await workspace(page).getByRole('button', { name: 'Add cover' }).click();
			const editing = workspace(page).getByRole('group', { name: ALBUM_COVER_EDITING_LABEL });
			await expect(suggestButton(editing)).toBeDisabled();

			await failCoverJob(
				jobId,
				problem,
				STORED_ERROR_CANARY,
				problem === 'busy' ? BUSY_WAIT_SECONDS : undefined
			);

			const line = problemLine(editing);
			await expect(line).toContainText(COVER_PROBLEM_TEXTS[problem]);
			looks[problem] = await lookOf(line);
			await expect(suggestButton(editing)).toBeEnabled({ enabled: problem === 'unavailable' });
			if (problem === 'busy') await expect(suggestButton(editing)).toContainText(/[45]:\d\d/);
			await expect(page.getByText(STORED_ERROR_CANARY)).toHaveCount(0);
			await attachShot(page, testInfo, `cover-${problem}`);

			// A reload is a new view: busy keeps its wait, a refusal of the person asks again.
			await page.reload();
			await workspace(page).getByRole('button', { name: 'Add cover' }).click();
			if (problem === 'not_enabled') {
				await expect(suggestButton(editing)).toBeEnabled();
				await expect(problemLine(editing)).toHaveCount(0);
			} else {
				await expect(problemLine(editing)).toContainText(COVER_PROBLEM_TEXTS[problem]);
				await expect(suggestButton(editing)).toBeEnabled({ enabled: problem === 'unavailable' });
			}
			await expect(page.getByText(STORED_ERROR_CANARY)).toHaveCount(0);
		} finally {
			await archiveOwnedAlbum(page.request, album.id);
		}
	}

	// Busy and unavailable wait in amber; not enabled is grey and dashed (picture l).
	expect(looks.busy.borderColor).toBe(looks.unavailable.borderColor);
	expect(looks.busy.borderStyle).toBe('solid');
	expect(looks.not_enabled.borderStyle).toBe('dashed');
	expect(looks.not_enabled.borderColor).not.toBe(looks.busy.borderColor);
});

async function createFreshAlbum(page: Page, label: string): Promise<{ id: string }> {
	const response = await page.request.post('/api/albums', {
		headers: await sameOriginHeaders(page),
		data: { title: `E2E Cover Problem ${label} ${Date.now()}`, artist: '' }
	});
	expect(response.ok()).toBe(true);
	return (await response.json()) as { id: string };
}

async function latestCoverJobId(page: Page, albumId: string): Promise<string | null> {
	const response = await page.request.get(`/api/albums/${albumId}/cover-suggestions`);
	expect(response.ok()).toBe(true);
	const { job } = (await response.json()) as { job: { id: string } | null };
	return job?.id ?? null;
}

async function attachShot(page: Page, testInfo: TestInfo, name: string): Promise<void> {
	await testInfo.attach(name, { body: await page.screenshot(), contentType: 'image/png' });
}

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
		await expect(retry).toHaveCount(0);
		await testInfo.attach('cover-retry-loaded', {
			body: await page.screenshot(),
			contentType: 'image/png'
		});
	});
});

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
