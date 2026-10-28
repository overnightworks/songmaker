// The song ⋯ stands on the same popover as the album's (#1495, #915 slice 3a):
// fully on screen whatever the title's length, in the album form, with Rename
// leaving the focus in the title. The operator's drive of 16.10.2026 found a
// 27-character title pushing the old panel up to 165 px past the right edge
// at 1024 px -- a layout promise only a real browser measures. Phone cells
// run in the mobile project (the phone app bar carries the menu there),
// laptop cells in the desktop one (the editor header carries it).

import { expect, test, type Locator, type Page, type TestInfo } from '@playwright/test';
import {
	COLLECTION_MENU_LABEL,
	DIALOG_CANCEL_LABEL,
	HITBOX_FREQUENT_PX,
	SONG_MENU_ADD_TO_PLAYLIST_LABEL,
	SONG_MENU_DELETE_LABEL,
	SONG_MENU_LABEL,
	SONG_MENU_RENAME_LABEL,
	SONG_MENU_SAVE_LABEL,
	SONG_TITLE_LABEL
} from '../src/lib/constants';
import {
	appBar,
	boundingBoxes,
	sameOriginHeaders,
	FlowGuard,
	ONLY_IN_SHELL,
	type Shell,
	workspace
} from './helpers';
import { expectMenuInsideViewport, rightOf, VIEWPORT_MARGIN_PX } from './menu-viewport';
import { archiveOwnedAlbum } from './seed';

const VIEWPORT_HEIGHT_PX = 844;
const SONG_RESOLVING_TEXT = 'Loading song...';
const ALBUM_FORM_MENU_WIDTH_PX = 238;
const ROW_LABELS_IN_ORDER = [
	SONG_MENU_SAVE_LABEL,
	SONG_MENU_RENAME_LABEL,
	SONG_MENU_ADD_TO_PLAYLIST_LABEL,
	SONG_MENU_DELETE_LABEL
];

/**
 * Own album and song per flow, so the flow's page loads cost the API what a cold song open
 * costs; the text-size cells add the album's own cold open. Measured locally: 18 for a song
 * flow, 31 on desktop and 29 on mobile with the album page.
 */
const SONG_MENU_FLOW_API_REQUEST_BUDGET = 40;

interface Cell {
	id: string;
	shell: Shell;
	width: number;
	title: string;
}

const TITLES = [
	'Blue hours',
	'Slow summer nights by train',
	'The quiet river keeps every promise the morning ever made to'
];
const WIDTHS: Array<{ shell: Shell; width: number }> = [
	{ shell: 'mobile', width: 390 },
	{ shell: 'desktop', width: 1024 },
	{ shell: 'desktop', width: 1280 }
];
const CELLS: Cell[] = TITLES.flatMap((title, titleIndex) =>
	WIDTHS.map(({ shell, width }, widthIndex) => ({
		id: `1495_S${titleIndex * WIDTHS.length + widthIndex + 1}`,
		shell,
		width,
		title
	}))
);

let guard: FlowGuard;

test.beforeEach(({ page }) => {
	guard = new FlowGuard(page);
});

// eslint-disable-next-line no-empty-pattern -- Playwright requires the object-destructuring form even with no fixture named
test.afterEach(({}, testInfo) => {
	console.log(`Song-menu flow /api requests (${testInfo.title}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(SONG_MENU_FLOW_API_REQUEST_BUDGET);
});

async function onOwnSong(
	page: Page,
	title: string,
	width: number,
	flow: (ids: { songId: string; albumId: string }) => Promise<void>
): Promise<void> {
	await page.setViewportSize({ width, height: VIEWPORT_HEIGHT_PX });
	const headers = await sameOriginHeaders(page);
	const album = await page.request.post('/api/albums', {
		headers,
		data: { title: `E2E Song menu ${Date.now()}`, artist: '' }
	});
	expect(album.ok()).toBe(true);
	const { id: albumId } = (await album.json()) as { id: string };
	try {
		const created = await page.request.post('/api/songs', {
			headers,
			data: { title, album_id: albumId, lyrics: `${title} lyrics`, prompt: 'calm test tone' }
		});
		expect(created.ok()).toBe(true);
		const song = (await created.json()) as { id: string; slug: string };
		await page.goto(`/album/${albumId}/${song.slug}`);
		await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
		await flow({ songId: song.id, albumId });
	} finally {
		// 1354_65_D2: every menu flow archives through the seed owner.
		await archiveOwnedAlbum(page.request, albumId);
	}
}

function menuTrigger(page: Page): Locator {
	return page.getByRole('button', { name: SONG_MENU_LABEL, exact: true });
}

async function openSongMenu(page: Page): Promise<Locator> {
	await menuTrigger(page).click();
	const menu = page.getByRole('dialog', { name: SONG_MENU_LABEL });
	await expect(menu).toBeVisible();
	return menu;
}

/** Delete song from the open menu, down to the confirm dialog with Cancel focused. */
async function openDeleteConfirm(page: Page, title: string): Promise<Locator> {
	const menu = await openSongMenu(page);
	await menu.getByRole('button', { name: SONG_MENU_DELETE_LABEL, exact: true }).click();

	const confirm = page.getByRole('dialog', { name: `Delete "${title}"?` });
	await expect(confirm).toBeVisible();
	await expect(confirm.getByRole('button', { name: DIALOG_CANCEL_LABEL })).toBeFocused();
	return confirm;
}

const isAlbumSongListing = (url: URL): boolean =>
	url.pathname === '/api/songs' && url.searchParams.has('album_id');
const isLibrarySongListing = (url: URL): boolean =>
	url.pathname === '/api/songs' && url.searchParams.has('sort');

/**
 * Opens the window in which the song's address still resolves although the song already stands in
 * the phone app bar: the album's first song-listing read answers once the library's own lists have
 * loaded, every re-read of it waits until released. The page keeps its "Loading song..." overlay,
 * and the workspace inert, until that re-read answers.
 */
async function holdSongListingRereads(page: Page): Promise<{ release: () => void }> {
	let release!: () => void;
	const released = new Promise<void>((resolve) => (release = resolve));
	const libraryListingAnswered = page.waitForResponse((response) =>
		isLibrarySongListing(new URL(response.url()))
	);
	let reads = 0;
	await page.route(isAlbumSongListing, async (route) => {
		reads += 1;
		if (reads === 1) await libraryListingAnswered;
		else await released;
		await route.continue();
	});
	return { release };
}

interface MenuTextSizes {
	heading: string;
	row: string;
}

async function fontSizeOf(element: Locator): Promise<string> {
	return element.evaluate((node) => getComputedStyle(node).fontSize);
}

async function menuTextSizes(menu: Locator): Promise<MenuTextSizes> {
	return {
		heading: await fontSizeOf(menu.locator('.menu-heading')),
		row: await fontSizeOf(menu.locator('.menu-item').first())
	};
}

async function openAlbumMenu(page: Page): Promise<Locator> {
	await workspace(page)
		.locator('.collection-header')
		.getByRole('button', { name: COLLECTION_MENU_LABEL, exact: true })
		.click();
	const menu = page.getByRole('dialog', { name: COLLECTION_MENU_LABEL });
	await expect(menu).toBeVisible();
	return menu;
}

/** Leaves the song page: the album's own page is where its menu stands. */
async function expectTextSizesOfAlbumMenu(
	page: Page,
	songMenu: Locator,
	albumId: string
): Promise<void> {
	const songSizes = await menuTextSizes(songMenu);
	await page.goto(`/album/${albumId}`);
	expect(songSizes).toEqual(await menuTextSizes(await openAlbumMenu(page)));
}

async function dangerColor(page: Page): Promise<string> {
	return page.evaluate(() => {
		const probe = document.createElement('span');
		probe.style.color = 'var(--score-bad)';
		document.body.append(probe);
		const { color } = getComputedStyle(probe);
		probe.remove();
		return color;
	});
}

async function expectAlbumForm(page: Page, menu: Locator, title: string): Promise<void> {
	const rows = menu.locator('.menu-item');
	await expect(rows).toHaveText(ROW_LABELS_IN_ORDER);
	for (const row of await rows.all()) await expect(row.locator('svg')).toHaveCount(1);
	for (const rowBox of await boundingBoxes(...(await rows.all())))
		expect(rowBox.height).toBeCloseTo(HITBOX_FREQUENT_PX, 0);

	const heading = menu.locator('.menu-heading');
	await expect(heading).toHaveText(`Song · ${title}`);
	await expect(heading).toHaveCSS('text-transform', 'uppercase');
	await expect(page.locator('.menu-backdrop')).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');

	const [panel] = await boundingBoxes(menu);
	expect(panel.width).toBeCloseTo(ALBUM_FORM_MENU_WIDTH_PX, 0);

	const danger = await dangerColor(page);
	await expect(rows.last()).toHaveText(SONG_MENU_DELETE_LABEL);
	await expect(rows.last()).toHaveCSS('color', danger);
	await expect(rows.first()).not.toHaveCSS('color', danger);
}

for (const { id, shell, width, title } of CELLS) {
	test(
		`${id}: the song ⋯ opens fully on screen in the album form at ${width} px with a ${title.length}-character title`,
		{ tag: ONLY_IN_SHELL[shell] },
		async ({ page }, testInfo: TestInfo) => {
			await onOwnSong(page, title, width, async ({ albumId }) => {
				const menu = await openSongMenu(page);

				await expectMenuInsideViewport(page, menu);
				await expectAlbumForm(page, menu, title);
				if (shell === 'mobile') {
					const [panel] = await boundingBoxes(menu);
					expect(rightOf(panel)).toBeCloseTo(width - VIEWPORT_MARGIN_PX, 0);
				}
				await testInfo.attach(`song-menu-${title.length}-chars-at-${width}px`, {
					body: await page.screenshot(),
					contentType: 'image/png'
				});
				await expectTextSizesOfAlbumMenu(page, menu, albumId);
			});
		}
	);
}

test(
	'1495_S10: Rename leaves the focus in the title field',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		await onOwnSong(page, TITLES[1], 1280, async () => {
			const menu = await openSongMenu(page);
			await menu.getByRole('button', { name: SONG_MENU_RENAME_LABEL, exact: true }).click();

			await expect(menu).toBeHidden();
			await expect(page.getByRole('textbox', { name: SONG_TITLE_LABEL })).toBeFocused();
		});
	}
);

test(
	'1495_S11: Delete song asks first, and Cancel keeps the song',
	{ tag: ONLY_IN_SHELL.mobile },
	async ({ page }) => {
		await onOwnSong(page, TITLES[1], 390, async ({ songId }) => {
			const confirm = await openDeleteConfirm(page, TITLES[1]);
			await confirm.getByRole('button', { name: DIALOG_CANCEL_LABEL }).click();

			await expect(confirm).toBeHidden();
			await expect(menuTrigger(page)).toBeFocused();
			await expect(page.getByRole('heading', { name: TITLES[1], exact: true })).toBeVisible();
			expect((await page.request.get(`/api/songs/${songId}`)).ok()).toBe(true);
		});
	}
);

test(
	'defect:#1531: the song ⋯ waits while the song loads, then Delete opens its dialog with Cancel focused',
	{ tag: ONLY_IN_SHELL.mobile },
	async ({ page }) => {
		const listing = await holdSongListingRereads(page);
		await onOwnSong(page, TITLES[1], 390, async () => {
			const trigger = appBar(page).getByLabel(SONG_MENU_LABEL, { exact: true });
			await expect(trigger).toBeVisible();
			await expect(page.getByText(SONG_RESOLVING_TEXT, { exact: true })).toBeVisible();
			const [triggerBox] = await boundingBoxes(trigger);
			await page.mouse.click(
				triggerBox.x + triggerBox.width / 2,
				triggerBox.y + triggerBox.height / 2
			);
			await expect(page.getByRole('dialog', { name: SONG_MENU_LABEL })).toBeHidden();

			listing.release();
			await openDeleteConfirm(page, TITLES[1]);
		});
	}
);

test(
	'1495_S12: Escape closes the menu and hands the focus back to its trigger',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		await onOwnSong(page, TITLES[0], 1024, async () => {
			const menu = await openSongMenu(page);
			await page.keyboard.press('Escape');

			await expect(menu).toBeHidden();
			await expect(menuTrigger(page)).toBeFocused();
		});
	}
);
