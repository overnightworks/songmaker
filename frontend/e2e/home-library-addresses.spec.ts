// Home at `/` and the Library at `/library` (#1506, #1354 rules 25, 31 and 40),
// driven the way a person reaches them: a pasted address, the brand, the word
// Library, a reload, Back and Forward. The rows are those of #1506's scenario
// matrix (3.5); each test names its row, and one test covers one row across
// the two shells (390 and 1440) and its origins.
//
// Rows 10a-10d seed an entry a tab kept from before the switch -- the Library
// wall's own `{browse}` state at `/` -- with `history.replaceState`, since that
// is the only way a browser can hold one now. 10a-10c hold whichever order the
// real load produces (the entry and the live snapshot finish in either) and
// assert the one outcome; 10d forces the route first by holding the snapshot.
// The hydration-first order cannot be forced here and is proven in the unit
// suite (libraryContext.test.ts) with controlled promises. Row 9 (the legacy
// `/?song=` redirect) lives in album-address.spec.ts, which is desktop-only.

import { expect, test, type Page } from '@playwright/test';
import {
	HOME_PAGE_LABEL,
	LIBRARY_NEW_MENU_LABEL,
	RAIL_DRAWER_LABEL,
	RAIL_LIBRARY_LABEL,
	RAIL_LIBRARY_NAV_LABEL,
	RAIL_SEARCH_LABEL,
	SESSION_LOST_REDIRECT_PARAM
} from '../src/lib/constants';
import {
	FlowGuard,
	HOME_PATH,
	HOME_URL,
	LIBRARY_PATH,
	LIBRARY_URL,
	ONLY_IN_SHELL,
	appBar,
	expectLibraryWallLoaded,
	loseNetwork,
	nameStartingWith,
	openAlbumFromRail,
	openHome,
	openLibraryWall,
	openRailNav,
	openSettingsSection,
	regainNetwork,
	scrollWallHalfway,
	shellOf,
	wallBody,
	workspace,
	type Shell
} from './helpers';
import { readSeededLibrary, type SeededLibrary } from './seed';

const CONTINUE_REGION = { name: 'Continue' };
const SETTINGS_SECTION = 'Voices';
const SETTINGS_URL = /\/settings\/voices$/;
const HISTORY_WRITES_KEY = 'historyWrites';
const WALL_SIGHTINGS_KEY = 'wallSightings';
const WALL_SELECTOR = '.library-wall';
// A rail filter nothing in the seeded library answers to: the only album the
// rail then lists is the one it keeps open.
const NO_SUCH_TITLE = 'zz-no-such-title';

const homeHeading = (page: Page) =>
	workspace(page).getByRole('heading', { name: HOME_PAGE_LABEL, exact: true });
const continueRegion = (page: Page) => workspace(page).getByRole('region', CONTINUE_REGION);
const wall = (page: Page) => workspace(page).locator(WALL_SELECTOR);
const historyLength = (page: Page) => page.evaluate(() => history.length);

function albumAddress(library: SeededLibrary): RegExp {
	return new RegExp(`/album/${library.albumId}$`);
}

async function expectHomeShown(page: Page): Promise<void> {
	await expect(page).toHaveURL(HOME_URL);
	await expect(homeHeading(page)).toBeVisible();
	await expect(continueRegion(page)).toBeVisible();
	await expect(wall(page)).toHaveCount(0);
}

async function expectWallShown(page: Page): Promise<void> {
	await expect(page).toHaveURL(LIBRARY_URL);
	await expectLibraryWallLoaded(page);
	await expect(continueRegion(page)).toHaveCount(0);
}

async function expectAlbumShown(page: Page, library: SeededLibrary): Promise<void> {
	await expect(page).toHaveURL(albumAddress(library));
	await expect(workspace(page).getByRole('heading', { name: library.albumTitle })).toBeVisible();
}

async function expectSettingsShown(page: Page): Promise<void> {
	await expect(page).toHaveURL(SETTINGS_URL);
	await expect(page.getByRole('heading', { name: SETTINGS_SECTION })).toBeVisible();
}

async function closeDrawer(page: Page): Promise<void> {
	await page.keyboard.press('Escape');
	await expect(page.getByRole('dialog', { name: RAIL_DRAWER_LABEL })).toBeHidden();
}

/** Whether the rail's word Library marks the page as the one shown; the phone's drawer is opened and closed again. */
async function expectLibraryWordCurrent(page: Page, shell: Shell, current: boolean): Promise<void> {
	const rail = await openRailNav(page, shell);
	const word = rail.getByRole('link', { name: nameStartingWith(RAIL_LIBRARY_LABEL) });
	if (current) await expect(word).toHaveAttribute('aria-current', 'page');
	else await expect(word).not.toHaveAttribute('aria-current', 'page');
	if (shell === 'mobile') await closeDrawer(page);
}

// What the rail lists for a filter nothing answers to: only the album the app
// keeps open as its context survives it (RailLibraryGroup), so the albums it
// lists are the albums the page was left holding.
async function expectRailKeepsOnlyAlbums(
	page: Page,
	shell: Shell,
	albumTitles: readonly string[]
): Promise<void> {
	const rail = await openRailNav(page, shell);
	await rail.getByRole('combobox', { name: RAIL_SEARCH_LABEL }).fill(NO_SUCH_TITLE);
	const albums = rail
		.getByRole('navigation', { name: RAIL_LIBRARY_NAV_LABEL })
		.getByRole('listitem');
	await expect(albums).toHaveCount(albumTitles.length);
	for (const title of albumTitles) await expect(albums.filter({ hasText: title })).toHaveCount(1);
}

function recordHistoryWrites(key: string): void {
	const writes: string[] = [];
	Reflect.set(window, key, writes);
	for (const method of ['pushState', 'replaceState'] as const) {
		const write = history[method].bind(history);
		history[method] = (data: unknown, unused: string, url?: string | URL | null) => {
			writes.push(new URL(String(url ?? location.href), location.href).pathname);
			write(data, unused, url);
		};
	}
}

/** From the next page load on, every address the app writes to history is noted. */
async function watchHistoryWrites(page: Page): Promise<void> {
	await page.addInitScript(recordHistoryWrites, HISTORY_WRITES_KEY);
}

function addressesWrittenToHistory(page: Page): Promise<string[]> {
	return page.evaluate((key) => Reflect.get(window, key) as string[], HISTORY_WRITES_KEY);
}

function watchForTheWall(args: { key: string; selector: string }): void {
	const sightings = { count: 0 };
	Reflect.set(window, args.key, sightings);
	new MutationObserver((records) => {
		for (const record of records) {
			for (const node of record.addedNodes) {
				if (
					node instanceof Element &&
					(node.matches(args.selector) || node.querySelector(args.selector))
				)
					sightings.count += 1;
			}
		}
	}).observe(document, { childList: true, subtree: true });
}

/** From the next page load on, every mount of the Library wall is counted, flashes included. */
async function countWallMounts(page: Page): Promise<void> {
	await page.addInitScript(watchForTheWall, { key: WALL_SIGHTINGS_KEY, selector: WALL_SELECTOR });
}

function wallMounts(page: Page): Promise<number> {
	return page.evaluate(
		(key) => (Reflect.get(window, key) as { count: number }).count,
		WALL_SIGHTINGS_KEY
	);
}

type RetainedCollection = { kind: 'album'; id: string } | null;

// The entry history stands on becomes what the Library wall wrote at `/` before
// #1506: surface `browse`, the album it had open (if any), no scroll.
async function ageEntryToBrowseAtHome(page: Page, collection: RetainedCollection): Promise<void> {
	await page.evaluate((retained) => {
		const states = history.state?.['sveltekit:states'];
		if (!states?.library) throw new Error('The entry carries no library state to age');
		const library = { ...states.library, surface: 'browse', collection: retained, scrollAnchor: 0 };
		history.replaceState(
			{ ...history.state, 'sveltekit:states': { ...states, library } },
			'',
			location.href
		);
	}, collection);
}

interface AppPage {
	readonly name: string;
	open(page: Page, shell: Shell, library: SeededLibrary): Promise<void>;
	expectStands(page: Page, library: SeededLibrary): Promise<void>;
}

const HOME: AppPage = {
	name: 'Home',
	open: async (page) => {
		await page.goto(HOME_PATH);
		await expectHomeShown(page);
	},
	expectStands: expectHomeShown
};

const LIBRARY: AppPage = {
	name: 'the Library',
	open: async (page) => {
		await page.goto(LIBRARY_PATH);
		await expectWallShown(page);
	},
	expectStands: expectWallShown
};

const ALBUM: AppPage = {
	name: 'an album',
	open: async (page, _shell, library) => {
		await page.goto(`/album/${library.albumId}`);
		await expectAlbumShown(page, library);
	},
	expectStands: expectAlbumShown
};

const SETTINGS: AppPage = {
	name: 'Settings',
	open: async (page, shell, library) => {
		await LIBRARY.open(page, shell, library);
		await openSettingsSection(page, shell, SETTINGS_SECTION);
		await expectSettingsShown(page);
	},
	expectStands: expectSettingsShown
};

for (const retainCollection of [false, true]) {
	test(
		retainCollection
			? '1354_rule_31 row 2 (H4): retained collection and scroll survive Back and reload'
			: '1354_rule_31 row 2 (H4) C1/C2: Back directly to the cold Library restores scroll and reload adds no entry',
		async ({ page }, testInfo) => {
			const guard = new FlowGuard(page);
			const body = wallBody(page);
			const album = wall(page).getByRole('button', {
				name: `Open album ${readSeededLibrary().albumTitle}`,
				exact: true
			});
			await page.goto(LIBRARY_PATH);
			await expect(album).toBeVisible();
			if (retainCollection) {
				await album.click();
				await expect(page).toHaveURL(/\/album\//);
				await openLibraryWall(page, shellOf(testInfo));
				await expect(album.locator('..')).toHaveClass(/selected/);
			}
			await expectLibraryWallLoaded(page);
			const scrolled = await scrollWallHalfway(page);
			const tiles = wall(page).locator('.tile-grid .wall-tile-body');
			const bounds = await body.evaluate((element) => {
				const { top, bottom } = element.getBoundingClientRect();
				return { top, bottom };
			});
			const visibleTile = await tiles.evaluateAll((elements, bounds) => {
				return elements.findIndex((element) => {
					const tile = element.getBoundingClientRect();
					return tile.top >= bounds.top && tile.bottom <= bounds.bottom;
				});
			}, bounds);
			expect(visibleTile, 'a wall tile is fully in view').toBeGreaterThanOrEqual(0);
			await tiles.nth(visibleTile).click();
			await expect(page).toHaveURL(/\/album\//);

			await page.goBack();

			await expect(page).toHaveURL(LIBRARY_URL);
			await expectLibraryWallLoaded(page);
			await expect
				.poll(() => body.evaluate((element) => Math.round(element.scrollTop)))
				.toBe(scrolled);
			if (retainCollection) await expect(album.locator('..')).toHaveClass(/selected/);
			const length = await historyLength(page);
			await page.reload();
			await expectLibraryWallLoaded(page);
			await expect
				.poll(() => body.evaluate((element) => Math.round(element.scrollTop)))
				.toBe(scrolled);
			expect(await historyLength(page)).toBe(length);
			if (retainCollection) await expect(album.locator('..')).toHaveClass(/selected/);
			guard.assertClean();
		}
	);
}

async function signInThroughTheForm(page: Page): Promise<void> {
	const username = process.env.ADMIN_USERNAME;
	const password = process.env.ADMIN_PASSWORD;
	if (!username || !password) throw new Error('The e2e stack requires admin credentials');
	await page.getByLabel('Username').fill(username);
	await page.getByLabel('Password').fill(password);
	await page.getByRole('button', { name: 'Enter', exact: true }).click();
}

test(
	'1354_rule_31 C3: sign-in lands on Home without adding a history entry',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page, context }) => {
		const guard = new FlowGuard(page, {
			refusalsExpectedOn: [{ path: '/api/auth/me', statuses: [401] }]
		});
		await context.clearCookies();
		await page.goto('/login');
		const length = await historyLength(page);

		await signInThroughTheForm(page);

		await expectHomeShown(page);
		expect(await historyLength(page)).toBe(length);
		guard.assertClean();
	}
);

test.describe('signed out', () => {
	test.use({ storageState: { cookies: [], origins: [] } });

	test('1354_rule_31 row 4: /library asks for sign-in and comes back to /library', async ({
		page
	}) => {
		const guard = new FlowGuard(page, {
			refusalsExpectedOn: [{ path: '/api/auth/me', statuses: [401] }]
		});

		await page.goto(LIBRARY_PATH);

		await expect(page).toHaveURL(
			(url) =>
				url.pathname === '/login' &&
				url.searchParams.get(SESSION_LOST_REDIRECT_PARAM) === LIBRARY_PATH &&
				url.search === `?${SESSION_LOST_REDIRECT_PARAM}=%2Flibrary`
		);
		await signInThroughTheForm(page);

		await expectWallShown(page);
		guard.assertClean();
	});
});

test('1354_rule_31 row 1: cold / shows Home, with Continue, no wall, no + New, and the Library word not current', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const shell = shellOf(testInfo);
	await countWallMounts(page);

	await page.goto(HOME_PATH);

	await expectHomeShown(page);
	await expect(workspace(page).locator('.tile-grid')).toHaveCount(0);
	await expect(
		workspace(page).getByRole('button', { name: LIBRARY_NEW_MENU_LABEL, exact: true })
	).toHaveCount(0);
	expect(await wallMounts(page), 'the wall never flashed before Home').toBe(0);
	await expectLibraryWordCurrent(page, shell, false);
	guard.assertClean();
});

test('1354_rule_31 row 2: cold /library shows the wall, with + New, no Continue, and the Library word current', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);

	await page.goto(LIBRARY_PATH);

	await expectWallShown(page);
	await expect(homeHeading(page)).toHaveCount(0);
	await expect(
		workspace(page).getByRole('button', { name: LIBRARY_NEW_MENU_LABEL, exact: true })
	).toBeVisible();
	await expectLibraryWordCurrent(page, shellOf(testInfo), true);
	guard.assertClean();
});

test('1354_rule_31 row 3a: Library, the brand, Home, then reload stays Home with no new entry', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	await page.goto(LIBRARY_PATH);
	await expectWallShown(page);

	await openHome(page, shellOf(testInfo));
	await expectHomeShown(page);
	const length = await historyLength(page);
	await page.reload();

	await expectHomeShown(page);
	expect(await historyLength(page)).toBe(length);
	guard.assertClean();
});

test('1354_rule_31 row 3b: Home, the word Library, then reload stays the Library with no new entry', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	await page.goto(HOME_PATH);
	await expectHomeShown(page);

	await openLibraryWall(page, shellOf(testInfo));
	await expectWallShown(page);
	const length = await historyLength(page);
	await page.reload();

	await expectWallShown(page);
	expect(await historyLength(page)).toBe(length);
	guard.assertClean();
});

for (const origin of [LIBRARY, ALBUM, SETTINGS]) {
	test(`1354_rule_40 row 5: the brand opens Home from ${origin.name}, and Back returns there`, async ({
		page
	}, testInfo) => {
		const guard = new FlowGuard(page);
		const shell = shellOf(testInfo);
		const library = readSeededLibrary();
		await origin.open(page, shell, library);

		await openHome(page, shell);
		await expectHomeShown(page);
		await page.goBack();

		await origin.expectStands(page, library);
		guard.assertClean();
	});
}

test('1354_rule_31 1354_rule_25 row 6 (H2/H3): Home, Library, album, then Back, Back, Forward, Forward restore each page and the wall scroll', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const shell = shellOf(testInfo);
	const library = readSeededLibrary();
	await page.goto(HOME_PATH);
	await expectHomeShown(page);
	await openLibraryWall(page, shell);
	await expectWallShown(page);
	const scrolled = await scrollWallHalfway(page);
	await workspace(page)
		.getByRole('button', { name: `Open album ${library.albumTitle}`, exact: true })
		.click();
	await expectAlbumShown(page, library);
	const length = await historyLength(page);
	const wallScroll = () => wallBody(page).evaluate((body) => Math.round(body.scrollTop));

	await page.goBack();
	await expectWallShown(page);
	await expect.poll(wallScroll).toBe(scrolled);

	await page.goBack();
	await expectHomeShown(page);

	await page.goForward();
	await expectWallShown(page);
	await expect.poll(wallScroll).toBe(scrolled);

	await page.goForward();
	await expectAlbumShown(page, library);
	expect(await historyLength(page)).toBe(length);
	guard.assertClean();
});

for (const origin of [HOME, LIBRARY]) {
	test(`1354_rule_31 row 7 (H7): Settings from ${origin.name}, then Back returns it and Forward returns Settings`, async ({
		page
	}, testInfo) => {
		const guard = new FlowGuard(page);
		const shell = shellOf(testInfo);
		const library = readSeededLibrary();
		await origin.open(page, shell, library);

		await openSettingsSection(page, shell, SETTINGS_SECTION);
		await expectSettingsShown(page);
		await page.goBack();
		await origin.expectStands(page, library);
		await page.goForward();

		await expectSettingsShown(page);
		guard.assertClean();
	});
}

// The phone's ‹ names the page below the album, and goes there when clicked;
// a cold album has none below it and goes to the Library. A Continue row opens
// a song, which carries its own bar instead of ‹, so the album is opened from
// Home through the drawer's album row.
const BACK_ARROW_CELLS: readonly {
	readonly origin: string;
	readonly name: string;
	readonly openAlbum: (page: Page, shell: Shell, library: SeededLibrary) => Promise<void>;
	readonly returnsTo: AppPage;
}[] = [
	{
		origin: 'Home',
		name: HOME_PAGE_LABEL,
		openAlbum: async (page, shell, library) => {
			await HOME.open(page, shell, library);
			await openAlbumFromRail(page, shell, library.albumTitle);
		},
		returnsTo: HOME
	},
	{
		origin: 'the Library',
		name: RAIL_LIBRARY_LABEL,
		openAlbum: async (page, shell, library) => {
			await LIBRARY.open(page, shell, library);
			await wall(page)
				.getByRole('button', { name: `Open album ${library.albumTitle}`, exact: true })
				.click();
		},
		returnsTo: LIBRARY
	},
	{
		origin: 'a cold address',
		name: RAIL_LIBRARY_LABEL,
		openAlbum: async (page) => {
			await page.goto(`/album/${readSeededLibrary().albumId}`);
		},
		returnsTo: LIBRARY
	}
];

for (const cell of BACK_ARROW_CELLS) {
	test(
		`1354_rule_25 row 8: an album opened from ${cell.origin} reads Back to ${cell.name} and goes there`,
		{ tag: ONLY_IN_SHELL.mobile },
		async ({ page }) => {
			const guard = new FlowGuard(page);
			const library = readSeededLibrary();
			await cell.openAlbum(page, 'mobile', library);
			await expectAlbumShown(page, library);

			await appBar(page)
				.getByRole('button', { name: `Back to ${cell.name}`, exact: true })
				.click();

			await cell.returnsTo.expectStands(page, library);
			guard.assertClean();
		}
	);
}

test('1354_R1prime row 10a: a pre-switch {browse} entry at / reads as Home after a reload, adding no entry', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const shell = shellOf(testInfo);
	await watchHistoryWrites(page);
	await page.goto(HOME_PATH);
	await expectHomeShown(page);
	await ageEntryToBrowseAtHome(page, null);
	const length = await historyLength(page);

	await page.reload();

	await expectHomeShown(page);
	expect(await historyLength(page)).toBe(length);
	expect(await addressesWrittenToHistory(page)).not.toContain(LIBRARY_PATH);
	await expectRailKeepsOnlyAlbums(page, shell, []);
	guard.assertClean();
});

test('1354_R1prime row 10b: a pre-switch {browse} entry at / reached by Back from an album reads as Home, never /library', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const shell = shellOf(testInfo);
	const library = readSeededLibrary();
	await watchHistoryWrites(page);
	await page.goto(HOME_PATH);
	await expectHomeShown(page);
	await openAlbumFromRail(page, shell, library.albumTitle);
	await expectAlbumShown(page, library);
	const length = await historyLength(page);
	await page.goBack();
	await expectHomeShown(page);
	await ageEntryToBrowseAtHome(page, null);
	await page.goForward();
	await expectAlbumShown(page, library);

	await page.goBack();

	await expectHomeShown(page);
	await page.goForward();
	await expectAlbumShown(page, library);
	expect(await historyLength(page)).toBe(length);
	expect(await addressesWrittenToHistory(page)).not.toContain(LIBRARY_PATH);
	guard.assertClean();
});

test('1354_R1prime row 10c: a pre-switch {browse, album} entry at / reads as Home with no album page and the rail keeping the album', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const shell = shellOf(testInfo);
	const library = readSeededLibrary();
	await watchHistoryWrites(page);
	await page.goto(HOME_PATH);
	await expectHomeShown(page);
	await ageEntryToBrowseAtHome(page, { kind: 'album', id: library.albumId });
	const length = await historyLength(page);

	await page.reload();

	await expectHomeShown(page);
	await expect(workspace(page).getByRole('heading', { name: library.albumTitle })).toHaveCount(0);
	expect(await historyLength(page)).toBe(length);
	expect(await addressesWrittenToHistory(page)).not.toContain(LIBRARY_PATH);
	await expectRailKeepsOnlyAlbums(page, shell, [library.albumTitle]);
	if (shell === 'mobile') await closeDrawer(page);
	await expectLibraryWordCurrent(page, shell, false);
	guard.assertClean();
});

test(
	'1354_R1prime row 10d: the route resolving before the live snapshot leaves a pre-switch {browse, album} entry at / as Home',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page }) => {
		const guard = new FlowGuard(page);
		const library = readSeededLibrary();
		await watchHistoryWrites(page);
		await page.goto(HOME_PATH);
		await expectHomeShown(page);
		await ageEntryToBrowseAtHome(page, { kind: 'album', id: library.albumId });
		let releaseSnapshot!: () => void;
		const snapshotReleased = new Promise<void>((release) => (releaseSnapshot = release));
		let heldReads = 0;
		await page.route(
			(url) => url.pathname === '/api/albums',
			async (route) => {
				heldReads += 1;
				await snapshotReleased;
				await route.continue();
			}
		);

		await page.reload();
		await expect.poll(() => heldReads, 'the snapshot is held at its first read').toBeGreaterThan(0);
		await expect(page).toHaveURL(HOME_URL);
		releaseSnapshot();

		await expectHomeShown(page);
		await expect(workspace(page).getByRole('heading', { name: library.albumTitle })).toHaveCount(0);
		expect(await addressesWrittenToHistory(page)).not.toContain(LIBRARY_PATH);
		guard.assertClean();
	}
);

test(
	'1354_rule_31 R6 row 12: with the network gone Home mounts without rows and the word Library still opens the wall',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page, context }) => {
		const guard = new FlowGuard(page, { losesNetworkOnPurpose: true });
		await page.goto(HOME_PATH);
		await expectHomeShown(page);
		await loseNetwork(page, context);

		await openHome(page, 'desktop');
		await openLibraryWall(page, 'desktop');
		await expectWallShown(page);
		await openHome(page, 'desktop');

		await expect(homeHeading(page)).toBeVisible();
		await expect(continueRegion(page)).toBeVisible();
		await expect(continueRegion(page).locator('.continue-item')).toHaveCount(0);
		await expect(wall(page)).toHaveCount(0);
		await openLibraryWall(page, 'desktop');
		await expectWallShown(page);
		await regainNetwork(page, context);
		guard.assertClean();
	}
);
