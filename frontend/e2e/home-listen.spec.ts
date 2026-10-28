import type { SongItem, PaginatedResponse } from '../src/lib/api/types';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import {
	COLLECTION_MENU_LABEL,
	COLLECTION_MENU_DELETE_LABEL,
	COLLECTION_MENU_ARCHIVE_LABEL,
	HOME_LISTEN_EMPTY,
	HOME_LISTEN_ERROR
} from '../src/lib/constants';
import {
	sameOriginHeaders,
	FlowGuard,
	HOME_PATH,
	loseNetwork,
	regainNetwork,
	openHome,
	listenRegion,
	shellOf,
	workspace
} from './helpers';
import {
	BASE_URL,
	archiveOwnedAlbum,
	runMarker,
	seedAccount,
	seedUnpickedLibrary,
	readSeededLibrary,
	signedInApi
} from './seed';

async function postFromPage(
	page: Page,
	path: string,
	data: unknown = {}
): Promise<Record<string, string>> {
	const response = await page.request.post(path, { headers: await sameOriginHeaders(page), data });
	expect(response.ok(), `${path}: ${response.status()}`).toBe(true);
	return response.json();
}

test('1354_rule_14 1354_rule_15 1354_rule_18 1354_rule_19 1354_rule_20: Home Listen orders three distinct places, opens them, retains offline rows and follows removal and Undo', async ({
	page,
	context,
	browser
}, testInfo) => {
	const guard = new FlowGuard(page, { losesNetworkOnPurpose: true });
	const account = await seedAccount(`e2e-listen-${testInfo.project.name}-${runMarker()}`);
	let accountApi: APIRequestContext | undefined;
	let albumId: string | undefined;
	try {
		accountApi = await signedInApi(account);
		const library = await seedUnpickedLibrary(accountApi);
		albumId = library.albumId;
		await context.clearCookies();
		await context.addCookies(account.cookies);
		await page.goto(HOME_PATH);
		await expect(listenRegion(page).getByText(HOME_LISTEN_EMPTY)).toBeVisible();
		await page.screenshot({ path: testInfo.outputPath('listen-empty.png') });

		const songsResponse = await page.request.get(`/api/songs?album_id=${library.albumId}`);
		expect(songsResponse.ok()).toBe(true);
		const songs: PaginatedResponse<SongItem> = await songsResponse.json();
		const songResponse = await page.request.get(`/api/songs/${songs.items[0].id}`);
		expect(songResponse.ok()).toBe(true);
		const song: SongItem = await songResponse.json();
		await postFromPage(page, `/api/songs/${song.id}/listen`);
		const titles: string[] = [];
		for (let index = 0; index < 3; index++) {
			const title = `E2E Listen playlist ${index}`;
			const playlist = await postFromPage(page, '/api/playlists', { title });
			await postFromPage(page, `/api/playlists/${playlist.id}/entries/generation`, {
				generation_id: song.generations[0].id
			});
			await postFromPage(page, `/api/songs/${song.id}/listen`, { playlist_id: playlist.id });
			titles.unshift(`Open playlist ${title}`);
		}
		let reads = 0;
		page.on('request', (req) => {
			if (new URL(req.url()).pathname === '/api/library/listen') reads++;
		});
		await page.reload();
		const rows = listenRegion(page).locator('.library-row');
		await expect(rows).toHaveCount(3);
		await expect(listenRegion(page).locator('.wall-tile-body').first()).toHaveAttribute(
			'aria-label',
			titles[0]
		);
		expect(
			await listenRegion(page)
				.locator('.wall-tile-body')
				.evaluateAll((items) => items.map((item) => item.getAttribute('aria-label')))
		).toEqual(titles);
		expect(reads).toBe(1);
		const otherDevice = await browser.newContext({
			storageState: await context.storageState(),
			viewport: testInfo.project.use.viewport
		});
		try {
			const otherPage = await otherDevice.newPage();
			await otherPage.goto(BASE_URL + HOME_PATH);
			await expect(listenRegion(otherPage).locator('.wall-tile-body')).toHaveCount(3);
			expect(
				await listenRegion(otherPage)
					.locator('.wall-tile-body')
					.evaluateAll((items) => items.map((item) => item.getAttribute('aria-label')))
			).toEqual(titles);
		} finally {
			await otherDevice.close();
		}

		for (const row of await rows.all()) {
			const bounds = await row.boundingBox();
			expect(bounds?.height).toBe(58);
			expect((bounds?.x ?? -1) >= 0).toBe(true);
			expect((bounds?.x ?? 0) + (bounds?.width ?? 0)).toBeLessThanOrEqual(
				page.viewportSize()?.width ?? 0
			);
		}
		await page.screenshot({ path: testInfo.outputPath('listen-rows.png') });
		await loseNetwork(page, context);
		await expect(rows).toHaveCount(3);
		await regainNetwork(page, context);

		await listenRegion(page).getByRole('button', { name: titles[0], exact: true }).click();
		await expect(page).toHaveURL(/\/playlist\//);
		await workspace(page).getByRole('button', { name: COLLECTION_MENU_LABEL, exact: true }).click();
		await page
			.getByRole('button', { name: `${COLLECTION_MENU_DELETE_LABEL} playlist`, exact: true })
			.click();
		await page.getByRole('button', { name: 'Delete Playlist', exact: true }).click();
		await openHome(page, shellOf(testInfo));
		await expect(
			listenRegion(page).getByRole('button', { name: titles[0], exact: true })
		).toHaveCount(0);

		await postFromPage(page, `/api/songs/${song.id}/listen`);
		await page.reload();
		const albumRow = listenRegion(page).getByRole('button', { name: /^Open album / });
		await expect(albumRow).toHaveCount(1);
		const albumLabel = await albumRow.getAttribute('aria-label');
		if (!albumLabel) throw new Error('Listen album has no accessible name');
		for (const action of [COLLECTION_MENU_DELETE_LABEL, COLLECTION_MENU_ARCHIVE_LABEL]) {
			await listenRegion(page).getByRole('button', { name: albumLabel, exact: true }).click();
			await expect(page).toHaveURL(/\/album\//);
			await workspace(page)
				.getByRole('button', { name: COLLECTION_MENU_LABEL, exact: true })
				.click();
			await page.getByRole('button', { name: action, exact: true }).click();
			if (action === COLLECTION_MENU_DELETE_LABEL)
				await page.getByRole('button', { name: 'Delete Album', exact: true }).click();
			await openHome(page, shellOf(testInfo));
			await expect(
				listenRegion(page).getByRole('button', { name: albumLabel, exact: true })
			).toHaveCount(0);
			await page.getByRole('button', { name: 'Undo', exact: true }).click();
			await expect(
				listenRegion(page).getByRole('button', { name: albumLabel, exact: true })
			).toBeVisible();
		}
		guard.assertClean();
	} finally {
		// The admin's Search lists every account's live albums.
		if (accountApi && albumId) await archiveOwnedAlbum(accountApi, albumId);
		await accountApi?.dispose();
	}
});

test('1354_rule_19: a never-loaded Home offers Retry and then loads Listen', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page, {
		refusalsExpectedOn: [{ path: '/api/library/listen', statuses: [422] }]
	});
	await page.route('**/api/library/listen?*', (route) =>
		route.fulfill({
			status: 422,
			contentType: 'application/json',
			body: JSON.stringify({ detail: 'Listen unavailable' })
		})
	);
	await page.goto(HOME_PATH);
	await expect(listenRegion(page).getByText(HOME_LISTEN_ERROR)).toBeVisible();
	await page.screenshot({ path: testInfo.outputPath('listen-error.png') });
	await page.unroute('**/api/library/listen?*');
	await listenRegion(page).getByRole('button', { name: 'Retry', exact: true }).click();
	await expect(listenRegion(page).getByText(HOME_LISTEN_ERROR)).toHaveCount(0);
	await expect(listenRegion(page).getByRole('status')).toHaveCount(0);
	await expect(
		listenRegion(page)
			.locator('.library-row')
			.or(listenRegion(page).getByText(HOME_LISTEN_EMPTY))
			.first()
	).toBeVisible();
	guard.assertClean();
});

test('1354_rule_15: the playing Listen row offers Pause and its body opens the album', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const library = readSeededLibrary();
	await postFromPage(page, `/api/songs/${library.listenReorderSongs[shellOf(testInfo)].id}/listen`);
	await page.goto(HOME_PATH);
	await listenRegion(page)
		.getByRole('button', { name: `Play ${library.albumTitle}`, exact: true })
		.click();
	await expect(
		listenRegion(page).getByRole('button', { name: `Pause ${library.albumTitle}`, exact: true })
	).toBeVisible();
	await listenRegion(page)
		.getByRole('button', { name: `Open album ${library.albumTitle}`, exact: true })
		.click();
	await expect(page).toHaveURL(new RegExp(`/album/${library.albumId}$`));
	guard.assertClean();
});
