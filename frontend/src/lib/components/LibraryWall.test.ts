import {
	describeBackClosesOverlay,
	replaceHistoryEntry,
	standingHistoryEntry
} from '$lib/test-utils/library-history';
import {
	makeAlbum as album,
	makePlaylist as playlist,
	makeSong,
	makeGeneration
} from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { libraryBrowse, resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { reportResourceStreamReachable, resetConnectivityForTests } from '$lib/stores/connectivity';
import { openCollection } from '$lib/stores/collection';
import { albumList, allAlbumsLoad, albumSongsLoad, songList } from '$lib/stores/libraryData';
import { libraryWallOrder } from '$lib/stores/ui';
import { resetLibraryOrderForTests } from '$lib/stores/libraryOrder';
import { playlistList, playlistLoad, resetPlaylistsForTests } from '$lib/stores/playlists';
import { toasts } from '$lib/stores/toast';
import { getByRoleButton } from '$lib/test-utils/accessible-name';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import {
	playAlbum,
	queueContext,
	pendingStart,
	playStartNotice,
	stopStartAwaitingNetwork
} from '$lib/stores/player';
import { fetchSong } from '$lib/api/client';
import { ApiError, NetworkError } from '$lib/api/fetch';
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
	stopStartAwaitingNetwork();
	queueContext.set({ type: 'library' });
	audioPlayer.current = null;
	audioPlayer.status = 'idle';
	vi.restoreAllMocks();
	vi.unstubAllGlobals();
	songList.set([]);
	albumSongsLoad.set({});
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

		const root = await render('playlists');

		await vi.waitFor(() => expect(fetchPlaylists).toHaveBeenCalledTimes(1));
		await vi.waitFor(() =>
			expect(root.querySelector('[aria-label="Open playlist Night Drive"]')).not.toBeNull()
		);
	});

	it('#1354 rule 7: shows only albums, A–Z, under one head line reading Library · 3, each line giving the size', async () => {
		seedWall();

		const root = await render();

		expect(orderChoices(root).map(choiceLabel)).toEqual(['A–Z', 'Last played']);
		expect(pressedOrder(root)).toEqual(['A–Z']);
		expect(tileTitles(root)).toEqual(['nachtstrom', 'Sonne für Andrea', 'Sonnenlauf']);
		expect(tileLines(root)).toEqual(['1 song', '5 songs', '7 songs']);
		await vi.waitFor(() =>
			expect(root.querySelector('.wall-titlebar h1')?.getAttribute('aria-label')).toBe(
				'Library · 3'
			)
		);
		expect(root.querySelector('[role="group"]')?.getAttribute('aria-label')).toBe('Sort albums');
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
				expect(tileTitles(root)).toEqual(['Sonne für Andrea', 'nachtstrom', 'Sonnenlauf'])
			);
			expect(fetchLibraryListen).toHaveBeenCalledWith({ offset: 0, limit: 200 });
			expect(pressedOrder(root)).toEqual(['Last played']);
			expect(tileLines(root)).toEqual(['today 05:47', 'Thu 20:31', '20 Sep']);
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
		expect(tileLines(reopened).slice(1)).toEqual(['1 song', '5 songs']);
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

		expect(tileTitles(root)).toHaveLength(3);
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
		const root = await render('playlists');

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
		const root = await render('playlists');

		expect(root.querySelector('.playlist-cover')).not.toBeNull();
		expect(root.querySelector('.playlist-cover img')?.getAttribute('loading')).toBe('lazy');
	});

	it.each([
		{
			wall: 'library' as const,
			tile: 'Open album Local Album',
			opens: { kind: 'album', id: 'a-local' }
		},
		{
			wall: 'playlists' as const,
			tile: 'Open playlist Night Drive',
			opens: { kind: 'playlist', id: 'p-local' }
		}
	])('opens the matching collection from the $wall wall', async ({ wall, tile, opens }) => {
		playlistList.set([playlist({ id: 'p-local', entry_count: 2, share_slug: null })]);
		const root = await render(wall);

		root.querySelector<HTMLButtonElement>(`[aria-label="${tile}"]`)?.click();
		await tick();

		expect(get(openCollection)).toEqual(opens);
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

	it('states no count in its head until the playlists have loaded, whichever the library holds meanwhile', async () => {
		let deliver: (items: unknown[]) => void = () => undefined;
		fetchPlaylists.mockReturnValueOnce(new Promise((resolve) => (deliver = resolve)));
		playlistLoad.set({ status: 'idle', error: null });
		const nightDrive = playlist({ id: 'p-night', title: 'Night drive', share_slug: null });
		playlistList.set([nightDrive]);
		const root = await render('playlists');
		const heading = () => root.querySelector('.wall-titlebar h1');

		expect(heading()?.getAttribute('aria-label')).toBe('Playlists');
		expect(heading()?.textContent?.trim()).toBe('Playlists');

		deliver([nightDrive, playlist({ id: 'p-alpha', title: 'Alpha mix', share_slug: null })]);

		await vi.waitFor(() => expect(heading()?.getAttribute('aria-label')).toBe('Playlists · 2'));
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

	it('#1354 rule 9: says so in one line when there is no playlist yet, and still offers New in Library', async () => {
		emptyLibrary();
		const root = await render('playlists');

		const menu = await openNewMenu(root);

		expect(root.querySelector('.wall-body .empty')?.textContent).toBe(NO_PLAYLISTS);
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
			says: NO_PLAYLISTS
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
const NO_ALBUMS = 'No albums yet. + New makes one.';
const NO_PLAYLISTS = 'No playlists yet. + New makes one.';

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
	it('#1354 rule 9: stands on the Library title line with its plus, even with no album yet, over an empty wall that says so in one line', async () => {
		emptyLibrary();
		playlistList.set([playlist({ id: 'p-road', title: 'Road Trip', share_slug: null })]);
		const root = await render();

		expect(newButton(root).textContent).toContain('New');
		expect(newButton(root).querySelector('svg')).not.toBeNull();
		expect(root.querySelector('.wall-body .empty')?.textContent).toBe(NO_ALBUMS);
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

	it('#1354 rule 7: Playlist makes a named playlist there and opens it, leaving the album wall as it was', async () => {
		const root = await render();
		const card = await chooseNew(root, NEW_PLAYLIST);

		await fillAndCreate(card, 'Road Trip');
		await vi.waitFor(() => expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p-road' }));

		expect(createPlaylist).toHaveBeenCalledWith('Road Trip');
		expect(newCard(root, NEW_PLAYLIST)).toBeNull();
		expect(tileTitles(root)).toEqual(['Local Album']);
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

function phoneViewport(): void {
	vi.stubGlobal('matchMedia', () => ({
		matches: true,
		addEventListener: () => undefined,
		removeEventListener: () => undefined
	}));
}

it.each([
	{ label: 'unloaded playable', flag: true, loaded: false, archived: false, expected: true },
	{ label: 'unloaded archived-only', flag: false, loaded: false, archived: true, expected: false },
	{
		label: 'loaded archived-only overrides stale flag',
		flag: true,
		loaded: true,
		archived: true,
		expected: false
	},
	{
		label: 'unpicked playable overrides stale flag',
		flag: false,
		loaded: true,
		archived: false,
		expected: true
	}
])(
	'1354_rule_11: $label uses the playability owner',
	async ({ flag, loaded, archived, expected }) => {
		phoneViewport();
		albumList.set([album({ id: 'proof', title: 'Proof', has_playable_take: flag })]);
		if (loaded) {
			songList.set([
				makeSong({
					album_id: 'proof',
					generations: [makeGeneration({ is_archived: archived, is_picked: false })]
				})
			]);
			albumSongsLoad.set({ proof: 'idle' });
		}
		const root = await render();
		expect(root.querySelector('[aria-label="Play Proof"]') !== null).toBe(expected);
		expect(root.querySelector('.tile-subtitle')).toHaveTextContent('1 song');
	}
);

it.each(['library', 'playlists'] as const)(
	'1354_rule_13: phone %s keeps counts under both orders',
	async (kind) => {
		phoneViewport();
		seedWall();
		const root = await render(kind);
		const counts = tileLines(root);
		fetchLibraryListen.mockResolvedValue({
			items: [
				place(
					kind === 'library' ? 'album' : 'playlist',
					kind === 'library' ? 'a-sonne' : 'p-night',
					'Recently played',
					new Date().toISOString()
				)
			]
		});
		orderButton(root, 'Last played').click();
		await tick();
		await vi.waitFor(() =>
			expect(tileTitles(root)[0]).toBe(kind === 'library' ? 'Sonnenlauf' : 'Night drive')
		);
		expect(tileLines(root).toSorted()).toEqual(counts.toSorted());
		if (kind === 'playlists') expect(root.querySelector('.row-play')).toBeNull();
	}
);

it('1354_rule_10: opening album B keeps the mark and Pause on queue source A', async () => {
	phoneViewport();
	albumList.set([
		album({ id: 'a', title: 'Album A', has_playable_take: true }),
		album({ id: 'b', title: 'Album B', has_playable_take: true })
	]);
	queueContext.set({ type: 'album', albumId: 'a' });
	audioPlayer.current = {
		generation: makeGeneration(),
		songId: 's',
		songTitle: 'Song',
		artist: 'Artist',
		albumTitle: 'Album A',
		lyrics: null
	};
	audioPlayer.status = 'playing';
	const root = await render();
	getByRoleButton(root, 'Open album Album B').click();
	await tick();
	expect(get(openCollection)).toMatchObject({ kind: 'album', id: 'b' });
	expect(root.querySelector('[aria-label="Pause Album A"]')).not.toBeNull();
	expect(root.querySelector('[aria-label="Play Album B"]')).not.toBeNull();
	const marks = root.querySelectorAll('[role="img"][aria-label="Playing"]');
	expect(marks).toHaveLength(1);
	expect(marks[0].closest('.library-row')).toHaveTextContent('Album A');
});

it('1354_rule_10: the row withdraws an album start waiting for the network', async () => {
	phoneViewport();
	albumList.set([album({ id: 'waiting', title: 'Waiting', has_playable_take: true })]);
	songList.set([
		makeSong({ id: 'waiting-song', album_id: 'waiting', generations: [], generation_count: 1 })
	]);
	reportResourceStreamReachable(false);
	vi.mocked(fetchSong).mockRejectedValue(
		new NetworkError('/api/songs/waiting-song', new TypeError('Failed to fetch'))
	);
	await playAlbum('waiting');
	expect(get(playStartNotice)).toBe('awaiting-network');
	const root = await render();
	const control = root.querySelector<HTMLButtonElement>('.row-play');
	if (!control) throw new Error('Expected the waiting album transport');
	control.click();
	await tick();
	expect(get(pendingStart)).toBeNull();
	expect(get(playStartNotice)).toBe('idle');
	expect(root.querySelector('.row-play')).toHaveAccessibleName('Play Waiting');
});
