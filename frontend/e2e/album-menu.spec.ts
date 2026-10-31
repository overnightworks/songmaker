// The collection ⋯ opens fully on screen, and a collection's Play · ⋯
// sit on their own row under cover and title (#1135, #915 F1+F5). Both are
// layout promises jsdom cannot measure, so only a real browser at a phone and
// a laptop width shows them: the operator's phone cut the album menu off past
// the left edge of the screen.

import { expect, test, type Locator, type Page, type TestInfo } from '@playwright/test';
import {
	ALBUM_DETAILS_CLOSE_LABEL,
	ALBUM_DETAILS_SAVE_LABEL,
	ALBUM_DETAILS_SAVED,
	ALBUM_SUBTITLE_LABEL,
	ALBUM_YEAR_LABEL,
	COLLECTION_MENU_EDIT_DETAILS_LABEL,
	COLLECTION_MENU_LABEL,
	COLLECTION_MENU_SHARE_LABEL,
	COLLECTION_MENU_SHARE_OFF_HINT,
	COLLECTION_MENU_SHARE_ON_HINT,
	collectionActionLabel,
	HITBOX_FREQUENT_PX,
	NEW_ALBUM_TITLE_LABEL,
	TRANSPORT_PLAY_LABEL
} from '../src/lib/constants';
import { boundingBoxes, sameOriginHeaders, FlowGuard, shellOf, workspace } from './helpers';
import { bottomOf, expectMenuInsideViewport, rightOf } from './menu-viewport';
import { archiveOwnedAlbum, readSeededLibrary, seedPlaylist } from './seed';

const LAPTOP_WIDTH_PX = 1280;
const PHONE_WIDTH_PX = 390;
const VIEWPORT_HEIGHT_PX = 844;
const REMOVED_SAVE_OFFLINE_LABEL = 'Save offline';

/**
 * Measured in CI on PR #1136: the album cold open costs 14 on desktop and 11
 * on mobile, the playlist cold open 12 on desktop and 8 on mobile, and the
 * logged-out public album page 0 on both, since opening the ⋯ asks the API
 * nothing. Shared budget, sized from the costliest flow the same way
 * playlist-address.spec.ts's is. The Edit details flow opens an album of its
 * own, with no songs, and adds its one save. The Share row flow adds a share,
 * an unshare and a share: 16 on desktop locally, with a cold open of 13.
 */
const ALBUM_MENU_FLOW_API_REQUEST_BUDGET = 18;

type CollectionKind = 'album' | 'playlist';

let guard: FlowGuard;

function viewportFor(testInfo: TestInfo): { width: number; height: number } {
	const width = shellOf(testInfo) === 'mobile' ? PHONE_WIDTH_PX : LAPTOP_WIDTH_PX;
	return { width, height: VIEWPORT_HEIGHT_PX };
}

test.beforeEach(async ({ page }, testInfo) => {
	await page.setViewportSize(viewportFor(testInfo));
	guard = new FlowGuard(page);
});

// eslint-disable-next-line no-empty-pattern -- Playwright requires the object-destructuring form even with no fixture named
test.afterEach(({}, testInfo) => {
	console.log(`Album-menu flow /api requests (${testInfo.title}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(ALBUM_MENU_FLOW_API_REQUEST_BUDGET);
});

async function expectActionRowUnderCoverAndTitle(
	header: Locator,
	kind: CollectionKind,
	title: string
): Promise<void> {
	const heading = header.getByRole('heading', { name: title });
	const play = header.getByRole('button', {
		name: collectionActionLabel(TRANSPORT_PLAY_LABEL, kind),
		exact: true
	});
	await expect(heading).toBeVisible();
	await expect(play).toBeVisible();
	const [cover, titleBox, playBox] = await boundingBoxes(
		header.locator('.header-cover'),
		heading,
		play
	);
	expect(playBox.y).toBeGreaterThanOrEqual(Math.max(bottomOf(cover), bottomOf(titleBox)));
}

async function expectMenuAtRowEnd(header: Locator): Promise<void> {
	const [identity, menuTrigger] = await boundingBoxes(
		header.locator('.header-identity'),
		header.getByRole('button', { name: COLLECTION_MENU_LABEL, exact: true })
	);
	expect(rightOf(menuTrigger)).toBeCloseTo(rightOf(identity), 0);
}

async function openMenu(page: Page, header: Locator): Promise<Locator> {
	await header.getByRole('button', { name: COLLECTION_MENU_LABEL, exact: true }).click();
	const menu = page.getByRole('dialog', { name: COLLECTION_MENU_LABEL });
	await expect(menu).toBeVisible();
	return menu;
}

async function expectMenuFullyOnScreen(page: Page, header: Locator): Promise<void> {
	await expectMenuInsideViewport(page, await openMenu(page, header));
}

test('the album ⋯ opens fully on screen, under its own row of actions', async ({ page }) => {
	const library = readSeededLibrary();
	await page.goto(`/album/${library.albumId}`);
	const header = workspace(page).locator('.collection-header');

	await expectActionRowUnderCoverAndTitle(header, 'album', library.albumTitle);
	await expectMenuAtRowEnd(header);
	await expectMenuFullyOnScreen(page, header);
});

test('the playlist ⋯ opens fully on screen, under its own row of actions', async ({
	page,
	request
}) => {
	const playlist = await seedPlaylist(request, readSeededLibrary());
	await page.goto(`/playlist/${playlist.slug}`);
	const header = workspace(page).locator('.collection-header');

	await expectActionRowUnderCoverAndTitle(header, 'playlist', playlist.title);
	await expectMenuAtRowEnd(header);
	await expectMenuFullyOnScreen(page, header);
	await expect(page.getByRole('button', { name: REMOVED_SAVE_OFFLINE_LABEL })).toHaveCount(0);
});

test('the public playlist opens with the page-player order', async ({ browser }, testInfo) => {
	const library = readSeededLibrary();
	const { isMobile, hasTouch } = testInfo.project.use;
	const visitor = await browser.newContext({
		storageState: undefined,
		viewport: viewportFor(testInfo),
		isMobile,
		hasTouch
	});
	const sharePage = await visitor.newPage();
	const shareGuard = new FlowGuard(sharePage);

	try {
		await sharePage.goto(library.playlistShareUrl);
		await expect(sharePage.locator('.queue-row').first()).toBeVisible();
		await sharePage.evaluate(() => document.fonts.ready);
		const boxes = await boundingBoxes(
			sharePage.getByRole('heading', { level: 1 }),
			sharePage.locator('.now-playing-line'),
			sharePage.locator('.now-playing.page .transport'),
			sharePage.locator('.lyrics-heading'),
			sharePage.getByRole('heading', { name: 'Songs', exact: true })
		);
		if (shellOf(testInfo) === 'mobile') {
			for (let index = 1; index < boxes.length; index++)
				expect(boxes[index].y).toBeGreaterThan(boxes[index - 1].y);
		} else {
			const [cover, transport, lyrics, songs] = await boundingBoxes(
				sharePage.locator('.cover-art'),
				sharePage.locator('.now-playing.page .transport'),
				sharePage.locator('.np-page-lyrics'),
				sharePage.locator('.np-page-songs')
			);
			expect(cover.x + cover.width).toBeLessThanOrEqual(lyrics.x);
			expect(transport.x + transport.width).toBeLessThanOrEqual(lyrics.x);
			expect(lyrics.x + lyrics.width).toBeLessThanOrEqual(songs.x);
		}
		await expect(sharePage.locator('.collection-header')).toHaveCount(0);
	} finally {
		try {
			shareGuard.assertClean();
		} finally {
			await visitor.close();
		}
	}
});

async function openEditDetails(page: Page, header: Locator): Promise<Locator> {
	const menu = await openMenu(page, header);
	await menu.getByRole('button', { name: COLLECTION_MENU_EDIT_DETAILS_LABEL, exact: true }).click();
	const editor = header.getByRole('form', { name: COLLECTION_MENU_EDIT_DETAILS_LABEL });
	await expect(editor).toBeVisible();
	await expect(editor.getByLabel(NEW_ALBUM_TITLE_LABEL, { exact: true })).toBeFocused();
	return editor;
}

async function onOwnAlbum(
	page: Page,
	testInfo: TestInfo,
	flow: (album: { id: string; title: string }) => Promise<void>
): Promise<void> {
	const title = `E2E Nightdrive ${shellOf(testInfo)} ${Date.now()}`;
	const created = await page.request.post('/api/albums', {
		headers: await sameOriginHeaders(page),
		data: { title, artist: '' }
	});
	expect(created.ok()).toBe(true);
	const album = (await created.json()) as { id: string };
	try {
		await page.goto(`/album/${album.id}`);
		await flow({ id: album.id, title });
	} finally {
		await archiveOwnedAlbum(page.request, album.id);
	}
}

for (const outcome of ['success', 'throwing callback'] as const) {
	test(`1346-F11-menu: ${outcome} retains an archived proof album`, async ({ page }, testInfo) => {
		let albumId = '';
		const failure = new Error('Menu proof callback failed');
		const flow = onOwnAlbum(page, testInfo, async (album) => {
			albumId = album.id;
			expect(album.title).toMatch(/^E2E /);
			if (outcome === 'throwing callback') throw failure;
		});
		if (outcome === 'throwing callback') await expect(flow).rejects.toBe(failure);
		else await flow;

		const retained = await page.request.get(`/api/albums/${albumId}`);
		expect(retained.ok()).toBe(true);
		expect(await retained.json()).toMatchObject({ id: albumId, is_archived: true });
	});
}

test('Edit details changes title, subtitle and year; × and Back discard', async ({
	page
}, testInfo) => {
	await onOwnAlbum(page, testInfo, async (album) => {
		const title = album.title;
		const header = workspace(page).locator('.collection-header');
		await expect(header.getByRole('heading', { name: title })).toBeVisible();
		await expect(header).not.toContainText('Add subtitle');
		await expect(header).not.toContainText('Add year');

		const renamed = `${title} remastered`;
		let editor = await openEditDetails(page, header);
		await editor.getByLabel(NEW_ALBUM_TITLE_LABEL, { exact: true }).fill(renamed);
		await editor.getByLabel(ALBUM_SUBTITLE_LABEL, { exact: true }).fill('Late-night synthwave');
		await editor.getByLabel(ALBUM_YEAR_LABEL, { exact: true }).fill('2026');
		await editor.getByRole('button', { name: ALBUM_DETAILS_SAVE_LABEL, exact: true }).click();

		await expect(editor).toBeHidden();
		await expect(header.getByRole('heading', { name: renamed })).toBeVisible();
		const meta = header.locator('.header-meta');
		await expect(meta).toHaveText('Late-night synthwave · 2026');

		editor = await openEditDetails(page, header);
		await editor.getByLabel(ALBUM_YEAR_LABEL, { exact: true }).fill('1999');
		await editor.getByRole('button', { name: ALBUM_DETAILS_CLOSE_LABEL, exact: true }).click();
		await expect(editor).toBeHidden();
		await expect(meta).toHaveText('Late-night synthwave · 2026');

		editor = await openEditDetails(page, header);
		await editor.getByLabel(ALBUM_YEAR_LABEL, { exact: true }).fill('1999');
		await page.goBack();
		await expect(editor).toBeHidden();
		await expect(page).toHaveURL(new RegExp(`/album/${album.id}$`));
		await expect(header.getByRole('heading', { name: renamed })).toBeVisible();
		await expect(meta).toHaveText('Late-night synthwave · 2026');
	});
});

test('Back during a slow Edit details save keeps the form until the details are saved', async ({
	page
}, testInfo) => {
	await onOwnAlbum(page, testInfo, async (album) => {
		const header = workspace(page).locator('.collection-header');
		await expect(header.getByRole('heading', { name: album.title })).toBeVisible();
		let answerSave!: () => void;
		const saveMayAnswer = new Promise<void>((resolve) => (answerSave = resolve));
		let saveSent!: () => void;
		const saveIsSent = new Promise<void>((resolve) => (saveSent = resolve));
		await page.route(`**/api/albums/${album.id}`, async (route) => {
			if (route.request().method() !== 'PUT') return route.fallback();
			saveSent();
			await saveMayAnswer;
			return route.fallback();
		});

		const editor = await openEditDetails(page, header);
		await editor.getByLabel(ALBUM_YEAR_LABEL, { exact: true }).fill('2026');
		await editor.getByRole('button', { name: ALBUM_DETAILS_SAVE_LABEL, exact: true }).click();
		await saveIsSent;
		await page.goBack();

		await expect(editor).toBeVisible();
		await expect(editor.getByLabel(ALBUM_YEAR_LABEL, { exact: true })).toHaveValue('2026');
		await expect(page).toHaveURL(new RegExp(`/album/${album.id}$`));

		answerSave();
		await expect(page.getByText(ALBUM_DETAILS_SAVED, { exact: true })).toBeVisible();
		await expect(editor).toBeHidden();
		await expect(header.locator('.header-meta')).toHaveText('2026');
		await expect(page).toHaveURL(new RegExp(`/album/${album.id}$`));
	});
});

function shareRowOf(menu: Locator, label: string): Locator {
	return menu.getByRole('button', { name: label, exact: true });
}

// The row's word sits left of its state: a tap there is the tap that used to
// land on nothing, since only the icon beside it was a button.
async function centreOfWord(row: Locator, word: string): Promise<{ x: number; y: number }> {
	return row.evaluate((rowElement, wanted) => {
		const text = Array.from(rowElement.childNodes).find(
			(node) => node.textContent?.trim() === wanted
		);
		if (!text) throw new Error(`No text "${wanted}" in the row`);
		const range = document.createRange();
		range.selectNodeContents(text);
		const wordBox = range.getBoundingClientRect();
		const rowBox = rowElement.getBoundingClientRect();
		return {
			x: wordBox.x + wordBox.width / 2 - rowBox.x,
			y: wordBox.y + wordBox.height / 2 - rowBox.y
		};
	}, word);
}

async function expectShareState(row: Locator, shared: boolean): Promise<void> {
	await expect(row).toHaveAttribute('aria-pressed', String(shared));
	await expect(row.locator('.menu-item-hint')).toHaveText(
		shared ? COLLECTION_MENU_SHARE_ON_HINT : COLLECTION_MENU_SHARE_OFF_HINT
	);
}

async function expectRowIsOneTarget(row: Locator): Promise<void> {
	const [box] = await boundingBoxes(row);
	expect(box.height).toBeCloseTo(HITBOX_FREQUENT_PX, 0);
}

test('1480_R1, 1480_R2, 1480_R3: the album Share row is one 44 px target that shows off and on, from a tap on its word or the keys', async ({
	page
}, testInfo) => {
	await onOwnAlbum(page, testInfo, async (album) => {
		const header = workspace(page).locator('.collection-header');
		await expect(header.getByRole('heading', { name: album.title })).toBeVisible();
		const menu = await openMenu(page, header);
		const share = shareRowOf(menu, COLLECTION_MENU_SHARE_LABEL);

		await expectRowIsOneTarget(share);
		await expectShareState(share, false);

		const sharing = page.waitForResponse(
			(response) =>
				response.url().endsWith(`/api/albums/${album.id}/share`) &&
				response.request().method() === 'POST'
		);
		await share.click({ position: await centreOfWord(share, COLLECTION_MENU_SHARE_LABEL) });
		expect((await sharing).ok()).toBe(true);
		await expectShareState(share, true);
		await expectRowIsOneTarget(share);
		await expectMenuInsideViewport(page, menu);

		await share.press('Enter');
		await expectShareState(share, false);
		await share.press('Space');
		await expectShareState(share, true);
		await expectMenuInsideViewport(page, menu);
	});
});

test('1480_R1, 1480_R2: the playlist Share row is the same 44 px target, named for the playlist', async ({
	page,
	request
}) => {
	const playlist = await seedPlaylist(request, readSeededLibrary());
	await page.goto(`/playlist/${playlist.slug}`);
	const menu = await openMenu(page, workspace(page).locator('.collection-header'));
	const share = shareRowOf(menu, `${COLLECTION_MENU_SHARE_LABEL} playlist`);

	await expectRowIsOneTarget(share);
	await expectShareState(share, false);
	await expectMenuInsideViewport(page, menu);
});
