// + NEW on the Library head makes an album or a playlist from the wall, even
// from an empty library (#1149, #1166, #915 F2a/F2b; pictures N1–N5 in
// docs/design/navigation.html). A card closed with a typed title opens again
// on it (#1184 K2). Escape folds each create card and returns focus, a refused
// create says why in words that fit it, a repeat refusal replaces the toast
// before it, and a long album title leaves the song card's × on screen
// (#1508, #915 E1-E4).
// The empty library is this user's own library answered empty on the wire, so
// the first-album path runs against the seeded stack; creating the album and
// opening its page are real.

import {
	expect,
	test,
	type BrowserContext,
	type Locator,
	type Page,
	type Route
} from '@playwright/test';
import {
	LIBRARY_NEW_ALBUM_LABEL,
	LIBRARY_NEW_MENU_LABEL,
	LIBRARY_NEW_PLAYLIST_LABEL,
	LIBRARY_WALL_EMPTY,
	NEW_ALBUM_CARD_LABEL,
	NEW_ALBUM_CLOSE_LABEL,
	NEW_ALBUM_FAILED,
	NEW_ALBUM_TITLE_LABEL,
	NEW_PLACE_CREATE_LABEL,
	NEW_PLACE_OFFLINE,
	NEW_PLAYLIST_CARD_LABEL,
	NEW_PLAYLIST_CLOSE_LABEL,
	NEW_PLAYLIST_NAME_LABEL,
	NEW_SONG_CLOSE_LABEL,
	NEW_SONG_ROW_LABEL,
	NEW_SONG_TITLE_LABEL,
	newSongCardLabel,
	PLAYLISTS_WALL_EMPTY,
	RAIL_LIBRARY_LABEL,
	RAIL_PLAYLISTS_LABEL,
	RATE_LIMITED_TOAST_MESSAGE
} from '../src/lib/constants';
import {
	boundingBoxes,
	csrfHeaders,
	FlowGuard,
	loseNetwork,
	nameStartingWith,
	ONLY_IN_SHELL,
	openRailNav,
	shellOf,
	workspace,
	HOME_PATH,
	LIBRARY_PATH
} from './helpers';
import { readSeededLibrary, type SeededLibrary } from './seed';

/**
 * Sized before the first CI measurement from the cold wall open (auth, the
 * album and playlist lists, Continue, the live stream) plus one album create
 * and the album page's own loads; the CI log line below is the measurement to
 * tighten it against.
 */
const LIBRARY_CREATE_FLOW_API_REQUEST_BUDGET = 35;

const EMPTY_LIST_ANSWERS: Record<string, unknown> = {
	'/api/albums': { items: [], total: 0, offset: 0, limit: 50, has_more: false },
	'/api/playlists': [],
	'/api/library/listen': { items: [] }
};

const ALBUMS_API = '/api/albums';

const REFUSED_CREATE_TAG = '@refused-create';
const LOSES_NETWORK_TAG = '@loses-network';
// FlowGuard fails a flow on every 5xx and has no way to forgive one, so the
// flow that answers a server error on purpose runs without it.
const ANSWERS_SERVER_ERROR_TAG = '@answers-server-error';

let guard: FlowGuard | undefined;

test.beforeEach(({ page }, testInfo) => {
	guard = testInfo.tags.includes(ANSWERS_SERVER_ERROR_TAG)
		? undefined
		: new FlowGuard(page, {
				refusalsExpectedOn: testInfo.tags.includes(REFUSED_CREATE_TAG)
					? [{ path: ALBUMS_API, statuses: [422, 429] }]
					: [],
				losesNetworkOnPurpose: testInfo.tags.includes(LOSES_NETWORK_TAG)
			});
});

// eslint-disable-next-line no-empty-pattern -- Playwright requires the object-destructuring form even with no fixture named
test.afterEach(({}, testInfo) => {
	if (!guard) return;
	console.log(`Library-create flow /api requests (${testInfo.title}): ${guard.apiRequestCount}`);
	guard.assertClean();
	guard.assertWithinBudget(LIBRARY_CREATE_FLOW_API_REQUEST_BUDGET);
});

async function answerTheLibraryEmpty(page: Page): Promise<void> {
	await page.route(
		(url) => url.pathname in EMPTY_LIST_ANSWERS,
		(route: Route) => {
			const answer = EMPTY_LIST_ANSWERS[new URL(route.request().url()).pathname];
			if (route.request().method() !== 'GET') return route.fallback();
			return route.fulfill({ json: answer });
		}
	);
}

function newButton(page: Page) {
	return workspace(page).getByRole('button', { name: LIBRARY_NEW_MENU_LABEL, exact: true });
}

function newMenu(page: Page) {
	return page.getByRole('dialog', { name: LIBRARY_NEW_MENU_LABEL });
}

test('an empty library makes its first album from + New on the Library head and opens it', async ({
	page
}, testInfo) => {
	const title = `Night Drive ${shellOf(testInfo)} ${Date.now()}`;
	await answerTheLibraryEmpty(page);
	await page.goto(LIBRARY_PATH);

	const wall = workspace(page);
	const libraryTitle = wall.getByRole('heading', { name: 'Library', level: 1 });
	await expect(wall.getByText(LIBRARY_WALL_EMPTY)).toBeVisible();
	await expect(newButton(page)).toBeVisible();
	const [titleBox, newBox] = await boundingBoxes(libraryTitle, newButton(page));
	expect(newBox.y).toBeLessThan(titleBox.y + titleBox.height);
	expect(newBox.y + newBox.height).toBeGreaterThan(titleBox.y);
	expect(newBox.x + newBox.width).toBeLessThanOrEqual(page.viewportSize()?.width ?? 0);

	await newButton(page).click();
	await expect(newMenu(page)).toBeVisible();
	await expect(newButton(page)).toHaveAttribute('aria-expanded', 'true');
	await page.goBack();
	await expect(newMenu(page)).toBeHidden();
	await expect(newButton(page)).toBeFocused();
	await expect(libraryTitle).toBeVisible();

	await newButton(page).click();
	await newMenu(page).getByRole('button', { name: LIBRARY_NEW_ALBUM_LABEL }).click();
	const card = wall.getByRole('form', { name: NEW_ALBUM_CARD_LABEL });
	await expect(card).toBeVisible();
	await card.getByRole('button', { name: NEW_ALBUM_CLOSE_LABEL }).click();
	await expect(card).toBeHidden();

	await newButton(page).click();
	await newMenu(page).getByRole('button', { name: LIBRARY_NEW_ALBUM_LABEL }).click();
	await card.getByLabel(NEW_ALBUM_TITLE_LABEL).fill(title);
	await page.keyboard.press('Escape');
	await expect(card).toBeHidden();

	await newButton(page).click();
	await newMenu(page).getByRole('button', { name: LIBRARY_NEW_ALBUM_LABEL }).click();
	await expect(card.getByLabel(NEW_ALBUM_TITLE_LABEL)).toHaveValue(title);
	await card.getByRole('button', { name: NEW_PLACE_CREATE_LABEL }).click();

	await expect(page).toHaveURL(/\/album\//);
	await expect(workspace(page).getByRole('heading', { name: title })).toBeVisible();
});

test('+ New makes a named playlist from the Library head and opens it', async ({
	page
}, testInfo) => {
	const name = `Road Trip ${shellOf(testInfo)} ${Date.now()}`;
	await page.goto(LIBRARY_PATH);
	const wall = workspace(page);

	await newButton(page).click();
	await newMenu(page).getByRole('button', { name: LIBRARY_NEW_PLAYLIST_LABEL }).click();
	const card = wall.getByRole('form', { name: NEW_PLAYLIST_CARD_LABEL });
	await expect(card).toBeVisible();
	await card.getByRole('button', { name: NEW_PLAYLIST_CLOSE_LABEL }).click();
	await expect(card).toBeHidden();
	await expect(newButton(page)).toBeFocused();

	await newButton(page).click();
	await newMenu(page).getByRole('button', { name: LIBRARY_NEW_PLAYLIST_LABEL }).click();
	await expect(card).toBeVisible();
	await page.goBack();
	await expect(card).toBeHidden();
	await expect(newButton(page)).toBeFocused();

	await newButton(page).click();
	await newMenu(page).getByRole('button', { name: LIBRARY_NEW_PLAYLIST_LABEL }).click();
	await card.getByLabel(NEW_PLAYLIST_NAME_LABEL).fill(name);
	await card.getByRole('button', { name: NEW_PLACE_CREATE_LABEL }).click();

	await expect(page).toHaveURL(/\/playlist\//);
	await expect(workspace(page).getByRole('heading', { name })).toBeVisible();
});

test('#1354 rule 9: an empty account reads one line on the Library and one on Playlists, offers + New on both and keeps both rail groups', async ({
	page
}, testInfo) => {
	await answerTheLibraryEmpty(page);

	for (const { address, line } of [
		{ address: LIBRARY_PATH, line: LIBRARY_WALL_EMPTY },
		{ address: '/playlists', line: PLAYLISTS_WALL_EMPTY }
	]) {
		await page.goto(address);

		await expect(workspace(page).locator('.wall-body .empty')).toHaveText(line);
		await expect(newButton(page)).toBeVisible();
		const rail = await openRailNav(page, shellOf(testInfo));
		for (const group of [RAIL_LIBRARY_LABEL, RAIL_PLAYLISTS_LABEL])
			await expect(rail.getByRole('button', { name: nameStartingWith(group) })).toBeVisible();
	}
});

async function openNewCardFromMenu(page: Page, kindLabel: string): Promise<void> {
	await newButton(page).click();
	await newMenu(page).getByRole('button', { name: kindLabel }).click();
}

function newSongRow(page: Page): Locator {
	return workspace(page).getByRole('button', { name: NEW_SONG_ROW_LABEL, exact: true });
}

interface CreateCard {
	name: string;
	address: (library: SeededLibrary) => string;
	open: (page: Page, library: SeededLibrary) => Promise<void>;
	form: (page: Page, library: SeededLibrary) => Locator;
	titleLabel: string;
	foldsFocusTo: (page: Page) => Locator;
}

const CREATE_CARDS: CreateCard[] = [
	{
		name: 'New album',
		address: () => LIBRARY_PATH,
		open: (page) => openNewCardFromMenu(page, LIBRARY_NEW_ALBUM_LABEL),
		form: (page) => workspace(page).getByRole('form', { name: NEW_ALBUM_CARD_LABEL }),
		titleLabel: NEW_ALBUM_TITLE_LABEL,
		foldsFocusTo: newButton
	},
	{
		name: 'New playlist',
		address: () => LIBRARY_PATH,
		open: (page) => openNewCardFromMenu(page, LIBRARY_NEW_PLAYLIST_LABEL),
		form: (page) => workspace(page).getByRole('form', { name: NEW_PLAYLIST_CARD_LABEL }),
		titleLabel: NEW_PLAYLIST_NAME_LABEL,
		foldsFocusTo: newButton
	},
	{
		name: 'New song',
		address: (library) => `/album/${library.albumId}`,
		open: (page) => newSongRow(page).click(),
		form: (page, library) =>
			workspace(page).getByRole('form', { name: newSongCardLabel(library.albumTitle) }),
		titleLabel: NEW_SONG_TITLE_LABEL,
		foldsFocusTo: newSongRow
	}
];

for (const card of CREATE_CARDS) {
	test(`915_E1 Escape folds the ${card.name} card, returns focus and keeps the title typed`, async ({
		page
	}, testInfo) => {
		const library = readSeededLibrary();
		const draft = `Draft ${shellOf(testInfo)} ${Date.now()}`;
		await page.goto(card.address(library));
		await card.open(page, library);
		await card.form(page, library).getByLabel(card.titleLabel).fill(draft);

		await page.keyboard.press('Escape');

		await expect(card.form(page, library)).toBeHidden();
		await expect(card.foldsFocusTo(page)).toBeFocused();
		await card.open(page, library);
		await expect(card.form(page, library).getByLabel(card.titleLabel)).toHaveValue(draft);
	});
}

const SERVER_REASON = 'That title is already taken.';

function toastMessages(page: Page): Locator {
	return page.locator('.toast-container .toast-message');
}

async function answerAlbumCreates(
	page: Page,
	answer: () => { status: number; detail: string; headers?: Record<string, string> } | null
): Promise<void> {
	await page.route(
		(url) => url.pathname === ALBUMS_API,
		(route: Route) => {
			const refusal = answer();
			if (route.request().method() !== 'POST' || refusal === null) return route.fallback();
			return route.fulfill({
				status: refusal.status,
				headers: refusal.headers,
				json: { detail: refusal.detail }
			});
		}
	);
}

async function typeIntoNewAlbumCard(page: Page, title: string): Promise<Locator> {
	await page.goto(LIBRARY_PATH);
	await openNewCardFromMenu(page, LIBRARY_NEW_ALBUM_LABEL);
	const card = workspace(page).getByRole('form', { name: NEW_ALBUM_CARD_LABEL });
	await card.getByLabel(NEW_ALBUM_TITLE_LABEL).fill(title);
	return card;
}

interface FailedCreate {
	failure: string;
	tag: string;
	arrange: (page: Page, context: BrowserContext) => Promise<void>;
	toast: string;
	/** The app's generic rate-limit notice, which a 429 raises ahead of the card's own message. */
	alsoSaid?: string;
}

const FAILED_CREATES: FailedCreate[] = [
	{
		failure: 'the server refuses it: its reason, no Try again',
		tag: REFUSED_CREATE_TAG,
		arrange: (page) => answerAlbumCreates(page, () => ({ status: 422, detail: SERVER_REASON })),
		toast: SERVER_REASON
	},
	{
		failure: 'the server fails: Try again, without its details',
		tag: ANSWERS_SERVER_ERROR_TAG,
		arrange: (page) =>
			answerAlbumCreates(page, () => ({ status: 500, detail: 'Internal Server Error' })),
		toast: NEW_ALBUM_FAILED
	},
	{
		failure: 'the server rate-limits it: Try again, without its details',
		tag: REFUSED_CREATE_TAG,
		arrange: (page) =>
			answerAlbumCreates(page, () => ({
				status: 429,
				detail: 'Too many requests',
				headers: { 'Retry-After': '30' }
			})),
		toast: NEW_ALBUM_FAILED,
		alsoSaid: RATE_LIMITED_TOAST_MESSAGE
	},
	{
		failure: 'the network is gone: Try again once back online',
		tag: LOSES_NETWORK_TAG,
		arrange: (page, context) => loseNetwork(page, context),
		toast: NEW_PLACE_OFFLINE
	}
];

for (const { failure, tag, arrange, toast, alsoSaid } of FAILED_CREATES) {
	test(
		`915_E2 a create where ${failure}, with the card keeping its title`,
		{ tag },
		async ({ page, context }, testInfo) => {
			const title = `Night Drive ${shellOf(testInfo)} ${Date.now()}`;
			const card = await typeIntoNewAlbumCard(page, title);
			await arrange(page, context);

			await card.getByRole('button', { name: NEW_PLACE_CREATE_LABEL }).click();

			await expect(toastMessages(page)).toHaveText(alsoSaid ? [alsoSaid, toast] : [toast]);
			await expect(card.getByLabel(NEW_ALBUM_TITLE_LABEL)).toHaveValue(title);
			await expect(card.getByRole('button', { name: NEW_PLACE_CREATE_LABEL })).toBeEnabled();
		}
	);
}

async function archiveAlbum(page: Page, albumId: string): Promise<void> {
	const archived = await page.request.post(`${ALBUMS_API}/${albumId}/archive`, {
		headers: await csrfHeaders(page)
	});
	expect(archived.ok()).toBe(true);
}

function albumIdOfAddress(address: string): string {
	return new URL(address).pathname.split('/')[2];
}

test(
	'915_E3 refusals in a row leave one toast, × clears it, and a made album clears the next',
	{ tag: REFUSED_CREATE_TAG },
	async ({ page }, testInfo) => {
		const title = `Night Drive ${shellOf(testInfo)} ${Date.now()}`;
		let refusalReason: string | null = 'First reason';
		await answerAlbumCreates(page, () =>
			refusalReason === null ? null : { status: 422, detail: refusalReason }
		);
		const card = await typeIntoNewAlbumCard(page, title);
		const create = card.getByRole('button', { name: NEW_PLACE_CREATE_LABEL });
		let createdAlbumId: string | undefined;

		try {
			await create.click();
			await expect(toastMessages(page)).toHaveText(['First reason']);

			refusalReason = 'Second reason';
			await create.click();
			await expect(toastMessages(page)).toHaveText(['Second reason']);

			await page.locator('.toast-container').getByRole('button', { name: 'Dismiss' }).click();
			await expect(toastMessages(page)).toHaveCount(0);

			await create.click();
			await expect(toastMessages(page)).toHaveText(['Second reason']);

			refusalReason = null;
			await create.click();
			await expect(page).toHaveURL(/\/album\//);
			createdAlbumId = albumIdOfAddress(page.url());
			await expect(toastMessages(page)).toHaveCount(0);
		} finally {
			if (createdAlbumId) await archiveAlbum(page, createdAlbumId);
		}
	}
);

test(
	'915_E4 a long unbroken album title ends in … on the New song card and leaves × on screen',
	{ tag: ONLY_IN_SHELL.mobile },
	async ({ page }) => {
		const albumTitle = `${'Nightdrive'.repeat(15)}${Date.now()}`;
		await page.goto(HOME_PATH);
		const created = await page.request.post(ALBUMS_API, {
			headers: await csrfHeaders(page),
			data: { title: albumTitle, artist: '' }
		});
		expect(created.ok()).toBe(true);
		const albumId = ((await created.json()) as { id: string }).id;

		try {
			await page.goto(`/album/${albumId}`);
			await newSongRow(page).click();
			const card = workspace(page).getByRole('form', { name: newSongCardLabel(albumTitle) });
			const heading = card.getByText(newSongCardLabel(albumTitle), { exact: true });
			const close = card.getByRole('button', { name: NEW_SONG_CLOSE_LABEL });

			await expect(close).toBeInViewport({ ratio: 1 });
			const [headingBox, closeBox, cardBox] = await boundingBoxes(heading, close, card);
			expect(headingBox.x + headingBox.width).toBeLessThanOrEqual(closeBox.x);
			expect(cardBox.x + cardBox.width).toBeLessThanOrEqual(page.viewportSize()?.width ?? 0);
			const clipping = await heading.evaluate((element) => ({
				overflow: getComputedStyle(element).overflow,
				textOverflow: getComputedStyle(element).textOverflow,
				cutShort: element.scrollWidth > element.clientWidth
			}));
			expect(clipping).toEqual({ overflow: 'hidden', textOverflow: 'ellipsis', cutShort: true });
		} finally {
			await archiveAlbum(page, albumId);
		}
	}
);
