import { scrollWallTo } from './wall-scroll';
import { PHONE_TABS_NAV_LABEL } from '../src/lib/constants/phone-tabs';
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

import { phoneSearchResult } from './phone-search';
import { expect, test, type Page } from '@playwright/test';
import {
	HOME_PAGE_LABEL,
	LIBRARY_NEW_MENU_LABEL,
	PLAYLISTS_PAGE_LABEL,
	LIBRARY_PAGE_LABEL,
	RAIL_SETTINGS_LABEL,
	SIGN_IN_NEXT_PARAM
} from '../src/lib/constants';
import { SIGN_IN_ACTION_LABEL } from '../src/lib/constants/auth';
import { PLAYLISTS_ROUTE_PATH } from '../src/lib/routes/addresses';
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
	nextSignInStart,
	nameStartingWith,
	openAlbumFromRail,
	openHome,
	openLibraryWall,
	openRailNav,
	openSettingsFromAccountMenu,
	openSettingsSection,
	regainNetwork,
	shellOf,
	stubIdentityProvider,
	waitForServiceWorkerControl,
	wallBody,
	workspace,
	type Shell
} from './helpers';
import { readSeededLibrary, type SeededLibrary } from './seed';

const LISTEN_REGION = { name: 'Listen' };
const SETTINGS_SECTION = 'Voices';
const SETTINGS_SECTION_URL = /\/settings\/voices$/;
const SETTINGS_LIST_URL = /\/settings$/;
const PLAYLISTS_URL = /\/playlists$/;
const PLAYLISTS_HEADING = new RegExp(`^${PLAYLISTS_PAGE_LABEL}( · \\d+)?$`);
const SAME_DOCUMENT_KEY = 'sameDocument';
const HISTORY_WRITES_KEY = 'historyWrites';
const WALL_SIGHTINGS_KEY = 'wallSightings';
const WALL_SELECTOR = '.library-wall';

const homeHeading = (page: Page) =>
	workspace(page).getByRole('heading', { name: HOME_PAGE_LABEL, exact: true });
const newButton = (page: Page) =>
	workspace(page).getByRole('button', { name: LIBRARY_NEW_MENU_LABEL, exact: true });
const listenRegion = (page: Page) => workspace(page).getByRole('region', LISTEN_REGION);
const wall = (page: Page) => workspace(page).locator(WALL_SELECTOR);
const historyLength = (page: Page) => page.evaluate(() => history.length);

function albumAddress(library: SeededLibrary): RegExp {
	return new RegExp(`/album/${library.albumId}$`);
}

async function openAlbumFromHome(page: Page, shell: Shell, title: string): Promise<void> {
	if (shell === 'mobile') {
		await (await phoneSearchResult(page, 'Albums', title, nameStartingWith(title))).click();
	} else {
		await openAlbumFromRail(page, shell, title);
	}
}

async function expectHomeShown(page: Page): Promise<void> {
	await expect(page).toHaveURL(HOME_URL);
	await expect(homeHeading(page)).toBeVisible();
	await expect(listenRegion(page)).toBeVisible();
	await expect(wall(page)).toHaveCount(0);
}

async function expectWallShown(page: Page): Promise<void> {
	await expect(page).toHaveURL(LIBRARY_URL);
	await expectLibraryWallLoaded(page);
	await expect(listenRegion(page)).toHaveCount(0);
}

async function expectPlaylistsShown(page: Page): Promise<void> {
	await expect(page).toHaveURL(PLAYLISTS_URL);
	await expect(workspace(page).getByRole('heading', { name: PLAYLISTS_HEADING })).toBeVisible();
}

async function expectAlbumShown(page: Page, library: SeededLibrary): Promise<void> {
	await expect(page).toHaveURL(albumAddress(library));
	await expect(workspace(page).getByRole('heading', { name: library.albumTitle })).toBeVisible();
}

// The desktop rail opens a Settings section; the phone's account menu opens the
// Settings list, whose sections are one tap further.
async function openSettings(page: Page, shell: Shell): Promise<void> {
	if (shell === 'mobile') await openSettingsFromAccountMenu(page);
	else await openSettingsSection(page, shell, SETTINGS_SECTION);
}

async function expectSettingsShown(page: Page, shell: Shell): Promise<void> {
	const [url, heading] =
		shell === 'mobile'
			? [SETTINGS_LIST_URL, RAIL_SETTINGS_LABEL]
			: [SETTINGS_SECTION_URL, SETTINGS_SECTION];
	await expect(page).toHaveURL(url);
	await expect(page.getByRole('heading', { name: heading })).toBeVisible();
}

type RailWord = typeof HOME_PAGE_LABEL | typeof LIBRARY_PAGE_LABEL | typeof PLAYLISTS_PAGE_LABEL;
const RAIL_WORDS: readonly RailWord[] = [LIBRARY_PAGE_LABEL, PLAYLISTS_PAGE_LABEL];

async function expectCurrentRailWord(
	page: Page,
	current: RailWord | null,
	shell: Shell = 'desktop'
): Promise<void> {
	const rail =
		shell === 'mobile'
			? page.getByRole('navigation', { name: PHONE_TABS_NAV_LABEL })
			: await openRailNav(page, shell);
	for (const label of shell === 'mobile' ? [HOME_PAGE_LABEL, ...RAIL_WORDS] : RAIL_WORDS) {
		const word = rail.getByRole(shell === 'mobile' ? 'button' : 'link', {
			name: nameStartingWith(label)
		});
		if (label === current) await expect(word).toHaveAttribute('aria-current', 'page');
		else await expect(word).not.toHaveAttribute('aria-current', 'page');
	}
}

// The album a page was left holding as its open collection is the one the idle
// mini-player offers to play; with none open it offers the Library.
async function expectOpenCollectionNamedByMiniPlayer(
	page: Page,
	albumTitle: string,
	named: boolean
): Promise<void> {
	const miniPlayer = page.getByRole('contentinfo');
	if (named) await expect(miniPlayer).toContainText(albumTitle, { ignoreCase: true });
	else await expect(miniPlayer).not.toContainText(albumTitle, { ignoreCase: true });
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
	expectStands(page: Page, shell: Shell, library: SeededLibrary): Promise<void>;
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

const PLAYLISTS: AppPage = {
	name: 'the Playlists page',
	open: async (page) => {
		await page.goto(PLAYLISTS_ROUTE_PATH);
		await expectPlaylistsShown(page);
	},
	expectStands: expectPlaylistsShown
};

const ALBUM: AppPage = {
	name: 'an album',
	open: async (page, _shell, library) => {
		await page.goto(`/album/${library.albumId}`);
		await expectAlbumShown(page, library);
	},
	expectStands: (page, _shell, library) => expectAlbumShown(page, library)
};

const SETTINGS: AppPage = {
	name: 'Settings',
	open: async (page, shell, library) => {
		await LIBRARY.open(page, shell, library);
		await openSettings(page, shell);
		await expectSettingsShown(page, shell);
	},
	expectStands: (page, shell) => expectSettingsShown(page, shell)
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
			const scrolled = await scrollWallTo(page, 'halfway');
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

test(
	'1354_rule_31 C3: Log in on the signed-out page leaves for the server sign-in start in one navigation, adding one history entry',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page, context }) => {
		const guard = new FlowGuard(page);
		await context.clearCookies();
		await stubIdentityProvider(context);
		await page.goto('/login');
		const length = await historyLength(page);
		const documentRequests: string[] = [];
		page.on('request', (request) => {
			if (request.isNavigationRequest()) documentRequests.push(new URL(request.url()).pathname);
		});

		const [start] = await Promise.all([
			nextSignInStart(page),
			page.getByRole('link', { name: SIGN_IN_ACTION_LABEL, exact: true }).click()
		]);

		expect(start.status).toBe(303);
		expect(start.requested.search).toBe('');
		expect(start.location.origin).not.toBe(start.requested.origin);
		expect(documentRequests[0]).toBe('/login/oidc');
		await expect.poll(() => historyLength(page), "one entry, the issuer's").toBe(length + 1);
		await expect.poll(() => guard.forgivenIssuerNavigations).toEqual([start.location.href]);
		guard.assertClean();
	}
);

test.describe('signed out', () => {
	test.use({ storageState: { cookies: [], origins: [] } });

	test('1354_rule_31 row 4: /library asks the server to sign in and to come back to /library', async ({
		page,
		context
	}) => {
		const guard = new FlowGuard(page, {
			refusalsExpectedOn: [{ path: '/api/auth/me', statuses: [401] }]
		});
		await stubIdentityProvider(context);

		const [start] = await Promise.all([nextSignInStart(page), page.goto(LIBRARY_PATH)]);

		expect(start.requested.searchParams.get(SIGN_IN_NEXT_PARAM)).toBe(LIBRARY_PATH);
		expect(start.requested.search).toBe(`?${SIGN_IN_NEXT_PARAM}=%2Flibrary`);
		expect(start.status).toBe(303);
		expect(start.location.origin).not.toBe(start.requested.origin);
		await expect.poll(() => guard.forgivenIssuerNavigations).toEqual([start.location.href]);
		guard.assertClean();
	});
});

for (const shell of ['desktop', 'mobile'] as const) {
	test(
		`1354_rule_14 1354_rule_31 row 1: cold / shows Home, with Listen and + New, no wall${shell === 'desktop' ? ', and the Library word not current' : ''} (${shell})`,
		{ tag: ONLY_IN_SHELL[shell] },
		async ({ page }) => {
			const guard = new FlowGuard(page);
			await countWallMounts(page);

			await page.goto(HOME_PATH);

			await expectHomeShown(page);
			await expect(workspace(page).locator('.tile-grid')).toHaveCount(0);
			await expect(newButton(page)).toBeVisible();
			expect(await wallMounts(page), 'the wall never flashed before Home').toBe(0);
			if (shell === 'desktop') await expectCurrentRailWord(page, null);
			guard.assertClean();
		}
	);
}

for (const shell of ['desktop', 'mobile'] as const) {
	test(
		`1354_rule_14 1354_rule_31 row 2: cold /library shows the wall, with + New on the desktop head only, no Listen${shell === 'desktop' ? ', and the Library word current' : ''} (${shell})`,
		{ tag: ONLY_IN_SHELL[shell] },
		async ({ page }) => {
			const guard = new FlowGuard(page);

			await page.goto(LIBRARY_PATH);

			await expectWallShown(page);
			await expect(homeHeading(page)).toHaveCount(0);
			await expect(newButton(page)).toHaveCount(shell === 'desktop' ? 1 : 0);
			if (shell === 'desktop') await expectCurrentRailWord(page, LIBRARY_PAGE_LABEL);
			guard.assertClean();
		}
	);
}

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

// The rail's words follow the address history stands on, not the surface a
// page left behind: Settings changes no surface, so it must not leave the word
// of the page it was opened from marked.
for (const [origin, railWord] of [
	[LIBRARY, LIBRARY_PAGE_LABEL],
	[PLAYLISTS, PLAYLISTS_PAGE_LABEL]
] as const) {
	for (const shell of ['desktop', 'mobile'] as const) {
		test(
			`1354_61_C${origin === PLAYLISTS ? '09' : '08'} defect:#1523 1354_rule_40 1354_37b_64 1354_rule_31: ${origin.name}, Settings and Back restore current navigation in one document (${shell})`,
			{ tag: ONLY_IN_SHELL[shell] },
			async ({ page }) => {
				const guard = new FlowGuard(page);
				const library = readSeededLibrary();
				await origin.open(page, shell, library);
				await expectCurrentRailWord(page, railWord, shell);
				await page.evaluate((key) => Reflect.set(window, key, true), SAME_DOCUMENT_KEY);

				await openSettings(page, shell);
				await expectSettingsShown(page, shell);
				await expectCurrentRailWord(page, null, shell);
				await page.goBack();

				await origin.expectStands(page, shell, library);
				await expectCurrentRailWord(page, railWord, shell);
				expect(
					await page.evaluate((key) => Reflect.get(window, key), SAME_DOCUMENT_KEY),
					'the journey stayed in one document'
				).toBe(true);
				guard.assertClean();
			}
		);
	}
}

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

		await origin.expectStands(page, shell, library);
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
	const scrolled = await scrollWallTo(page, 'halfway');
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

		await openSettings(page, shell);
		await expectSettingsShown(page, shell);
		await page.goBack();
		await origin.expectStands(page, shell, library);
		await page.goForward();

		await expectSettingsShown(page, shell);
		guard.assertClean();
	});
}

// The phone's ‹ names the page below the album, and goes there when clicked;
// a cold album has none below it and goes to the Library. A Listen row opens
// an album; this address proof uses phone search or the desktop rail.
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
			await openAlbumFromHome(page, shell, library.albumTitle);
		},
		returnsTo: HOME
	},
	{
		origin: 'the Library',
		name: LIBRARY_PAGE_LABEL,
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
		name: LIBRARY_PAGE_LABEL,
		openAlbum: async (page) => {
			await page.goto(`/album/${readSeededLibrary().albumId}`);
		},
		returnsTo: LIBRARY
	}
];

for (const cell of BACK_ARROW_CELLS) {
	test(
		`1354_37a_A2 1354_rule_25 row 8: an album opened from ${cell.origin} reads Back to ${cell.name} and goes there`,
		{ tag: ONLY_IN_SHELL.mobile },
		async ({ page }) => {
			const guard = new FlowGuard(page);
			const library = readSeededLibrary();
			await cell.openAlbum(page, 'mobile', library);
			await expectAlbumShown(page, library);

			await appBar(page)
				.getByRole('button', { name: `Back to ${cell.name}`, exact: true })
				.click();

			await cell.returnsTo.expectStands(page, 'mobile', library);
			guard.assertClean();
		}
	);
}

test('1354_R1prime row 10a: a pre-switch {browse} entry at / reads as Home after a reload, adding no entry', async ({
	page
}) => {
	const guard = new FlowGuard(page);
	const library = readSeededLibrary();
	await watchHistoryWrites(page);
	await page.goto(HOME_PATH);
	await expectHomeShown(page);
	await ageEntryToBrowseAtHome(page, null);
	const length = await historyLength(page);

	await page.reload();

	await expectHomeShown(page);
	expect(await historyLength(page)).toBe(length);
	expect(await addressesWrittenToHistory(page)).not.toContain(LIBRARY_PATH);
	await expectOpenCollectionNamedByMiniPlayer(page, library.albumTitle, false);
	guard.assertClean();
});

test('1354_37a_A2 1354_R1prime row 10b: a pre-switch {browse} entry at / reached by Back from an album reads as Home, never /library', async ({
	page
}, testInfo) => {
	const guard = new FlowGuard(page);
	const shell = shellOf(testInfo);
	const library = readSeededLibrary();
	await watchHistoryWrites(page);
	await page.goto(HOME_PATH);
	await expectHomeShown(page);
	await openAlbumFromHome(page, shell, library.albumTitle);
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

for (const shell of ['desktop', 'mobile'] as const) {
	test(
		`1354_R1prime row 10c: a pre-switch {browse, album} entry at / reads as Home with no album page and the album kept as the open collection (${shell})`,
		{ tag: ONLY_IN_SHELL[shell] },
		async ({ page }) => {
			const guard = new FlowGuard(page);
			const library = readSeededLibrary();
			await watchHistoryWrites(page);
			await page.goto(HOME_PATH);
			await expectHomeShown(page);
			await ageEntryToBrowseAtHome(page, { kind: 'album', id: library.albumId });
			const length = await historyLength(page);

			await page.reload();

			await expectHomeShown(page);
			await expect(workspace(page).getByRole('heading', { name: library.albumTitle })).toHaveCount(
				0
			);
			expect(await historyLength(page)).toBe(length);
			expect(await addressesWrittenToHistory(page)).not.toContain(LIBRARY_PATH);
			await expectOpenCollectionNamedByMiniPlayer(page, library.albumTitle, true);
			if (shell === 'desktop') await expectCurrentRailWord(page, null);
			guard.assertClean();
		}
	);
}

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
		await expectOpenCollectionNamedByMiniPlayer(page, library.albumTitle, true);
		expect(await addressesWrittenToHistory(page)).not.toContain(LIBRARY_PATH);
		guard.assertClean();
	}
);

test(
	'1354_rule_19 1354_rule_31 R6 row 12: with the network gone Home keeps its rows and the word Library still opens the wall',
	{ tag: ONLY_IN_SHELL.desktop },
	async ({ page, context }) => {
		const guard = new FlowGuard(page, { losesNetworkOnPurpose: true });
		await page.goto(HOME_PATH);
		await expectHomeShown(page);
		await expect(listenRegion(page).getByRole('status')).toHaveCount(0);
		const rows = await listenRegion(page).locator('.library-row').count();
		await waitForServiceWorkerControl(page);
		await loseNetwork(page, context);

		await openHome(page, 'desktop');
		await openLibraryWall(page, 'desktop');
		await expectWallShown(page);
		await openHome(page, 'desktop');

		await expect(homeHeading(page)).toBeVisible();
		await expect(listenRegion(page)).toBeVisible();
		await expect(listenRegion(page).locator('.library-row')).toHaveCount(rows);
		await expect(wall(page)).toHaveCount(0);
		await openLibraryWall(page, 'desktop');
		await expectWallShown(page);
		await regainNetwork(page, context);
		guard.assertClean();
	}
);

for (const [row, path, current, retainAlbum] of [
	['1354_rule_31 row 1', HOME_PATH, HOME_PAGE_LABEL, false],
	['1354_rule_31 row 2', LIBRARY_PATH, LIBRARY_PAGE_LABEL, false],
	['1354_R1prime row 10c', HOME_PATH, HOME_PAGE_LABEL, true]
] as const) {
	test(
		`${row}: 1354_61_C07: phone tab follows the address`,
		{ tag: ONLY_IN_SHELL.mobile },
		async ({ page }) => {
			const guard = new FlowGuard(page);
			await page.goto(path);
			if (retainAlbum) {
				await expectHomeShown(page);
				await ageEntryToBrowseAtHome(page, { kind: 'album', id: readSeededLibrary().albumId });
				await page.reload();
			}
			if (path === HOME_PATH) await expectHomeShown(page);
			else await expectWallShown(page);
			await expectCurrentRailWord(page, current, 'mobile');
			guard.assertClean();
		}
	);
}
