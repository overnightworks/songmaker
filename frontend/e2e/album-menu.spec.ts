// The collection ⋯ opens fully on screen, and a collection's Play · Shuffle · ⋯
// sit on their own row under cover and title (#1135, #915 F1+F5). Both are
// layout promises jsdom cannot measure, so only a real browser at a phone and
// a laptop width shows them: the operator's phone cut the album menu off past
// the left edge of the screen.

import { expect, test, type Locator, type Page, type TestInfo } from '@playwright/test';
import { COLLECTION_MENU_LABEL, collectionPlayLabel } from '../src/lib/constants';
import { boundingBoxes, FlowGuard, shellOf, workspace, type RenderedBox } from './helpers';
import { readSeededLibrary, seedPlaylist } from './seed';

const VIEWPORT_MARGIN_PX = 8;
const LAPTOP_WIDTH_PX = 1280;
const PHONE_WIDTH_PX = 390;
const VIEWPORT_HEIGHT_PX = 844;

/**
 * Sized from the neighbouring cold opens rather than measured: a playlist's
 * cold open costs 11 (playlist-address.spec.ts), and opening the ⋯ asks the
 * API nothing. The first green CI run logs the real count below.
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

function expectInside(inner: RenderedBox, outer: RenderedBox): void {
	expect(inner.x).toBeGreaterThanOrEqual(outer.x);
	expect(inner.y).toBeGreaterThanOrEqual(outer.y);
	expect(inner.x + inner.width).toBeLessThanOrEqual(outer.x + outer.width);
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
