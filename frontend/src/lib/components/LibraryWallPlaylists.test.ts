import { replaceHistoryEntry } from '#lib/test-utils/library-history.ts';
import { makeAlbum as album, makePlaylist as playlist } from '#lib/test-utils/factories.ts';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { libraryWallOrder } from '#lib/stores/ui.ts';
import { resetLibraryContextForTests } from '#lib/stores/libraryContext.ts';
import { libraryBrowse, resetLibrarySearchForTests } from '#lib/stores/librarySearch.ts';
import { resetConnectivityForTests } from '#lib/stores/connectivity.ts';
import { albumList, allAlbumsLoad, albumSongsLoad, songList } from '#lib/stores/libraryData.ts';
import { resetLibraryOrderForTests } from '#lib/stores/libraryOrder.ts';
import { playlistList, playlistLoad, resetPlaylistsForTests } from '#lib/stores/playlists.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import {
	setShuffle,
	queueContext,
	pendingStart,
	toggleOrStartCollection
} from '#lib/stores/player.ts';
import {
	LIBRARY_NEW_MENU_LABEL,
	LIBRARY_WALL_ORDER_KEYS,
	type LibraryWallOrder
} from '#lib/constants/library.ts';
import { words } from '#lib/words/en.ts';

const fetchPlaylists = vi.fn();
const fetchPlaylist = vi.fn();
const fetchLibraryListen = vi.fn();
const fetchAlbums = vi.fn();

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('#lib/api/library.ts', () => ({
	fetchLibraryListen: (...args: unknown[]) => fetchLibraryListen(...args)
}));
vi.mock('#lib/api/albums.ts', () => ({ fetchAlbum: vi.fn(), fetchAlbums: vi.fn() }));
vi.mock('#lib/api/songs.ts', () => ({ fetchSong: vi.fn(), fetchSongs: vi.fn() }));
vi.mock('#lib/api/client.ts', () => ({
	fetchPlaylists: (...args: unknown[]) => fetchPlaylists(...args),
	fetchPlaylist: (...args: unknown[]) => fetchPlaylist(...args),
	fetchAlbums: (...args: unknown[]) => fetchAlbums(...args),
	fetchSong: vi.fn(),
	fetchSongs: vi.fn(),
	fetchLastFailedGeneration: vi.fn().mockResolvedValue({ job: null })
}));

import LibraryWall from './LibraryWall.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];
const songs = words['libraryWall.songCount'];
const orderFace = (order: LibraryWallOrder) => words[LIBRARY_WALL_ORDER_KEYS[order]];
const headLabel = (page: 'places.library' | 'places.playlists', count: number) =>
	words['libraryWall.heading']({ page: words[page], count });

beforeEach(() => {
	fetchPlaylists.mockReset().mockResolvedValue([]);
	fetchPlaylist.mockReset().mockResolvedValue({
		...playlist({ id: 'p-local', entry_count: 2, share_slug: null }),
		entries: []
	});
	fetchLibraryListen.mockReset().mockResolvedValue({ items: [] });
	fetchAlbums.mockReset().mockResolvedValue(albumPage([], false));
	localStorage.clear();
	libraryWallOrder.set('title');
	resetLibraryOrderForTests();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
	albumList.set([album({ id: 'a-local', title: 'Local Album' })]);
	playlistList.set([]);
	playlistLoad.set({ status: 'ready', error: null });
	replaceHistoryEntry('/');
});

async function unmountAll(): Promise<void> {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
}

afterEach(async () => {
	await unmountAll();
	const waiting = get(pendingStart);
	if (waiting) toggleOrStartCollection('album', waiting.albumId, null);
	queueContext.set({ type: 'library' });
	setShuffle(false);
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

function orderChoices(root: ParentNode): HTMLButtonElement[] {
	const group = root.querySelector('.wall-titlebar [role="group"]');
	return [...(group?.querySelectorAll('button') ?? [])];
}

function choiceLabel(choice: HTMLButtonElement): string {
	return choice.textContent?.trim() ?? '';
}

function orderButton(root: ParentNode, order: LibraryWallOrder): HTMLButtonElement {
	const button = orderChoices(root).find((choice) => choiceLabel(choice) === orderFace(order));
	if (!button) throw new Error(`no ${order} order`);
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

// Stubs every media query as matching the phone width; the returned function
// turns the viewport to the phone width or away from it and tells the listeners.
function phoneViewport(): (phone: boolean) => void {
	let matches = true;
	const listeners = new Set<() => void>();
	vi.stubGlobal('matchMedia', () => ({
		get matches() {
			return matches;
		},
		addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
		removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener)
	}));
	return (phone) => {
		matches = phone;
		for (const listener of listeners) listener();
	};
}

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

	it('defect:#1529: shows only playlists, A–Z, under one head line reading Playlists · 2 with the sort switch and + New', async () => {
		seedPlaylists();

		const root = await render('playlists');

		expect(tileTitles(root)).toEqual(['Alpha mix', 'Night drive']);
		expect(tileLines(root)).toEqual([songs(1), songs(14)]);
		const head = root.querySelector('.wall-titlebar');
		expect(head?.querySelector('h1')?.getAttribute('aria-label')).toBe(
			headLabel('places.playlists', 2)
		);
		expect(head?.querySelector('[role="group"]')?.getAttribute('aria-label')).toBe(
			words['libraryWall.sortPlaylists']
		);
		expect(head?.querySelector(`[aria-label="${LIBRARY_NEW_MENU_LABEL}"]`)).not.toBeNull();
		expect(pressedOrder(root)).toEqual([orderFace('title')]);
	});

	it('states no count in its head until the playlists have loaded, whichever the library holds meanwhile', async () => {
		let deliver: (items: unknown[]) => void = () => undefined;
		fetchPlaylists.mockReturnValueOnce(new Promise((resolve) => (deliver = resolve)));
		playlistLoad.set({ status: 'idle', error: null });
		const nightDrive = playlist({ id: 'p-night', title: 'Night drive', share_slug: null });
		playlistList.set([nightDrive]);
		const root = await render('playlists');
		const heading = () => root.querySelector('.wall-titlebar h1');

		expect(heading()?.getAttribute('aria-label')).toBe(words['places.playlists']);
		expect(heading()?.textContent?.trim()).toBe(words['places.playlists']);

		deliver([nightDrive, playlist({ id: 'p-alpha', title: 'Alpha mix', share_slug: null })]);

		await vi.waitFor(() =>
			expect(heading()?.getAttribute('aria-label')).toBe(headLabel('places.playlists', 2))
		);
	});

	it('sorts by the one switch the Library uses, which this device remembers for both', async () => {
		seedPlaylists();
		fetchLibraryListen.mockResolvedValue({
			items: [place('playlist', 'p-night', 'Night drive', '2026-09-21T10:00:00Z')]
		});
		const playlists = await render('playlists');

		orderButton(playlists, 'played').click();

		await vi.waitFor(() => expect(tileTitles(playlists)).toEqual(['Night drive', 'Alpha mix']));
		await unmountAll();
		libraryWallOrder.set('title');
		const library = await render('library');
		expect(pressedOrder(library)).toEqual([orderFace('played')]);
	});

	it('1354_rule_9: says so in one line when there is no playlist yet, and still offers New in Library', async () => {
		emptyLibrary();
		const root = await render('playlists');

		expect(root.querySelector('.wall-body .empty')?.textContent).toBe(
			words['libraryWall.playlistsEmpty']({ home: words['places.home'] })
		);
		expect(newButtonOnHead(root)).not.toBeNull();
	});

	it.each([
		{
			failing: 'the albums',
			fail: () =>
				libraryBrowse.update((state) => ({ ...state, status: 'error' as const, error: 'down' })),
			says: words['libraryWall.playlistsEmpty']({ home: words['places.home'] })
		},
		{
			failing: 'the playlists',
			fail: () => playlistLoad.set({ status: 'error', error: 'down' }),
			says: words['libraryWall.playlistsFailed']
		}
	])('answers for its playlists alone when $failing could not load', async ({ fail, says }) => {
		emptyLibrary();
		const root = await render('playlists');

		fail();
		await tick();

		expect(root.querySelector('.wall-body .empty')?.textContent).toBe(says);
	});
});

function newButtonOnHead(root: ParentNode): Element | null {
	return root.querySelector(`.wall-titlebar [aria-label="${LIBRARY_NEW_MENU_LABEL}"]`);
}

function emptyLibrary(): void {
	albumList.set([]);
	playlistList.set([]);
	libraryBrowse.update((state) => ({ ...state, status: 'ready' }));
	allAlbumsLoad.set({ status: 'ready', error: null });
}

describe('1354_rule_14 915_C1 LibraryWall + New head', () => {
	it('1354_rule_9: stands on the Library title line with its plus, even with no album yet, over an empty wall that says so in one line', async () => {
		emptyLibrary();
		playlistList.set([playlist({ id: 'p-road', title: 'Road Trip', share_slug: null })]);
		const root = await render();

		expect(newButtonOnHead(root)?.textContent).toContain('New');
		expect(newButtonOnHead(root)?.querySelector('svg')).not.toBeNull();
		expect(root.querySelector('.wall-body .empty')?.textContent).toBe(
			words['libraryWall.libraryEmpty']({ home: words['places.home'] })
		);
	});

	it.each(['library', 'playlists'] as const)(
		'the desktop %s head carries + New beside the order switch',
		async (kind) => {
			const root = await render(kind);

			expect(newButtonOnHead(root)).not.toBeNull();
			expect(orderChoices(root)).not.toHaveLength(0);
		}
	);

	it.each(['library', 'playlists'] as const)(
		'the phone %s head carries the order switch only, no + New',
		async (kind) => {
			phoneViewport();

			const root = await render(kind);

			expect(orderChoices(root)).not.toHaveLength(0);
			expect(newButtonOnHead(root)).toBeNull();
		}
	);
});
