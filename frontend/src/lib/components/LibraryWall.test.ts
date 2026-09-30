import { replaceHistoryEntry } from '$lib/test-utils/library-history';
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
import { playlistList, playlistLoad, resetPlaylists } from '$lib/stores/playlists';

const fetchPlaylists = vi.fn();
const fetchPlaylist = vi.fn();
const fetchLibraryContinue = vi.fn();
const fetchAlbums = vi.fn();

vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('$lib/api/library', () => ({
	fetchLibraryContinue: (...args: unknown[]) => fetchLibraryContinue(...args)
}));
vi.mock('$lib/api/albums', () => ({ fetchAlbum: vi.fn(), fetchAlbums: vi.fn() }));
vi.mock('$lib/api/songs', () => ({ fetchSong: vi.fn(), fetchSongs: vi.fn() }));
vi.mock('$lib/api/client', () => ({
	fetchPlaylists: (...args: unknown[]) => fetchPlaylists(...args),
	fetchPlaylist: (...args: unknown[]) => fetchPlaylist(...args),
	fetchAlbums: (...args: unknown[]) => fetchAlbums(...args),
	fetchSong: vi.fn(),
	fetchSongs: vi.fn(),
	fetchLastFailedGeneration: vi.fn().mockResolvedValue({ job: null })
}));
vi.mock('$lib/stores/toast', () => ({ addToast: vi.fn() }));

import LibraryWall from './LibraryWall.svelte';

const mounted: Array<ReturnType<typeof mount>> = [];

beforeEach(() => {
	fetchPlaylists.mockReset().mockResolvedValue([]);
	fetchPlaylist.mockReset().mockResolvedValue({
		...playlist({ id: 'p-local', entry_count: 2, share_slug: null }),
		entries: []
	});
	fetchLibraryContinue.mockReset().mockResolvedValue({ items: [] });
	fetchAlbums.mockReset().mockResolvedValue(albumPage([], false));
	localStorage.clear();
	libraryWallOrder.set('title');
	resetLibraryOrderForTests();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylists();
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
	Reflect.deleteProperty(document, 'visibilityState');
	resetConnectivityForTests();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylists();
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

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(LibraryWall, { target }));
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

function orderButton(root: ParentNode, label: string): HTMLButtonElement {
	const group = root.querySelector('[role="group"][aria-label="Sort albums and playlists"]');
	const button = [...(group?.querySelectorAll('button') ?? [])].find(
		(candidate) => candidate.textContent?.trim() === label
	);
	if (!button) throw new Error(`no ${label} order`);
	return button;
}

function pressedOrder(root: ParentNode): string[] {
	return ['A–Z', 'Recent', 'Added'].filter(
		(label) => orderButton(root, label).getAttribute('aria-pressed') === 'true'
	);
}

function place(type: 'album' | 'playlist', id: string, title: string, activityAt: string) {
	return {
		type,
		id,
		title,
		cover: null,
		album_covers: [],
		song_id: null,
		song_title: null,
		activity_at: activityAt
	};
}

function seedWall(): void {
	albumList.set([
		album({
			id: 'a-sonne',
			title: 'Sonnenlauf',
			song_count: 7,
			created_at: '2026-07-28T10:00:00Z'
		}),
		album({
			id: 'a-fuer',
			title: 'Sonne für Andrea',
			song_count: 5,
			created_at: '2026-08-03T10:00:00Z'
		}),
		album({ id: 'a-nacht', title: 'nachtstrom', song_count: 1, created_at: '2026-09-01T10:00:00Z' })
	]);
	playlistList.set([
		playlist({
			id: 'p-night',
			title: 'Night drive',
			entry_count: 14,
			share_slug: null,
			created_at: '2026-08-20T10:00:00Z'
		})
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

	it('opens in A–Z: albums and playlists together by title, each line giving the size', async () => {
		seedWall();

		const root = await render();

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

		it('orders Recent by the activity Continue reads and names the last work, never re-sorting Continue', async () => {
			seedWall();
			const continueRow = [place('album', 'a-nacht', 'nachtstrom', '2026-09-27T03:47:00Z')];
			const everyPlace = [
				place('album', 'a-fuer', 'Sonne für Andrea', '2026-09-27T03:47:00Z'),
				place('playlist', 'p-night', 'Night drive', '2026-09-26T21:40:00Z'),
				place('album', 'a-nacht', 'nachtstrom', '2026-09-24T18:31:00Z'),
				place('album', 'a-sonne', 'Sonnenlauf', '2026-09-20T10:00:00Z')
			];
			fetchLibraryContinue.mockImplementation((page?: { offset: number; limit: number }) =>
				Promise.resolve({ items: page ? everyPlace : continueRow })
			);
			const root = await render();
			await vi.waitFor(() => expect(continueTitles(root)).toEqual(['nachtstrom']));

			orderButton(root, 'Recent').click();

			await vi.waitFor(() =>
				expect(tileTitles(root)).toEqual([
					'Sonne für Andrea',
					'Night drive',
					'nachtstrom',
					'Sonnenlauf'
				])
			);
			expect(fetchLibraryContinue).toHaveBeenCalledWith({ offset: 0, limit: 200 });
			expect(pressedOrder(root)).toEqual(['Recent']);
			expect(tileLines(root)).toEqual([
				'today 05:47',
				'Playlist · yesterday 23:40',
				'Thu 20:31',
				'20 Sep'
			]);
			expect(continueTitles(root)).toEqual(['nachtstrom']);
		});

		it('orders Recent by the activity of every place and names its last work, past one page of that activity', async () => {
			const titles = Array.from(
				{ length: 209 },
				(_, index) => `Album ${String(index).padStart(3, '0')}`
			);
			albumList.set(titles.map((title) => album({ id: title, title, song_count: 0 })));
			const byActivity = titles
				.toReversed()
				.map((title) => place('album', title, title, '2026-09-27T03:47:00Z'));
			fetchLibraryContinue.mockImplementation((page?: { offset: number; limit: number }) =>
				Promise.resolve({
					items: page ? byActivity.slice(page.offset, page.offset + page.limit) : []
				})
			);
			const root = await render();

			orderButton(root, 'Recent').click();

			await vi.waitFor(() => expect(tileTitles(root)).toEqual(titles.toReversed()));
			expect(new Set(tileLines(root))).toEqual(new Set(['today 05:47']));
		});

		it('orders Added newest first and names the day each was made', async () => {
			seedWall();
			const root = await render();

			orderButton(root, 'Added').click();
			await tick();

			expect(tileTitles(root)).toEqual([
				'nachtstrom',
				'Night drive',
				'Sonne für Andrea',
				'Sonnenlauf'
			]);
			expect(tileLines(root)).toEqual([
				'added 1 Sep',
				'Playlist · added 20 Aug',
				'added 3 Aug',
				'added 28 Jul'
			]);
		});
	});

	it('opens in the order last chosen on this device', async () => {
		seedWall();
		const first = await render();
		orderButton(first, 'Added').click();
		await unmountAll();
		libraryWallOrder.set('title');

		const reopened = await render();

		expect(pressedOrder(reopened)).toEqual(['Added']);
		expect(tileTitles(reopened)[0]).toBe('nachtstrom');
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

	it('keeps the recent ranking when a later read fails and reads again on the foreground and on reconnect', async () => {
		seedWall();
		const rankedBy = (album: string) =>
			Promise.resolve({ items: [place('album', album, album, '2026-09-21T10:00:00Z')] });
		fetchLibraryContinue.mockImplementation(() => rankedBy('a-sonne'));
		const root = await render();
		orderButton(root, 'Recent').click();
		await vi.waitFor(() => expect(tileTitles(root)[0]).toBe('Sonnenlauf'));

		const failedRead = Promise.reject(new Error('offline'));
		failedRead.catch(() => undefined);
		fetchLibraryContinue.mockImplementation(() => failedRead);
		returnToForeground();
		await failedRead.catch(() => undefined);
		await tick();

		expect(tileTitles(root)[0]).toBe('Sonnenlauf');
		expect(root.querySelector('[role="alert"]')).toBeNull();

		fetchLibraryContinue.mockImplementation(() => rankedBy('a-nacht'));
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
