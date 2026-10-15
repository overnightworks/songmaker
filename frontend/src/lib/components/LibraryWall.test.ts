import {
	describeBackClosesOverlay,
	replaceHistoryEntry,
	standingHistoryEntry
} from '$lib/test-utils/library-history';
import { makeAlbum as album, makePlaylist as playlist } from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { libraryBrowse, resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { reportResourceStreamReachable, resetConnectivityForTests } from '$lib/stores/connectivity';
import { openCollection } from '$lib/stores/collection';
import { albumList, allAlbumsLoad } from '$lib/stores/libraryData';
import { libraryWallOrder } from '$lib/stores/ui';
import { resetLibraryOrderForTests } from '$lib/stores/libraryOrder';
import { playlistList, playlistLoad, resetPlaylistsForTests } from '$lib/stores/playlists';
import { toasts } from '$lib/stores/toast';
import { ApiError } from '$lib/api/fetch';
import { LIBRARY_WALL_PLAYED_PAGE_SIZE } from '$lib/constants';

const fetchPlaylists = vi.fn();
const fetchPlaylist = vi.fn();
const fetchLibraryListen = vi.fn();
const fetchAlbums = vi.fn();
const createAlbum = vi.fn();
const createPlaylist = vi.fn();

vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('$lib/api/library', () => ({
	fetchLibraryListen: (...args: unknown[]) => fetchLibraryListen(...args)
}));
vi.mock('$lib/api/albums', () => ({ fetchAlbum: vi.fn(), fetchAlbums: vi.fn() }));
vi.mock('$lib/api/songs', () => ({ fetchSong: vi.fn(), fetchSongs: vi.fn() }));
vi.mock('$lib/api/client', () => ({
	fetchPlaylists: (...args: unknown[]) => fetchPlaylists(...args),
	fetchPlaylist: (...args: unknown[]) => fetchPlaylist(...args),
	fetchAlbums: (...args: unknown[]) => fetchAlbums(...args),
	createAlbum: (...args: unknown[]) => createAlbum(...args),
	createPlaylist: (...args: unknown[]) => createPlaylist(...args),
	fetchSong: vi.fn(),
	fetchSongs: vi.fn(),
	fetchLastFailedGeneration: vi.fn().mockResolvedValue({ job: null })
}));

import LibraryWall from './LibraryWall.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
	fetchPlaylists.mockReset().mockResolvedValue([]);
	fetchPlaylist.mockReset().mockResolvedValue({
		...playlist({ id: 'p-local', entry_count: 2, share_slug: null }),
		entries: []
	});
	fetchLibraryListen.mockReset().mockResolvedValue({ items: [] });
	fetchAlbums.mockReset().mockResolvedValue(albumPage([], false));
	createAlbum.mockReset().mockResolvedValue(album({ id: 'a-night', title: 'Night Drive' }));
	createPlaylist
		.mockReset()
		.mockResolvedValue(playlist({ id: 'p-road', title: 'Road Trip', share_slug: null }));
	localStorage.clear();
	libraryWallOrder.set('title');
	resetLibraryOrderForTests();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
	albumList.set([album({ id: 'a-local', title: 'Local Album' })]);
	playlistList.set([]);
	playlistLoad.set({ status: 'ready', error: null });
	toasts.set([]);
	replaceHistoryEntry('/');
});

async function unmountAll(): Promise<void> {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
}

afterEach(async () => {
	await unmountAll();
	Reflect.deleteProperty(document, 'visibilityState');
	resetConnectivityForTests();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
	allAlbumsLoad.set({ status: 'idle', error: null });
});

function albumPage(items: ReturnType<typeof album>[], hasMore: boolean) {
	return { items, total: items.length, offset: 0, limit: 50, has_more: hasMore };
}

function returnToForeground(): void {
	Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
	document.dispatchEvent(new Event('visibilitychange'));
}

function reconnect(): void {
	reportResourceStreamReachable(false);
	reportResourceStreamReachable(true);
}

async function render(kind: 'library' | 'playlists' = 'library'): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(LibraryWall, { target, props: { kind } }));
	await tick();
	return target;
}

function tileTitles(root: ParentNode): string[] {
	return [...root.querySelectorAll('.wall-tile .tile-title')].map(
		(title) => title.textContent ?? ''
	);
}

function tileLines(root: ParentNode): string[] {
	return [...root.querySelectorAll('.wall-tile .tile-subtitle')].map(
		(line) => line.textContent ?? ''
	);
}

function continueTitles(root: ParentNode): string[] {
	return [...root.querySelectorAll('.continue-item .tile-title')].map(
		(title) => title.textContent ?? ''
	);
}

function orderChoices(root: ParentNode): HTMLButtonElement[] {
	const group = root.querySelector('[role="group"][aria-label^="Sort "]');
	return [...(group?.querySelectorAll('button') ?? [])];
}

function choiceLabel(choice: HTMLButtonElement): string {
	return choice.textContent?.trim() ?? '';
}

function orderButton(root: ParentNode, label: string): HTMLButtonElement {
	const button = orderChoices(root).find((choice) => choiceLabel(choice) === label);
	if (!button) throw new Error(`no ${label} order`);
	return button;
}

function pressedOrder(root: ParentNode): string[] {
	return orderChoices(root)
		.filter((choice) => choice.getAttribute('aria-pressed') === 'true')
		.map(choiceLabel);
}

function place(type: 'album' | 'playlist', id: string, title: string, playedAt: string) {
	return {
		type,
		id,
		title,
		cover: null,
		album_covers: [],
		song_id: null,
		song_title: null,
		song_number: null,
		played_at: playedAt
	};
}

type ListenPage = { offset: number; limit: number };

function isLastPlayedRead(page: ListenPage): boolean {
	return page.limit === LIBRARY_WALL_PLAYED_PAGE_SIZE;
}

function seedWall(): void {
	albumList.set([
		album({ id: 'a-sonne', title: 'Sonnenlauf', song_count: 7 }),
		album({ id: 'a-fuer', title: 'Sonne für Andrea', song_count: 5 }),
		album({ id: 'a-nacht', title: 'nachtstrom', song_count: 1 })
	]);
	playlistList.set([
		playlist({ id: 'p-night', title: 'Night drive', entry_count: 14, share_slug: null })
	]);
}

describe('LibraryWall', () => {
	it('loads playlists when the wall mounts', async () => {
		playlistLoad.set({ status: 'idle', error: null });
		fetchPlaylists.mockResolvedValueOnce([
			playlist({ id: 'p-local', entry_count: 2, share_slug: null })
		]);

		const root = await render();

		await vi.waitFor(() => expect(fetchPlaylists).toHaveBeenCalledTimes(1));
		await vi.waitFor(() =>
			expect(root.querySelector('[aria-label="Open playlist Night Drive"]')).not.toBeNull()
		);
	});

	it('opens in A–Z, the switch offering only A–Z and Last played: albums and playlists together by title, each line giving the size', async () => {
		seedWall();

		const root = await render();

		expect(orderChoices(root).map(choiceLabel)).toEqual(['A–Z', 'Last played']);
		expect(pressedOrder(root)).toEqual(['A–Z']);
		expect(tileTitles(root)).toEqual([
			'nachtstrom',
			'Night drive',
			'Sonne für Andrea',
			'Sonnenlauf'
		]);
		expect(tileLines(root)).toEqual(['1 song', 'Playlist · 14 songs', '5 songs', '7 songs']);
	});

	describe('with the clock on a Sunday noon in Berlin', () => {
		beforeEach(() => {
			vi.stubEnv('TZ', 'Europe/Berlin');
			vi.useFakeTimers({ toFake: ['Date'] });
			vi.setSystemTime(new Date('2026-09-27T10:00:00Z'));
		});

		afterEach(() => {
			vi.useRealTimers();
			vi.unstubAllEnvs();
		});

		it('orders Last played by the listens Continue reads and names the last listen, never re-sorting Continue', async () => {
			seedWall();
			const continueRow = [place('album', 'a-nacht', 'nachtstrom', '2026-09-27T03:47:00Z')];
			const everyPlace = [
				place('album', 'a-fuer', 'Sonne für Andrea', '2026-09-27T03:47:00Z'),
				place('playlist', 'p-night', 'Night drive', '2026-09-26T21:40:00Z'),
				place('album', 'a-nacht', 'nachtstrom', '2026-09-24T18:31:00Z'),
				place('album', 'a-sonne', 'Sonnenlauf', '2026-09-20T10:00:00Z')
			];
			fetchLibraryListen.mockImplementation((page: ListenPage) =>
				Promise.resolve({ items: isLastPlayedRead(page) ? everyPlace : continueRow })
			);
			const root = await render();
			await vi.waitFor(() => expect(continueTitles(root)).toEqual(['nachtstrom']));

			orderButton(root, 'Last played').click();

			await vi.waitFor(() =>
				expect(tileTitles(root)).toEqual([
					'Sonne für Andrea',
					'Night drive',
					'nachtstrom',
					'Sonnenlauf'
				])
			);
			expect(fetchLibraryListen).toHaveBeenCalledWith({ offset: 0, limit: 200 });
			expect(pressedOrder(root)).toEqual(['Last played']);
			expect(tileLines(root)).toEqual([
				'today 05:47',
				'Playlist · yesterday 23:40',
				'Thu 20:31',
				'20 Sep'
			]);
			expect(continueTitles(root)).toEqual(['nachtstrom']);
		});

		it('orders Last played by the listens of every place and names its last listen, past one page of them', async () => {
			const titles = Array.from(
				{ length: 209 },
				(_, index) => `Album ${String(index).padStart(3, '0')}`
			);
			albumList.set(titles.map((title) => album({ id: title, title, song_count: 0 })));
			const byActivity = titles
				.toReversed()
				.map((title) => place('album', title, title, '2026-09-27T03:47:00Z'));
			fetchLibraryListen.mockImplementation((page: ListenPage) =>
				Promise.resolve({
					items: isLastPlayedRead(page)
						? byActivity.slice(page.offset, page.offset + page.limit)
						: []
				})
			);
			const root = await render();

			orderButton(root, 'Last played').click();

			await vi.waitFor(() => expect(tileTitles(root)).toEqual(titles.toReversed()));
			expect(new Set(tileLines(root))).toEqual(new Set(['today 05:47']));
		});
	});

	it('opens in the order last chosen on this device', async () => {
		seedWall();
		fetchLibraryListen.mockResolvedValue({
			items: [place('album', 'a-sonne', 'Sonnenlauf', '2026-09-21T10:00:00Z')]
		});
		const first = await render();
		orderButton(first, 'Last played').click();
		await unmountAll();
		libraryWallOrder.set('title');

		const reopened = await render();

		expect(pressedOrder(reopened)).toEqual(['Last played']);
		await vi.waitFor(() => expect(tileTitles(reopened)[0]).toBe('Sonnenlauf'));
		expect(tileLines(reopened).slice(1)).toEqual(['1 song', 'Playlist · 14 songs', '5 songs']);
	});

	it.each([
		[
			'a browse reload',
			() =>
				libraryBrowse.update((state) => ({ ...state, status: 'error' as const, error: 'offline' }))
		],
		['a playlist reload', () => playlistLoad.set({ status: 'error', error: 'offline' })]
	])('keeps the tiles on screen and names no failure when %s fails', async (_, failReload) => {
		seedWall();
		const root = await render();

		failReload();
		await tick();

		expect(tileTitles(root)).toHaveLength(4);
		expect(root.querySelector('[role="alert"]')).toBeNull();
	});

	it('keeps the last-played ranking when a later read fails and reads again on the foreground and on reconnect', async () => {
		seedWall();
		const rankedBy = (album: string) =>
			Promise.resolve({ items: [place('album', album, album, '2026-09-21T10:00:00Z')] });
		fetchLibraryListen.mockImplementation(() => rankedBy('a-sonne'));
		const root = await render();
		orderButton(root, 'Last played').click();
		await vi.waitFor(() => expect(tileTitles(root)[0]).toBe('Sonnenlauf'));

		const failedRead = Promise.reject(new Error('offline'));
		failedRead.catch(() => undefined);
		fetchLibraryListen.mockImplementation(() => failedRead);
		returnToForeground();
		await failedRead.catch(() => undefined);
		await tick();

		expect(tileTitles(root)[0]).toBe('Sonnenlauf');
		expect(root.querySelector('[role="alert"]')).toBeNull();

		fetchLibraryListen.mockImplementation(() => rankedBy('a-nacht'));
		reconnect();
		await vi.waitFor(() => expect(tileTitles(root)[0]).toBe('nachtstrom'));
	});

	it('reads the albums it could not load again once the network is back', async () => {
		seedWall();
		fetchAlbums.mockRejectedValueOnce(new Error('offline'));
		const root = await render();
		await vi.waitFor(() => expect(get(allAlbumsLoad).status).toBe('error'));
		expect(root.querySelector('[role="alert"]')).toBeNull();

		fetchAlbums.mockResolvedValueOnce(albumPage([album({ id: 'a-arger', title: 'Ärger' })], false));
		reconnect();

		await vi.waitFor(() => expect(tileTitles(root)[0]).toBe('Ärger'));
	});

	it('sorts the complete set, reading every album page before ordering the wall', async () => {
		seedWall();
		fetchAlbums
			.mockResolvedValueOnce(albumPage(get(albumList), true))
			.mockResolvedValueOnce(albumPage([album({ id: 'a-arger', title: 'Ärger' })], false));

		const root = await render();

		await vi.waitFor(() => expect(tileTitles(root)[0]).toBe('Ärger'));
		expect(root.querySelector('.load-more')).toBeNull();
	});

	it('uses a playlist cover before its album-cover mosaic', async () => {
		playlistList.set([
			playlist({
				id: 'p-local',
				entry_count: 2,
				share_slug: null,
				cover: { card: '/covers/night-drive.jpg', detail: '/covers/night-drive.jpg' },
				album_covers: [{ card: '/covers/album.jpg', detail: '/covers/album.jpg' }]
			})
		]);
		const root = await render();

		expect(
			root.querySelector<HTMLImageElement>('img[alt="Playlist cover for Night Drive"]')?.src
		).toContain('/covers/night-drive.jpg');
		expect(root.querySelector('.playlist-cover')).toBeNull();
	});

	it('uses the 6B playlist mosaic when a playlist has no own cover', async () => {
		playlistList.set([
			playlist({
				id: 'p-local',
				entry_count: 2,
				share_slug: null,
				album_covers: [{ card: '/covers/album.jpg', detail: '/covers/album.jpg' }]
			})
		]);
		const root = await render();

		expect(root.querySelector('.playlist-cover')).not.toBeNull();
		expect(root.querySelector('.playlist-cover img')?.getAttribute('loading')).toBe('lazy');
	});

	it('opens the matching collection through the navigation store', async () => {
		playlistList.set([playlist({ id: 'p-local', entry_count: 2, share_slug: null })]);
		const root = await render();
		const albumTile = root.querySelector<HTMLButtonElement>(
			'[aria-label="Open album Local Album"]'
		);
		const playlistTile = root.querySelector<HTMLButtonElement>(
			'[aria-label="Open playlist Night Drive"]'
		);

		albumTile?.click();
		await tick();
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a-local' });

		playlistTile?.click();
		await tick();
		expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p-local' });
	});
});

// #1402, frame D3: the Playlists page shows the same wall of covers for
// playlists alone, under one head line.
describe('the Playlists page wall', () => {
	function seedPlaylists(): void {
		seedWall();
		playlistList.update((list) => [
			...list,
			playlist({ id: 'p-alpha', title: 'Alpha mix', entry_count: 1, share_slug: null })
		]);
	}

	it('shows only playlists, A–Z, under one head line reading Playlists · 2 with the sort switch and + New', async () => {
		seedPlaylists();

		const root = await render('playlists');

		expect(tileTitles(root)).toEqual(['Alpha mix', 'Night drive']);
		expect(tileLines(root)).toEqual(['1 song', '14 songs']);
		const head = root.querySelector('.wall-titlebar');
		expect(head?.querySelector('h1')?.getAttribute('aria-label')).toBe('Playlists · 2');
		expect(head?.querySelector('[role="group"]')?.getAttribute('aria-label')).toBe(
			'Sort playlists'
		);
		expect(head?.querySelector(`[aria-label="${NEW_LABEL}"]`)).not.toBeNull();
		expect(pressedOrder(root)).toEqual(['A–Z']);
	});

	it('sorts by the one switch the Library uses, which this device remembers for both', async () => {
		seedPlaylists();
		fetchLibraryListen.mockResolvedValue({
			items: [place('playlist', 'p-night', 'Night drive', '2026-09-21T10:00:00Z')]
		});
		const playlists = await render('playlists');

		orderButton(playlists, 'Last played').click();

		await vi.waitFor(() => expect(tileTitles(playlists)).toEqual(['Night drive', 'Alpha mix']));
		await unmountAll();
		libraryWallOrder.set('title');
		const library = await render('library');
		expect(pressedOrder(library)).toEqual(['Last played']);
	});

	it('says so when there is no playlist yet, and still offers New in Library', async () => {
		emptyLibrary();
		const root = await render('playlists');

		const menu = await openNewMenu(root);

		expect(root.querySelector('.wall-body')?.textContent).toContain('No playlists yet.');
		expect([...menu.querySelectorAll('button')].map((item) => item.textContent?.trim())).toEqual([
			'Album',
			'Playlist'
		]);
	});

	it.each([
		{
			failing: 'the albums',
			fail: () =>
				libraryBrowse.update((state) => ({ ...state, status: 'error' as const, error: 'down' })),
			says: 'No playlists yet.'
		},
		{
			failing: 'the playlists',
			fail: () => playlistLoad.set({ status: 'error', error: 'down' }),
			says: 'Failed to load playlists'
		}
	])('answers for its playlists alone when $failing could not load', async ({ fail, says }) => {
		emptyLibrary();
		const root = await render('playlists');

		fail();
		await tick();

		expect(root.querySelector('.wall-body .empty')?.textContent).toBe(says);
	});
});

const NEW_LABEL = 'New album or playlist';

type NewKind = { choice: 'Album' | 'Playlist'; card: string; close: string; field: string };

const NEW_ALBUM: NewKind = {
	choice: 'Album',
	card: 'New album',
	close: 'Close new album',
	field: 'Title'
};
const NEW_PLAYLIST: NewKind = {
	choice: 'Playlist',
	card: 'New playlist',
	close: 'Close new playlist',
	field: 'Name'
};

function newButton(root: ParentNode): HTMLButtonElement {
	const button = root.querySelector<HTMLButtonElement>(
		`.wall-titlebar [aria-label="${NEW_LABEL}"]`
	);
	if (!button) throw new Error('no + New on the Library title line');
	return button;
}

function newMenu(): HTMLElement | null {
	return document.querySelector<HTMLElement>(`[role="dialog"][aria-label="${NEW_LABEL}"]`);
}

function newCard(root: ParentNode, kind: NewKind): HTMLElement | null {
	return root.querySelector<HTMLElement>(`.wall-body [aria-label="${kind.card}"]`);
}

async function openNewMenu(root: HTMLElement): Promise<HTMLElement> {
	newButton(root).click();
	await tick();
	await tick();
	const menu = newMenu();
	if (!menu) throw new Error('+ New opened no menu');
	return menu;
}

async function chooseNew(root: HTMLElement, kind: NewKind): Promise<HTMLElement> {
	const menu = await openNewMenu(root);
	[...menu.querySelectorAll('button')]
		.find((item) => item.textContent?.trim() === kind.choice)
		?.click();
	await tick();
	const card = newCard(root, kind);
	if (!card) throw new Error(`${kind.choice} unfolded no card`);
	return card;
}

async function fillAndCreate(card: HTMLElement, value: string): Promise<void> {
	const input = card.querySelector<HTMLInputElement>('input');
	if (!input) throw new Error('no first field');
	input.value = value;
	input.dispatchEvent(new Event('input', { bubbles: true }));
	await tick();
	card.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
}

function emptyLibrary(): void {
	albumList.set([]);
	playlistList.set([]);
	libraryBrowse.update((state) => ({ ...state, status: 'ready' }));
	allAlbumsLoad.set({ status: 'ready', error: null });
}

describe('LibraryWall + New', () => {
	it('stands on the Library title line with its plus, even with no album yet, over an empty wall that says so', async () => {
		emptyLibrary();
		const root = await render();

		expect(newButton(root).textContent).toContain('New');
		expect(newButton(root).querySelector('svg')).not.toBeNull();
		expect(root.querySelector('.wall-body')?.textContent).toContain('No albums yet.');
	});

	it('opens New in Library offering Album and Playlist, each with its icon', async () => {
		const root = await render();

		const menu = await openNewMenu(root);

		expect(newButton(root).getAttribute('aria-expanded')).toBe('true');
		expect(menu.textContent).toContain('New in Library');
		const items = [...menu.querySelectorAll('button')];
		expect(items.map((item) => item.textContent?.trim())).toEqual(['Album', 'Playlist']);
		expect(items.every((item) => item.querySelector('svg') !== null)).toBe(true);
	});

	it.each([NEW_ALBUM, NEW_PLAYLIST])(
		'$choice closes the menu and unfolds its card at the top of the wall, + New pressed meanwhile',
		async (kind) => {
			const root = await render();

			const card = await chooseNew(root, kind);

			expect(newMenu()).toBeNull();
			expect(root.querySelector('.wall-body')?.firstElementChild).toBe(card);
			expect(document.activeElement?.closest('label')?.textContent).toContain(kind.field);
			expect(newButton(root).classList.contains('pressed')).toBe(true);
			expect(tileTitles(root)).toEqual(['Local Album']);
		}
	);

	it.each([NEW_ALBUM, NEW_PLAYLIST])(
		'× folds the $choice card, creates nothing and hands focus back to + New',
		async (kind) => {
			const root = await render();
			const card = await chooseNew(root, kind);

			card.querySelector<HTMLButtonElement>(`[aria-label="${kind.close}"]`)?.click();
			await vi.waitFor(() => expect(document.activeElement).toBe(newButton(root)));

			expect(newCard(root, kind)).toBeNull();
			expect(newButton(root).classList.contains('pressed')).toBe(false);
			expect(createAlbum).not.toHaveBeenCalled();
			expect(createPlaylist).not.toHaveBeenCalled();
		}
	);

	it('an empty library makes its first album there and opens its page', async () => {
		emptyLibrary();
		const root = await render();
		const card = await chooseNew(root, NEW_ALBUM);

		await fillAndCreate(card, 'Night Drive');
		await vi.waitFor(() => expect(get(openCollection)).toEqual({ kind: 'album', id: 'a-night' }));

		expect(createAlbum).toHaveBeenCalledWith('Night Drive', '');
		expect(newCard(root, NEW_ALBUM)).toBeNull();
	});

	it('Playlist makes a named playlist there and opens it', async () => {
		const root = await render();
		const card = await chooseNew(root, NEW_PLAYLIST);

		await fillAndCreate(card, 'Road Trip');
		await vi.waitFor(() => expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p-road' }));

		expect(createPlaylist).toHaveBeenCalledWith('Road Trip');
		expect(newCard(root, NEW_PLAYLIST)).toBeNull();
		expect(tileTitles(root)).toContain('Road Trip');
	});

	it.each([
		{ kind: NEW_ALBUM, create: () => createAlbum, name: 'Night Drive', opened: 'album' },
		{ kind: NEW_PLAYLIST, create: () => createPlaylist, name: 'Road Trip', opened: 'playlist' }
	])(
		'the $kind.card card leaves no failure on screen once a create succeeds after refused tries',
		async ({ kind, create, name, opened }) => {
			const created = await create()();
			create()
				.mockReset()
				.mockRejectedValueOnce(new ApiError(422, 'Validation error on: body.title', '/api'))
				.mockRejectedValueOnce(new ApiError(500, 'Internal Server Error', '/api'))
				.mockResolvedValue(created);
			const root = await render();
			const card = await chooseNew(root, kind);

			await fillAndCreate(card, name);
			await vi.waitFor(() => expect(get(toasts)).toHaveLength(1));
			card.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
			await vi.waitFor(() => expect(get(toasts)).toHaveLength(2));
			card.querySelector<HTMLButtonElement>('button[type="submit"]')?.click();
			await vi.waitFor(() => expect(get(openCollection)?.kind).toBe(opened));

			expect(get(toasts)).toEqual([]);
		}
	);
});

describeBackClosesOverlay({
	name: 'the New in Library menu',
	render,
	open: async (target) => {
		await openNewMenu(target);
	},
	isShown: () => newMenu() !== null,
	afterBack: () => expect(document.activeElement?.getAttribute('aria-label')).toBe(NEW_LABEL),
	closeWays: []
});

for (const kind of [NEW_ALBUM, NEW_PLAYLIST]) {
	describeBackClosesOverlay({
		name: `the ${kind.card} card`,
		render,
		open: async (target) => {
			await chooseNew(target, kind);
			await vi.waitFor(() => expect(standingHistoryEntry()?.layer).toBe('library-new-card'));
		},
		isShown: (target) => newCard(target, kind) !== null,
		afterBack: () => {
			expect(document.activeElement?.getAttribute('aria-label')).toBe(NEW_LABEL);
			expect(createAlbum).not.toHaveBeenCalled();
			expect(createPlaylist).not.toHaveBeenCalled();
		},
		closeWays: [
			{
				way: '×',
				close: (target) =>
					target.querySelector<HTMLButtonElement>(`[aria-label="${kind.close}"]`)?.click()
			}
		]
	});
}
