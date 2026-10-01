// The collection ⋯ opens fully on screen, and a collection's Play · Shuffle · ⋯
// sit on their own row under cover and title (#1135, #915 F1+F5). Both are
// layout promises jsdom cannot measure, so only a real browser at a phone and
// a laptop width shows them: the operator's phone cut the album menu off past
// the left edge of the screen.

import { expect, test, type Locator, type Page, type TestInfo } from '@playwright/test';
import {
	ALBUM_DETAILS_CLOSE_LABEL,
	ALBUM_DETAILS_SAVE_LABEL,
	ALBUM_SUBTITLE_LABEL,
	ALBUM_YEAR_LABEL,
	COLLECTION_MENU_EDIT_DETAILS_LABEL,
	COLLECTION_MENU_LABEL,
	collectionPlayLabel,
	NEW_ALBUM_TITLE_LABEL
} from '../src/lib/constants';
import {
	boundingBoxes,
	csrfHeaders,
	FlowGuard,
	shellOf,
	workspace,
	type RenderedBox
} from './helpers';
import { readSeededLibrary, seedPlaylist } from './seed';

const VIEWPORT_MARGIN_PX = 8;
const LAPTOP_WIDTH_PX = 1280;
const PHONE_WIDTH_PX = 390;
const VIEWPORT_HEIGHT_PX = 844;

/**
 * Measured in CI on PR #1136: the album cold open costs 14 on desktop and 11
 * on mobile, the playlist cold open 12 on desktop and 8 on mobile, and the
 * logged-out public album page 0 on both, since opening the ⋯ asks the API
 * nothing. Shared budget, sized from the costliest flow the same way
 * playlist-address.spec.ts's is. The Edit details flow opens an album of its
 * own, with no songs, and adds its one save.
 */
const ALBUM_MENU_FLOW_API_REQUEST_BUDGET = 15;

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

function bottomOf(box: RenderedBox): number {
	return box.y + box.height;
}

async function expectActionRowUnderCoverAndTitle(
	header: Locator,
	kind: CollectionKind,
	title: string
): Promise<void> {
	const heading = header.getByRole('heading', { name: title });
	const play = header.getByRole('button', { name: collectionPlayLabel(kind), exact: true });
	await expect(heading).toBeVisible();
	await expect(play).toBeVisible();
	const [cover, titleBox, playBox] = await boundingBoxes(
		header.locator('.header-cover'),
		heading,
		play
	);
	expect(playBox.y).toBeGreaterThanOrEqual(Math.max(bottomOf(cover), bottomOf(titleBox)));
}

function rightOf(box: RenderedBox): number {
	return box.x + box.width;
}

async function expectMenuAtRowEnd(header: Locator): Promise<void> {
	const [identity, menuTrigger] = await boundingBoxes(
		header.locator('.header-identity'),
		header.getByRole('button', { name: COLLECTION_MENU_LABEL, exact: true })
	);
	expect(rightOf(menuTrigger)).toBeCloseTo(rightOf(identity), 0);
}

function expectInside(inner: RenderedBox, outer: RenderedBox): void {
	expect(inner.x).toBeGreaterThanOrEqual(outer.x);
	expect(inner.y).toBeGreaterThanOrEqual(outer.y);
	expect(rightOf(inner)).toBeLessThanOrEqual(rightOf(outer));
	expect(bottomOf(inner)).toBeLessThanOrEqual(bottomOf(outer));
}

async function expectMenuFullyOnScreen(page: Page, header: Locator): Promise<void> {
	await header.getByRole('button', { name: COLLECTION_MENU_LABEL, exact: true }).click();
	const menu = page.getByRole('dialog', { name: COLLECTION_MENU_LABEL });
	await expect(menu).toBeVisible();
	const viewport = page.viewportSize();
	if (!viewport) throw new Error('Expected a fixed viewport to measure against');
	const [menuBox] = await boundingBoxes(menu);
	expectInside(menuBox, {
		x: VIEWPORT_MARGIN_PX,
		y: VIEWPORT_MARGIN_PX,
		width: viewport.width - 2 * VIEWPORT_MARGIN_PX,
		height: viewport.height - 2 * VIEWPORT_MARGIN_PX
	});
	const rows = await menu.getByRole('button').all();
	expect(rows.length).toBeGreaterThan(0);
	for (const rowBox of await boundingBoxes(...rows)) expectInside(rowBox, menuBox);
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
});

test('the public album page keeps its actions on their own row', async ({ browser }, testInfo) => {
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

	await sharePage.goto(library.albumShareUrl);

	await expectActionRowUnderCoverAndTitle(
		sharePage.locator('.collection-header'),
		'album',
		library.albumTitle
	);
	shareGuard.assertClean();
	await visitor.close();
});

async function openEditDetails(page: Page, header: Locator): Promise<Locator> {
	await header.getByRole('button', { name: COLLECTION_MENU_LABEL, exact: true }).click();
	await page
		.getByRole('dialog', { name: COLLECTION_MENU_LABEL })
		.getByRole('button', { name: COLLECTION_MENU_EDIT_DETAILS_LABEL, exact: true })
		.click();
	const editor = header.getByRole('form', { name: COLLECTION_MENU_EDIT_DETAILS_LABEL });
	await expect(editor).toBeVisible();
	await expect(editor.getByLabel(NEW_ALBUM_TITLE_LABEL, { exact: true })).toBeFocused();
	return editor;
}

test('Edit details changes title, subtitle and year; × and Back discard', async ({
	page
}, testInfo) => {
	const title = `Nightdrive ${shellOf(testInfo)} ${Date.now()}`;
	const created = await page.request.post('/api/albums', {
		headers: await csrfHeaders(page),
		data: { title, artist: '' }
	});
	expect(created.ok()).toBe(true);
	const album = (await created.json()) as { id: string };
	try {
		await page.goto(`/album/${album.id}`);
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
	} finally {
		const removed = await page.request.delete(`/api/albums/${album.id}`, {
			headers: await csrfHeaders(page)
		});
		expect(removed.ok()).toBe(true);
	}
});
