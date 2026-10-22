import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import type { LibraryWriteResponse, PaginatedResponse, SongItem } from '../src/lib/api/types';
import {
	ACCOUNT_MENU_LABEL,
	ACCOUNT_MENU_LOGOUT_LABEL,
	COLLECTION_MENU_LABEL,
	COLLECTION_MENU_ARCHIVE_LABEL,
	HOME_LISTEN_EMPTY,
	LIBRARY_NEW_MENU_LABEL,
	HOME_WRITE_EMPTY,
	HOME_WRITE_ERROR,
	SONG_MENU_LABEL,
	SONG_MENU_DELETE_LABEL,
	homeWriteOpenLabel,
	songEditorOpenLabel
} from '../src/lib/constants';
import { songRoutePath } from '../src/lib/routes/addresses';
import {
	appBar,
	csrfHeaders,
	HOME_PATH,
	leftTheApp,
	loseNetwork,
	regainNetwork,
	openHome,
	openLibraryWall,
	shellOf,
	stubIdentityProvider,
	workspace,
	listenRegion,
	type Shell
} from './helpers';
import {
	archiveOwnedAlbum,
	BASE_URL,
	runMarker,
	seedAccount,
	seedUnpickedLibrary,
	signedInApi,
	type SeededAccount
} from './seed';

const writeRegion = (page: Page) => page.getByRole('region', { name: 'Write', exact: true });
const writeBodies = (page: Page) => writeRegion(page).locator('.wall-tile-body');
const writeEndpoint = '**/api/library/write';
async function signInWriter(page: Page, account: SeededAccount): Promise<void> {
	const context = page.context();
	await context.clearCookies();
	await page.goto('/login');
	await context.addCookies(account.cookies);
	// Leaves the way the form does, replacing the entry, so Back revisits the earlier page.
	await page.evaluate((address) => location.replace(address), HOME_PATH);
	await expect(page).toHaveURL(new RegExp(`${HOME_PATH}$`));
	await expect(writeRegion(page)).toBeVisible();
}
async function writerPost(page: Page, path: string, data: unknown = {}): Promise<{ id: string }> {
	const response = await page.request.post(path, { headers: await csrfHeaders(page), data });
	expect(response.ok(), `${path}: ${response.status()}`).toBe(true);
	return response.json();
}
async function writtenAnswer(page: Page): Promise<LibraryWriteResponse> {
	const response = await page.request.get('/api/library/write');
	expect(response.ok()).toBe(true);
	return response.json();
}
const ariaLabels = (rows: Locator) =>
	rows.evaluateAll((elements) => elements.map((element) => element.getAttribute('aria-label')));
async function expectWrittenOrder(page: Page, answer: LibraryWriteResponse): Promise<void> {
	await expect(writeBodies(page)).toHaveText(
		answer.items.map((item) => new RegExp(item.song_title))
	);
	expect(await ariaLabels(writeBodies(page))).toEqual(
		answer.items.map((item) => homeWriteOpenLabel(item.song_title))
	);
	expect(await ariaLabels(writeRegion(page).locator('.row-editor'))).toEqual(
		answer.items.map((item) => songEditorOpenLabel(item.song_title))
	);
}
async function editorPathOf(page: Page, songId: string): Promise<string> {
	const response = await page.request.get(`/api/songs/${songId}`);
	expect(response.ok()).toBe(true);
	const song: SongItem = await response.json();
	return songRoutePath(song.album_id, song.slug);
}
// Headless Chromium fires no visibilitychange on bringToFront, so the flip is dispatched.
async function flipVisible(page: Page): Promise<void> {
	await page.evaluate(() => {
		for (const state of ['hidden', 'visible']) {
			Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
			document.dispatchEvent(new Event('visibilitychange'));
		}
	});
}
async function foregroundWriter(page: Page): Promise<void> {
	const refreshed = page.waitForResponse(
		(response) => new URL(response.url()).pathname === '/api/library/write'
	);
	await flipVisible(page);
	await refreshed;
}
// At phone widths the song menu sits in the app bar, outside the workspace.
const songMenuOf = (page: Page, shell: Shell) =>
	(shell === 'mobile' ? appBar(page) : workspace(page)).getByRole('button', {
		name: SONG_MENU_LABEL,
		exact: true
	});

// Runs in the existing desktop/mobile projects, with a private account and real API state.
test('1354_37a_A1 1354_rule_14 1354_rule_16 1354_rule_18 1354_rule_19 1354_rule_20: Write composes Home, opens editors and follows offline, removal and Undo', async ({
	page,
	context,
	browser
}, testInfo) => {
	let account: SeededAccount | undefined;
	let accountApi: APIRequestContext | undefined;
	let releaseRemoval: (() => void) | undefined;
	let libraryAlbumId: string | undefined;
	try {
		account = await seedAccount(`e2e-write-${testInfo.project.name}-${runMarker()}`);
		accountApi = await signedInApi(account);
		await signInWriter(page, account);
		await expect(listenRegion(page).getByText(HOME_LISTEN_EMPTY)).toBeVisible();
		await expect(writeRegion(page).getByText(HOME_WRITE_EMPTY)).toBeVisible();
		expect(
			await workspace(page)
				.locator('section[aria-label]')
				.evaluateAll((regions) => regions.map((region) => region.getAttribute('aria-label')))
		).toEqual(['Listen', 'Write']);
		await expect(
			workspace(page).getByRole('button', { name: LIBRARY_NEW_MENU_LABEL, exact: true })
		).toBeVisible();
		await expect(workspace(page).getByText('Continue', { exact: true })).toHaveCount(0);
		await page.screenshot({ path: testInfo.outputPath('write-empty.png') });

		const library = await seedUnpickedLibrary(accountApi);
		libraryAlbumId = library.albumId;
		const songsResponse = await page.request.get(`/api/songs?album_id=${library.albumId}`);
		expect(songsResponse.ok()).toBe(true);
		const songs: PaginatedResponse<SongItem> = await songsResponse.json();
		const created: string[] = [];
		for (let index = 0; index < 4; index++) {
			const song = await writerPost(page, '/api/songs', {
				album_id: library.albumId,
				title: `E2E Write ${index}`
			});
			created.push(song.id);
		}
		for (const title of ['E2E Write revised', 'E2E Write final']) {
			const response = await page.request.put(`/api/songs/${created[1]}/title`, {
				headers: await csrfHeaders(page),
				data: { title }
			});
			expect(response.ok()).toBe(true);
		}
		const answer = await writtenAnswer(page);
		expect(answer.items).toHaveLength(3);
		expect(new Set(answer.items.map((item) => item.song_id)).size).toBe(3);
		expect(answer.items[0].song_id).toBe(created[1]);
		await writerPost(page, `/api/songs/${songs.items[0].id}/listen`);
		await page.reload();
		await expectWrittenOrder(page, answer);
		for (const row of await writeRegion(page).locator('.library-row').all()) {
			const bounds = await row.boundingBox();
			expect(bounds?.height).toBe(58);
			expect(bounds?.x ?? -1).toBeGreaterThanOrEqual(0);
			expect((bounds?.x ?? 0) + (bounds?.width ?? 0)).toBeLessThanOrEqual(
				page.viewportSize()?.width ?? 0
			);
			const pencil = await row.locator('.row-editor').boundingBox();
			expect(pencil?.width).toBe(44);
			expect(pencil?.height).toBe(44);
			await expect(row.locator('.tile-subtitle')).toContainText(answer.items[0].album_title);
		}
		await page.screenshot({ path: testInfo.outputPath('write-rows.png') });
		await listenRegion(page)
			.getByRole('button', { name: /^Play / })
			.click();
		await expect(listenRegion(page).getByRole('button', { name: /^Pause / })).toBeVisible();
		await listenRegion(page)
			.getByRole('button', { name: /^Pause / })
			.click();
		const editorPath = await editorPathOf(page, answer.items[0].song_id);
		for (const selector of ['.wall-tile-body', '.row-editor']) {
			await writeRegion(page).locator(selector).first().click();
			await expect(page).toHaveURL(new RegExp(`${editorPath}$`));
			if (shellOf(testInfo) === 'mobile') {
				await appBar(page).getByRole('button', { name: 'Back to Home', exact: true }).click();
			} else {
				await openHome(page, 'desktop');
			}
			await expect(listenRegion(page).getByRole('button', { name: /^Play / })).toBeVisible();
			await expect(listenRegion(page).locator('.tile-subtitle')).toContainText('stopped at song 1');
		}
		await loseNetwork(page, context);
		await openLibraryWall(page, shellOf(testInfo));
		await openHome(page, shellOf(testInfo));
		await expectWrittenOrder(page, answer);
		await regainNetwork(page, context);
		await foregroundWriter(page);
		const otherDevice = await browser.newContext({
			storageState: await context.storageState(),
			viewport: testInfo.project.use.viewport
		});
		try {
			const otherPage = await otherDevice.newPage();
			await otherPage.goto(BASE_URL + HOME_PATH);
			await expectWrittenOrder(otherPage, await writtenAnswer(page));
		} finally {
			await otherDevice.close();
		}

		await page.route(writeEndpoint, (route) =>
			route.fulfill({ status: 422, json: { detail: 'Write unavailable' } })
		);
		await foregroundWriter(page);
		await expectWrittenOrder(page, answer);
		await page.reload();
		await expect(writeRegion(page).getByText(HOME_WRITE_ERROR)).toBeVisible();
		await expect(writeRegion(page).getByText(HOME_WRITE_EMPTY)).toHaveCount(0);
		await page.screenshot({ path: testInfo.outputPath('write-error.png') });
		await page.unroute(writeEndpoint);
		await writeRegion(page).getByRole('button', { name: 'Retry', exact: true }).click();
		await expectWrittenOrder(page, answer);

		let holdFirst = true;
		const heldRemoval = new Promise<void>((resolve) => {
			releaseRemoval = resolve;
		});
		let readCaptured!: () => void;
		const captured = new Promise<void>((resolve) => {
			readCaptured = resolve;
		});
		await page.route(writeEndpoint, async (route) => {
			if (!holdFirst) return route.continue();
			holdFirst = false;
			const response = await route.fetch();
			readCaptured();
			await heldRemoval;
			await route.fulfill({ response });
		});
		await flipVisible(page);
		await captured;

		await writeBodies(page).first().click();
		await songMenuOf(page, shellOf(testInfo)).click();
		await page.getByRole('button', { name: SONG_MENU_DELETE_LABEL, exact: true }).click();
		await page.getByRole('button', { name: 'Delete Song', exact: true }).click();
		await openHome(page, shellOf(testInfo));
		await expect(writeBodies(page).filter({ hasText: answer.items[0].song_title })).toHaveCount(0);
		releaseRemoval?.();
		await expect(writeBodies(page)).toHaveCount(3);
		await page.unroute(writeEndpoint);
		await page.getByRole('button', { name: 'Undo', exact: true }).click();
		await expect(writeBodies(page).filter({ hasText: answer.items[0].song_title })).toBeVisible();
		await expectWrittenOrder(page, await writtenAnswer(page));

		await listenRegion(page)
			.getByRole('button', { name: /^Open album / })
			.click();
		await workspace(page).getByRole('button', { name: COLLECTION_MENU_LABEL, exact: true }).click();
		await page.getByRole('button', { name: COLLECTION_MENU_ARCHIVE_LABEL, exact: true }).click();
		await openHome(page, shellOf(testInfo));
		await expect(writeRegion(page).getByText(HOME_WRITE_EMPTY)).toBeVisible();
		await page.getByRole('button', { name: 'Undo', exact: true }).click();
		await expect(writeBodies(page)).toHaveCount(3);
		await expectWrittenOrder(page, await writtenAnswer(page));
	} finally {
		releaseRemoval?.();
		await page.unrouteAll({ behavior: 'ignoreErrors' });
		try {
			if (accountApi && libraryAlbumId) await archiveOwnedAlbum(accountApi, libraryAlbumId);
		} finally {
			await accountApi?.dispose();
		}
	}
});

for (const pending of [false, true]) {
	test(`1354_rule_06 1354_rule_19: logout replaces account A's Write document (read pending: ${pending})`, async ({
		page
	}, testInfo) => {
		const marker = runMarker();
		const accounts: SeededAccount[] = [];
		let release: (() => void) | undefined;
		let accountAlbumId: string | undefined;
		// Sign out ends at the issuer's logout address, which leaves the app's origin.
		await stubIdentityProvider(page.context());
		try {
			for (const suffix of ['a', 'b']) {
				accounts.push(await seedAccount(`e2e-write-${testInfo.project.name}-${marker}-${suffix}`));
			}
			await signInWriter(page, accounts[0]);
			const album = await writerPost(page, '/api/albums', { title: 'E2E Write account A' });
			accountAlbumId = album.id;
			await writerPost(page, '/api/songs', { album_id: album.id, title: 'E2E Write private A' });
			await page.reload();
			await expect(writeBodies(page)).toContainText(['E2E Write private A']);
			if (pending) {
				const held = new Promise<void>((resolve) => {
					release = resolve;
				});
				await page.route(writeEndpoint, async (route) => {
					const response = await route.fetch();
					await held;
					// Logout destroys the requesting document; the intercepted request may be gone.
					if (!page.isClosed()) await route.fulfill({ response });
				});
				const started = page.waitForRequest(
					(req) => new URL(req.url()).pathname === '/api/library/write'
				);
				await page.reload({ waitUntil: 'domcontentloaded' });
				await started;
			}
			await page
				.getByRole('button', {
					name: `${ACCOUNT_MENU_LABEL} · ${accounts[0].username}`,
					exact: true
				})
				.click();
			await page.getByRole('button', { name: ACCOUNT_MENU_LOGOUT_LABEL, exact: true }).click();
			await expect.poll(() => leftTheApp(page)).toBe(true);
			release?.();
			await page.unrouteAll({ behavior: 'wait' });
			await signInWriter(page, accounts[1]);
			await expect(writeRegion(page).getByText(HOME_WRITE_EMPTY)).toBeVisible();
			for (const direction of ['back', 'forward'] as const) {
				if (direction === 'back') await page.goBack();
				else await page.goForward();

				await expect(page.getByText('E2E Write private A', { exact: true })).toHaveCount(0);
			}
			await page.goto(HOME_PATH);
			await expect(writeRegion(page).getByText(HOME_WRITE_EMPTY)).toBeVisible();
		} finally {
			release?.();
			await page.unrouteAll({ behavior: 'ignoreErrors' });
			// Logout ended account A's session; a fresh one of the same account archives its album.
			if (accountAlbumId) {
				const accountApi = await signedInApi(await seedAccount(accounts[0].username));
				try {
					await archiveOwnedAlbum(accountApi, accountAlbumId);
				} finally {
					await accountApi.dispose();
				}
			}
		}
	});
}
