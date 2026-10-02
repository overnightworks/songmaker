import { expect, test } from '@playwright/test';
import { TRANSPORT_PAUSE_LABEL, TRANSPORT_PLAY_LABEL } from '../src/lib/constants';
import {
	csrfHeaders,
	FlowGuard,
	nameStartingWith,
	openLibraryWall,
	shellOf,
	workspace,
	type Shell
} from './helpers';
import { readSeededLibrary } from './seed';

/**
 * A full green suite run measured 39 requests on desktop and 44 on mobile
 * before the return to the foreground on Home fetched Continue once more.
 * Continue is never cached beyond one showing of Home (#1077).
 * Since the album row opens the song (#1010), the flow pays for the song
 * page's own loads (the song, its versions, its active and last failed take,
 * models, LoRAs) before it plays the take. Earlier flows create enough albums
 * to cross the library's pagination boundary; this flow itself adds no
 * requests for that data. Since the wall sorts every album (#1102 W4), the
 * phone reads the complete album set on each page load, as the desktop rail
 * always did: one request per 50 albums, measured 47 on mobile. The playback
 * recorder (#1187) reports what it saw as the page reloads: measured 42 on
 * desktop and 48 on mobile. The two shells share one IP rate-limit window, so
 * new round trips are a regression to find rather than a budget to raise.
 */
const CONTINUE_FLOW_API_REQUEST_BUDGET: Record<Shell, number> = {
	desktop: 43,
	mobile: 48
};

test('Continue shows up to six places, follows a listen made elsewhere on a return to the foreground, and moves the place of a played song to the front after reload', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const shell = shellOf(testInfo);
	if (testInfo.project.name === 'mobile') await page.setViewportSize({ width: 375, height: 844 });
	const library = readSeededLibrary();
	const listenedSong = library.continueReorderSongs[shell];
	const otherShellSong = library.continueReorderSongs[shell === 'desktop' ? 'mobile' : 'desktop'];
	const seededAlbumOn = (songTitle: string) =>
		`Open song ${songTitle} in album ${library.albumTitle}`;
	let continueRequests = 0;
	let continueCoverRequests = 0;
	page.on('request', (request) => {
		const url = new URL(request.url());
		if (request.method() === 'GET' && url.pathname === '/api/library/continue')
			continueRequests += 1;
		if (
			request.resourceType() === 'image' &&
			/^\/api\/(?:albums|playlists)\/[^/]+\/cover$/.test(url.pathname)
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
	await expect(entries.first()).toBeVisible();
	expect(continueRequests).toBe(1);
	const before = await entries.evaluateAll((buttons) =>
		buttons.map((button) => button.getAttribute('aria-label'))
	);
	expect(before.length).toBeGreaterThan(0);
	expect(before.length).toBeLessThanOrEqual(6);
	expect(new Set(before).size).toBe(before.length);
	for (const label of before) expect(label).toMatch(/^Open (song .+ in )?(album|playlist) /);

	// Home stays open while the same musician listens somewhere else; the app
	// coming back to the foreground must show that, not the list it opened with.
	// The song is picked at run time so the seeded album's tile is sure to
	// change: it may already lead, naming a song an earlier flow played.
	const songListenedElsewhereTitle = [library.pickedSongTitle, otherShellSong.title].find(
		(title) => before[0] !== seededAlbumOn(title)
	);
	const songsResponse = await page.request.get(`/api/songs?album_id=${library.albumId}`);
	expect(songsResponse.status()).toBe(200);
	const albumSongs: Array<{ id: string; title: string }> = (await songsResponse.json()).items;
	const songListenedElsewhere = albumSongs.find(
		(song) => song.title === songListenedElsewhereTitle
	);
	if (!songListenedElsewhere) throw new Error(`Missing seeded song ${songListenedElsewhereTitle}`);
	const listenElsewhere = await page.request.post(`/api/songs/${songListenedElsewhere.id}/listen`, {
		headers: await csrfHeaders(page)
	});
	expect(listenElsewhere.status()).toBe(200);
	const continueAfterForeground = page.waitForResponse(
		(response) =>
			response.request().method() === 'GET' &&
			new URL(response.url()).pathname === '/api/library/continue'
	);
	await page.evaluate(() => {
		Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
		document.dispatchEvent(new Event('visibilitychange'));
		Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
		document.dispatchEvent(new Event('visibilitychange'));
	});
	expect((await continueAfterForeground).status()).toBe(200);
	await expect(entries.first()).toHaveAttribute(
		'aria-label',
		seededAlbumOn(songListenedElsewhere.title)
	);
	await expect(entries.first().locator('time')).toHaveText(/^today \d{2}:\d{2}$/);
	expect(continueRequests).toBe(2);
	const afterForeground = await entries.evaluateAll((buttons) =>
		buttons.map((button) => button.getAttribute('aria-label'))
	);
	expect(afterForeground.filter((label) => label?.endsWith(library.albumTitle))).toHaveLength(1);
	await page.evaluate(() => Reflect.deleteProperty(document, 'visibilityState'));

	const surface = workspace(page);
	await surface
		.locator('.library-wall .tile-grid')
		.locator('.wall-tile-body')
		.filter({ hasText: library.albumTitle })
		.click();
	// An album row opens the song (#1010); its take row's own play face plays it.
	await surface
		.locator('.item-row')
		.filter({ hasText: listenedSong.title })
		.getByRole('button')
		.click();
	if (shell === 'mobile') await surface.getByRole('tab', { name: /Takes/ }).click();
	const take = surface.locator('.take-row');
	await expect(take).toHaveCount(1);
	const listenReport = page.waitForResponse(
		(response) =>
			response.request().method() === 'POST' &&
			new URL(response.url()).pathname === `/api/songs/${listenedSong.id}/listen`
	);
	await take.getByRole('button', { name: nameStartingWith(TRANSPORT_PLAY_LABEL) }).click();
	await expect(
		take.getByRole('button', { name: nameStartingWith(TRANSPORT_PAUSE_LABEL) })
	).toBeVisible();
	expect((await listenReport).status()).toBe(200);

	await openLibraryWall(page, shell);
	await expect(entries.first()).toHaveAttribute('aria-label', seededAlbumOn(listenedSong.title));
	expect(continueRequests).toBe(3);
	const afterSpaReturn = await entries.evaluateAll((buttons) =>
		buttons.map((button) => button.getAttribute('aria-label'))
	);
	expect(afterSpaReturn).not.toEqual(afterForeground);
	const continueRequestsBeforeReload = continueRequests;
	const continueCoverRequestsBeforeReload = continueCoverRequests;
	const continueAfterReload = page.waitForResponse(
		(response) =>
			response.request().method() === 'GET' &&
			new URL(response.url()).pathname === '/api/library/continue'
	);
	await page.reload();
	expect((await continueAfterReload).status()).toBe(200);
	// Reloading the Continue owner fetches its data exactly once. This seed has
	// no covers, so the refreshed row must not add image requests.
	expect(continueRequests).toBe(continueRequestsBeforeReload + 1);
	expect(continueCoverRequests).toBe(continueCoverRequestsBeforeReload);
	const playedPlace = entries.first();
	await expect(playedPlace).toHaveAttribute('aria-label', seededAlbumOn(listenedSong.title));
	const afterReload = await entries.evaluateAll((buttons) =>
		buttons.map((button) => button.getAttribute('aria-label'))
	);
	expect(afterReload).toEqual(afterSpaReturn);

	await playedPlace.click();
	await expect(page.getByRole('heading', { name: listenedSong.title })).toBeVisible();

	console.log(`Continue flow /api requests (${shell}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(CONTINUE_FLOW_API_REQUEST_BUDGET[shell]);
});
