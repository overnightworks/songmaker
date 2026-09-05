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

test('Continue shows up to six tagged entries and moves a played song to the front after returning to Library', async ({
	page
}, testInfo) => {
	const shell = shellOf(testInfo);
	if (testInfo.project.name === 'mobile') await page.setViewportSize({ width: 375, height: 844 });
	const library = readSeededLibrary();
	const listenedSong = library.continueReorderSongs[shell];
	const anchorSong = library.continueAnchorSong;
	let continueRequests = 0;
	let continueCoverRequests = 0;
	page.on('request', (request) => {
		const url = new URL(request.url());
		if (request.method() === 'GET' && url.pathname === '/api/library/continue')
			continueRequests += 1;
		if (
			request.resourceType() === 'image' &&
			/^\/api\/(?:albums|songs)\/[^/]+\/cover$/.test(url.pathname)
		)
			continueCoverRequests += 1;
	});

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
	const anchorStatus = await page.evaluate(async (songId) => {
		const csrfToken = document.cookie
			.split('; ')
			.find((cookie) => cookie.startsWith('csrf_token='))
			?.split('=')[1];
		const response = await fetch(`/api/songs/${songId}/listen`, {
			method: 'POST',
			headers: { 'X-CSRF-Token': csrfToken ? decodeURIComponent(csrfToken) : '' }
		});
		return response.status;
	}, anchorSong.id);
	expect(anchorStatus).toBe(200);

	const continueRequestsBeforeAnchorReturn = continueRequests;
	const guard = new FlowGuard(page);
	const continueAfterAnchorReturn = page.waitForResponse(
		(response) =>
			response.request().method() === 'GET' &&
			new URL(response.url()).pathname === '/api/library/continue'
	);
	await page.goto('/');
	expect((await continueAfterAnchorReturn).status()).toBe(200);
	// Each return mounts Continue once. This seed has no covers, so neither
	// return adds images; the complete desktop/mobile flows stay within 45/40.
	expect(continueRequests).toBe(continueRequestsBeforeAnchorReturn + 1);
	expect(continueCoverRequests).toBe(0);

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

	const continueRequestsBeforeReturn = continueRequests;
	const continueCoverRequestsBeforeReturn = continueCoverRequests;
	const continueAfterReturn = page.waitForResponse(
		(response) =>
			response.request().method() === 'GET' &&
			new URL(response.url()).pathname === '/api/library/continue'
	);
	await page.goto('/');
	expect((await continueAfterReturn).status()).toBe(200);
	// The target return has the same one-GET, no-cover contract as the anchor
	// return above. The complete flows stay within their measured 45/40 budgets.
	expect(continueRequests).toBe(continueRequestsBeforeReturn + 1);
	expect(continueCoverRequests).toBe(continueCoverRequestsBeforeReturn);
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
