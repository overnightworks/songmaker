import { replaceHistoryEntry } from '#lib/test-utils/library-history.ts';
import {
	makeAlbum as album,
	makePlaylist as playlist,
	makeSong,
	makeGeneration
} from '#lib/test-utils/factories.ts';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import {
	applyLibraryHistory,
	cancelLibraryHistoryApply,
	libraryRootState,
	libraryScrollAnchor,
	libraryScrollRestore,
	librarySurface,
	resetLibraryContextForTests,
	setLibrarySurface
} from '#lib/stores/libraryContext.ts';
import { libraryBrowse, resetLibrarySearchForTests } from '#lib/stores/librarySearch.ts';
import {
	reportResourceStreamReachable,
	resetConnectivityForTests
} from '#lib/stores/connectivity.ts';
import { openCollection, setOpenCollection, type OpenCollection } from '#lib/stores/collection.ts';
import {
	albumList,
	allAlbumsLoad,
	albumSongsLoad,
	resetLibraryDataForTests,
	songList
} from '#lib/stores/libraryData.ts';
import { chooseLibraryWallOrder, libraryWallOrder } from '#lib/stores/ui.ts';
import { resetLibraryOrderForTests } from '#lib/stores/libraryOrder.ts';
import { playlistList, playlistLoad, resetPlaylistsForTests } from '#lib/stores/playlists.ts';
import { getByRoleButton } from '#lib/test-utils/accessible-name.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import {
	playAlbum,
	setShuffle,
	shuffleEnabled,
	queueContext,
	pendingStart,
	playStartNotice,
	toggleOrStartCollection
} from '#lib/stores/player.ts';
import { fetchSong } from '#lib/api/client.ts';
import { NetworkError } from '#lib/api/fetch.ts';
import { LIBRARY_NEW_MENU_LABEL, LIBRARY_WALL_PLAYED_PAGE_SIZE } from '#lib/constants.ts';

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

	it('1354_rule_31 1354_rule_14: shows no Listen list, and reads no listens until Last played is chosen', async () => {
		seedWall();

		const root = await render();

		expect(root.querySelector('[aria-label="Listen"]')).toBeNull();
		expect(fetchLibraryListen).not.toHaveBeenCalled();
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

		it('1354_rule_31: orders Last played by the listens of every place and names the last listen', async () => {
			seedWall();
			const everyPlace = [
				place('album', 'a-fuer', 'Sonne für Andrea', '2026-09-27T03:47:00Z'),
				place('playlist', 'p-night', 'Night drive', '2026-09-26T21:40:00Z'),
				place('album', 'a-nacht', 'nachtstrom', '2026-09-24T18:31:00Z'),
				place('album', 'a-sonne', 'Sonnenlauf', '2026-09-20T10:00:00Z')
			];
			fetchLibraryListen.mockResolvedValue({ items: everyPlace });
			const root = await render();

			orderButton(root, 'Last played').click();

			await vi.waitFor(() =>
				expect(tileTitles(root)).toEqual(['Sonne für Andrea', 'nachtstrom', 'Sonnenlauf'])
			);
			expect(fetchLibraryListen).toHaveBeenCalledWith({ offset: 0, limit: 200 });
			expect(pressedOrder(root)).toEqual(['Last played']);
			expect(tileLines(root)).toEqual(['today 05:47', 'Thu 20:31', '20 Sep']);
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

	it.each([
		['library', 'Library', ['Sonnenlauf', 'nachtstrom', 'Sonne für Andrea']],
		['playlists', 'Playlists', ['Night drive']]
	] as const)(
		'1354_rule_8: paints no %s tile, no count and no empty word while Last played is chosen and Listen has not answered',
		async (kind, pageLabel, ranked) => {
			seedWall();
			chooseLibraryWallOrder('played');
			const listen = Promise.withResolvers<{ items: ReturnType<typeof place>[] }>();
			fetchLibraryListen.mockReturnValue(listen.promise);
			const root = await render(kind);
			await vi.waitFor(() =>
				expect((kind === 'library' ? get(allAlbumsLoad) : get(playlistLoad)).status).toBe('ready')
			);

			expect(tileTitles(root)).toEqual([]);
			expect(root.querySelector('[role="status"]')).not.toBeNull();
			expect(root.querySelector('.wall-titlebar h1')?.getAttribute('aria-label')).toBe(pageLabel);

			listen.resolve({ items: [place('album', 'a-sonne', 'Sonnenlauf', '2026-09-21T10:00:00Z')] });

			await vi.waitFor(() => expect(tileTitles(root)).toEqual(ranked));
			expect(root.querySelector('[role="status"]')).toBeNull();
		}
	);

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

	it('defect:#1529: shows only playlists, A–Z, under one head line reading Playlists · 2 with the sort switch and + New', async () => {
		seedPlaylists();

		const root = await render('playlists');

		expect(tileTitles(root)).toEqual(['Alpha mix', 'Night drive']);
		expect(tileLines(root)).toEqual(['1 song', '14 songs']);
		const head = root.querySelector('.wall-titlebar');
		expect(head?.querySelector('h1')?.getAttribute('aria-label')).toBe('Playlists · 2');
		expect(head?.querySelector('[role="group"]')?.getAttribute('aria-label')).toBe(
			'Sort playlists'
		);
		expect(head?.querySelector(`[aria-label="${LIBRARY_NEW_MENU_LABEL}"]`)).not.toBeNull();
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

	it('1354_rule_9: says so in one line when there is no playlist yet, and still offers New in Library', async () => {
		emptyLibrary();
		const root = await render('playlists');

		expect(root.querySelector('.wall-body .empty')?.textContent).toBe(NO_PLAYLISTS);
		expect(newButtonOnHead(root)).not.toBeNull();
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

const NO_ALBUMS = 'No albums yet. + New on Home makes one.';
const NO_PLAYLISTS = 'No playlists yet. + New on Home makes one.';

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
		expect(root.querySelector('.wall-body .empty')?.textContent).toBe(NO_ALBUMS);
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
	vi.mocked(fetchSong).mockRejectedValueOnce(
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

it('1354_rule_43: the phone row starts an album and leaves Shuffle on', async () => {
	phoneViewport();
	albumList.set([album({ id: 'shuffle', title: 'Shuffle', has_playable_take: true })]);
	songList.set([
		makeSong({ id: 'shuffle-song', album_id: 'shuffle', generations: [makeGeneration()] })
	]);
	albumSongsLoad.set({ shuffle: 'idle' });
	setShuffle(true);
	const root = await render();
	getByRoleButton(root, 'Play Shuffle').click();
	await tick();
	expect(get(shuffleEnabled)).toBe(true);
});

function wallBody(root: ParentNode): HTMLElement {
	const body = root.querySelector<HTMLElement>('.wall-body');
	if (!body) throw new Error('Expected the wall body');
	return body;
}

function returnToWallFrom(place: OpenCollection, wall: 'browse' | 'playlists'): void {
	setOpenCollection(place);
	setLibrarySurface('detail');
	setLibrarySurface(wall);
}

function litTitles(root: ParentNode): string[] {
	return [...root.querySelectorAll('.library-row.lit .tile-title')].map(
		(title) => title.textContent ?? ''
	);
}

async function landOnWall(top: number): Promise<void> {
	await applyLibraryHistory({ ...libraryRootState(), scrollAnchor: top }, false);
	await tick();
}

function recordScrollTopWrites(body: HTMLElement, startAt: number) {
	const writes: number[] = [];
	let top = startAt;
	Object.defineProperty(body, 'scrollTop', {
		configurable: true,
		get: () => top,
		set: (next: number) => {
			top = next;
			writes.push(next);
		}
	});
	return {
		writes,
		scrollWithoutInput(next: number): void {
			top = next;
			body.dispatchEvent(new Event('scroll'));
		}
	};
}

function mockContentHeight(scrollHeight: number): void {
	vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(scrollHeight);
}

describe('the wall landing where it was left', () => {
	beforeEach(() => {
		mockContentHeight(2000);
		vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(600);
		fetchAlbums.mockReturnValue(new Promise(() => {}));
		allAlbumsLoad.set({ status: 'loading', error: null });
	});

	afterEach(() => {
		vi.restoreAllMocks();
		resetLibraryDataForTests();
	});

	it('1354_rule_12: lands at the scroll its entry kept', async () => {
		seedWall();
		await landOnWall(480);

		const root = await render();

		expect(wallBody(root).scrollTop).toBe(480);
	});

	it('1354_rule_12: applies a landing to the wall that is already showing', async () => {
		seedWall();
		const root = await render();

		await landOnWall(300);

		expect(wallBody(root).scrollTop).toBe(300);
	});

	it('1354_rule_12: leaves scrollTop alone for a scroll it reported itself', async () => {
		seedWall();
		const root = await render();
		const body = wallBody(root);
		const { writes, scrollWithoutInput } = recordScrollTopWrites(body, 0);

		scrollWithoutInput(500);
		await tick();

		expect(get(libraryScrollAnchor)).toBe(500);
		expect(writes).toEqual([]);
	});

	it('defect:#1354: a grown and re-sorted list while scrolled writes nothing', async () => {
		seedWall();
		const root = await render();
		const body = wallBody(root);
		await landOnWall(480);
		const { writes } = recordScrollTopWrites(body, 900);

		albumList.update((albums) => [
			album({ id: 'a-zuerst', title: 'Aaa zuerst', song_count: 3 }),
			...albums.slice().reverse()
		]);
		await tick();

		expect(writes).toEqual([]);
	});

	it('defect:#1354: a landing at the same position restores again', async () => {
		seedWall();
		const root = await render();
		const body = wallBody(root);
		await landOnWall(480);
		body.scrollTop = 0;

		await landOnWall(480);

		expect(body.scrollTop).toBe(480);
	});

	it.each([
		{
			input: 'a pointer press',
			fire: (body: HTMLElement) => body.dispatchEvent(new Event('pointerdown'))
		},
		{ input: 'a touch', fire: (body: HTMLElement) => body.dispatchEvent(new Event('touchstart')) },
		{ input: 'the wheel', fire: (body: HTMLElement) => body.dispatchEvent(new Event('wheel')) },
		{
			input: 'a scroll key',
			fire: (body: HTMLElement) =>
				body.dispatchEvent(new KeyboardEvent('keydown', { key: 'PageDown' }))
		}
	])('defect:#1354: $input drops a landing that waits for the content', async ({ fire }) => {
		mockContentHeight(600);
		seedWall();
		const root = await render();
		const body = wallBody(root);
		await landOnWall(480);

		fire(body);
		mockContentHeight(2000);
		albumList.update((albums) => [
			...albums,
			album({ id: 'a-more', title: 'Mehr', song_count: 2 })
		]);
		await tick();

		expect(body.scrollTop).toBe(0);
		expect(get(libraryScrollAnchor)).toBe(0);
	});

	it('defect:#1354: a clamp or programmatic scroll leaves a waiting landing in place', async () => {
		mockContentHeight(800);
		seedWall();
		const root = await render();
		const body = wallBody(root);
		await landOnWall(480);
		const { scrollWithoutInput } = recordScrollTopWrites(body, 0);

		scrollWithoutInput(200);
		mockContentHeight(2000);
		albumList.update((albums) => [
			...albums,
			album({ id: 'a-more', title: 'Mehr', song_count: 2 })
		]);
		await tick();

		expect(body.scrollTop).toBe(480);
	});

	it('defect:#1354: a landing on a detail page issues no request for a wall', async () => {
		await applyLibraryHistory(
			{
				...libraryRootState(),
				surface: 'detail',
				collection: { kind: 'album', id: 'a-local' },
				scrollAnchor: 480
			},
			false
		);

		expect(get(librarySurface)).toBe('detail');
		expect(get(libraryScrollRestore)).toBeNull();
	});

	it('defect:#1354: the Playlists wall opened from a detail entry starts at its own anchor', async () => {
		await applyLibraryHistory(
			{
				...libraryRootState(),
				surface: 'detail',
				collection: { kind: 'album', id: 'a-local' },
				scrollAnchor: 800
			},
			false
		);
		await applyLibraryHistory(
			{ ...libraryRootState(), surface: 'playlists', scrollAnchor: 0 },
			false
		);

		const root = await render('playlists');

		expect(wallBody(root).scrollTop).toBe(0);
	});

	it.each([
		{ clear: 'a cancelled apply', fire: () => cancelLibraryHistoryApply() },
		{ clear: 'a navigation', fire: () => setLibrarySurface('playlists') }
	])(
		'1354_rule_12: $clear while the wall waits leaves wall and anchor agreeing',
		async ({ fire }) => {
			mockContentHeight(600);
			seedWall();
			const root = await render();
			const body = wallBody(root);
			await landOnWall(480);

			fire();
			await tick();
			mockContentHeight(2000);
			albumList.update((albums) => [
				...albums,
				album({ id: 'a-more', title: 'Mehr', song_count: 2 })
			]);
			await tick();

			expect({ wall: body.scrollTop, anchor: get(libraryScrollAnchor) }).toEqual({
				wall: 0,
				anchor: 0
			});
		}
	);

	it('defect:#1354: a navigation off the wall drops a landing that still waits', async () => {
		mockContentHeight(600);
		seedWall();
		await landOnWall(480);

		setLibrarySurface('playlists');

		expect(get(libraryScrollRestore)).toBeNull();
	});

	it('defect:#1354: a cancelled apply drops a landing that still waits', async () => {
		mockContentHeight(600);
		seedWall();
		await landOnWall(480);

		cancelLibraryHistoryApply();

		expect(get(libraryScrollRestore)).toBeNull();
	});

	it('1354_rule_12: a wall mounted without a landing starts at the anchor', async () => {
		seedWall();
		libraryScrollAnchor.set(240);

		const root = await render();

		expect(wallBody(root).scrollTop).toBe(240);
		expect(get(libraryScrollAnchor)).toBe(240);
	});

	it('1354_rule_12: a target the loaded list cannot hold settles at the end and the anchor follows', async () => {
		mockContentHeight(1000);
		seedWall();
		allAlbumsLoad.set({ status: 'ready', error: null });
		await landOnWall(5000);

		const root = await render();
		await tick();

		expect(wallBody(root).scrollTop).toBe(400);
		expect(get(libraryScrollAnchor)).toBe(400);
	});

	it('1354_rule_12: a fractional shortfall of a pixel still counts as reached', async () => {
		mockContentHeight(1080);
		seedWall();
		await landOnWall(480.6);

		const root = await render();

		expect(wallBody(root).scrollTop).toBe(480.6);
	});
});

describe('the row of the place the wall returns from', () => {
	afterEach(() => {
		vi.useRealTimers();
	});

	it.each([
		{
			case: 'the album on the phone Library',
			kind: 'library' as const,
			wall: 'browse' as const,
			place: { kind: 'album', id: 'a-fuer' } as OpenCollection,
			phone: true,
			lit: ['Sonne für Andrea']
		},
		{
			case: 'the playlist on the phone Playlists page',
			kind: 'playlists' as const,
			wall: 'playlists' as const,
			place: { kind: 'playlist', id: 'p-night' } as OpenCollection,
			phone: true,
			lit: ['Night drive']
		},
		{
			case: 'a playlist on the phone Library',
			kind: 'library' as const,
			wall: 'browse' as const,
			place: { kind: 'playlist', id: 'p-night' } as OpenCollection,
			phone: true,
			lit: []
		},
		{
			case: 'the album on the desktop wall',
			kind: 'library' as const,
			wall: 'browse' as const,
			place: { kind: 'album', id: 'a-fuer' } as OpenCollection,
			phone: false,
			lit: []
		}
	])('1354_rule_12: lights up $case', async ({ kind, wall, place, phone, lit }) => {
		if (phone) phoneViewport();
		seedWall();
		returnToWallFrom(place, wall);

		const root = await render(kind);

		expect(litTitles(root)).toEqual(lit);
		expect(root.querySelectorAll('.lit')).toHaveLength(lit.length);
	});

	it('1354_rule_12: lights up no row when the wall was not reached by a return', async () => {
		phoneViewport();
		seedWall();
		setOpenCollection({ kind: 'album', id: 'a-fuer' });

		const root = await render();

		expect(litTitles(root)).toEqual([]);
	});

	it('1354_rule_12: does not light the row again when a width change remounts it', async () => {
		vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
		const turnViewport = phoneViewport();
		seedWall();
		returnToWallFrom({ kind: 'album', id: 'a-fuer' }, 'browse');
		const root = await render();
		expect(litTitles(root)).toEqual(['Sonne für Andrea']);
		await vi.advanceTimersByTimeAsync(10_000);
		expect(litTitles(root)).toEqual([]);

		turnViewport(false);
		await tick();
		expect(root.querySelectorAll('.library-row')).toHaveLength(0);
		turnViewport(true);
		await tick();

		expect(root.querySelectorAll('.library-row').length).toBeGreaterThan(0);
		expect(root.querySelectorAll('.lit')).toHaveLength(0);
	});

	it('1354_rule_12: lights up its row for one showing of the wall only', async () => {
		phoneViewport();
		seedWall();
		returnToWallFrom({ kind: 'album', id: 'a-fuer' }, 'browse');
		await unmountAll();

		const first = await render();
		expect(litTitles(first)).toEqual(['Sonne für Andrea']);
		await unmountAll();
		const second = await render();

		expect(litTitles(second)).toEqual([]);
	});
});
