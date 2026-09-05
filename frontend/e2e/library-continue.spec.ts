import { expect, test } from '@playwright/test';
import { collectionRowPlayLabel, TRANSPORT_PAUSE_LABEL } from '../src/lib/constants';
import { FlowGuard, shellOf, type Shell } from './helpers';
import { readSeededLibrary } from './seed';

/**
 * A full green suite run measures 42 requests on desktop and 36 on mobile.
 * Earlier flows create enough albums to cross the library's pagination
 * boundary; this flow itself adds no requests for that data. The two shells
 * share one IP rate-limit window, so new round trips are a regression to find
 * rather than a budget to raise.
 */
const CONTINUE_FLOW_API_REQUEST_BUDGET: Record<Shell, number> = {
	desktop: 45,
	mobile: 40
};

test('Continue shows up to six tagged entries and moves a played song to the front after reload', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const shell = shellOf(testInfo);
	if (testInfo.project.name === 'mobile') await page.setViewportSize({ width: 375, height: 844 });
	const library = readSeededLibrary();
	const listenedSong = {
		id: library.continueReorderSongId,
		title: library.continueReorderSongTitle
	};

	// AudioPlayer owns a detached Audio object, which headless Chromium does
	// not advance far enough to emit `playing`. Preserve the real playback
	// path by making its actual play() call produce the browser event 5C owns.
	await page.addInitScript(() => {
		const nativePlay = HTMLMediaElement.prototype.play;
		HTMLMediaElement.prototype.play = function () {
			const result = nativePlay.call(this);
			queueMicrotask(() => this.dispatchEvent(new Event('playing')));
			return result;
		};
	});

	await page.goto('/');
	const continueRow = page.getByRole('region', { name: 'Continue' });
	const entries = continueRow.locator('.continue-item');
	await expect(entries.first()).toBeVisible();
	const before = await entries.evaluateAll((buttons) =>
		buttons.map((button) => button.getAttribute('aria-label'))
	);
	expect(before.length).toBeGreaterThan(0);
	expect(before.length).toBeLessThanOrEqual(6);
	expect(await continueRow.locator('.continue-tag').allTextContents()).toEqual(
		expect.arrayContaining(['Album'])
	);

	await page.locator('.wall-tile-body').filter({ hasText: library.albumTitle }).click();
	const listenReport = page.waitForResponse(
		(response) =>
			response.request().method() === 'POST' &&
			new URL(response.url()).pathname === `/api/songs/${listenedSong.id}/listen`
	);
	await page
		.getByRole('button', { name: collectionRowPlayLabel(listenedSong.title), exact: true })
		.click();
	await expect(
		page.getByRole('contentinfo').getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true })
	).toBeVisible();
	expect((await listenReport).status()).toBe(200);

	const continueAfterListen = page.waitForResponse(
		(response) =>
			response.request().method() === 'GET' &&
			new URL(response.url()).pathname === '/api/library/continue'
	);
	await page.goto('/');
	expect((await continueAfterListen).status()).toBe(200);
	await page.reload();
	const playedSong = continueRow.getByRole('button', {
		name: `Open song ${listenedSong.title}`,
		exact: true
	});
	await expect(playedSong).toBeVisible();
	const after = await entries.evaluateAll((buttons) =>
		buttons.map((button) => button.getAttribute('aria-label'))
	);
	expect(after).not.toEqual(before);

	await playedSong.click();
	await expect(page.getByRole('heading', { name: listenedSong.title })).toBeVisible();

	console.log(`Continue flow /api requests (${shell}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(CONTINUE_FLOW_API_REQUEST_BUDGET[shell]);
});
