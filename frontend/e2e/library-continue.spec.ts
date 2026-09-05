import { expect, test } from '@playwright/test';
import { collectionRowPlayLabel, TRANSPORT_PAUSE_LABEL } from '../src/lib/constants';
import { FlowGuard, shellOf, type Shell } from './helpers';
import { readSeededLibrary } from './seed';

/**
 * A green run against a clean stack measures this full cold-start flow at
 * 32 requests on desktop and 28 on mobile. The two shells share one IP
 * rate-limit window, so new round trips are a regression to find rather than
 * a budget to raise.
 */
const CONTINUE_FLOW_API_REQUEST_BUDGET: Record<Shell, number> = {
	desktop: 35,
	mobile: 35
};

test('Continue shows up to six tagged entries and moves a played song to the front after reload', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const shell = shellOf(testInfo);
	if (testInfo.project.name === 'mobile') await page.setViewportSize({ width: 375, height: 844 });
	const library = readSeededLibrary();
	const listenedSong =
		shell === 'mobile' ? library.continueReorderSongTitle : library.pickedSongTitle;

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
			response.request().method() === 'POST' && /\/api\/songs\/[^/]+\/listen$/.test(response.url())
	);
	await page
		.getByRole('button', { name: collectionRowPlayLabel(listenedSong), exact: true })
		.click();
	await expect(
		page.getByRole('contentinfo').getByRole('button', { name: TRANSPORT_PAUSE_LABEL, exact: true })
	).toBeVisible();
	await listenReport;

	await page.goto('/');
	await page.reload();
	const playedSong = continueRow.getByRole('button', {
		name: `Open song ${listenedSong}`,
		exact: true
	});
	await expect(playedSong).toBeVisible();
	const after = await entries.evaluateAll((buttons) =>
		buttons.map((button) => button.getAttribute('aria-label'))
	);
	expect(after).not.toEqual(before);

	await playedSong.click();
	await expect(page.getByRole('heading', { name: listenedSong })).toBeVisible();

	console.log(`Continue flow /api requests (${shell}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(CONTINUE_FLOW_API_REQUEST_BUDGET[shell]);
});
