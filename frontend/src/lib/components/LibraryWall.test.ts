import { makeAlbum as album, makePlaylist as playlist } from '$lib/test-utils/factories';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { openCollection } from '$lib/stores/collection';
import { albumList } from '$lib/stores/libraryData';
import { libraryBrowse } from '$lib/stores/librarySearch';
import { libraryWallOrder } from '$lib/stores/ui';
import { playlistList, playlistLoad, resetPlaylists } from '$lib/stores/playlists';

const fetchPlaylists = vi.fn();
const fetchPlaylist = vi.fn();
const fetchLibraryContinue = vi.fn();
const fetchAlbums = vi.fn();

vi.mock('$app/navigation', () => ({ goto: vi.fn().mockResolvedValue(undefined) }));
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('$lib/api/library', () => ({
	fetchLibraryContinue: (...args: unknown[]) => fetchLibraryContinue(...args)
}));
vi.mock('$lib/api/albums', () => ({
	fetchAlbum: vi.fn(),
	fetchAlbums: (...args: unknown[]) => fetchAlbums(...args)
}));
vi.mock('$lib/api/songs', () => ({ fetchSong: vi.fn(), fetchSongs: vi.fn() }));
vi.mock('$lib/api/client', () => ({
	fetchPlaylists: (...args: unknown[]) => fetchPlaylists(...args),
	fetchPlaylist: (...args: unknown[]) => fetchPlaylist(...args),
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
	fetchAlbums.mockReset();
	localStorage.clear();
	libraryWallOrder.set('title');
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylists();
	albumList.set([album({ id: 'a-local', title: 'Local Album' })]);
	playlistList.set([]);
	playlistLoad.set({ status: 'ready', error: null });
	history.replaceState(null, '', '/');
});

async function unmountAll(): Promise<void> {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
}

afterEach(async () => {
	await unmountAll();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylists();
});

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
			fetchLibraryContinue.mockImplementation((options?: { limit?: number }) =>
				Promise.resolve({ items: options?.limit ? everyPlace : continueRow })
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
			expect(fetchLibraryContinue).toHaveBeenCalledWith({ limit: 200 });
			expect(pressedOrder(root)).toEqual(['Recent']);
			expect(tileLines(root)).toEqual([
				'today 05:47',
				'Playlist · yesterday 23:40',
				'Thu 20:31',
				'20 Sep'
			]);
			expect(continueTitles(root)).toEqual(['nachtstrom']);
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

	it('says when the recent order cannot be read and reads it again on Retry', async () => {
		seedWall();
		fetchLibraryContinue.mockImplementation((options?: { limit?: number }) =>
			options?.limit ? Promise.reject(new Error('offline')) : Promise.resolve({ items: [] })
		);
		const root = await render();

		orderButton(root, 'Recent').click();
		await vi.waitFor(() =>
			expect(root.querySelector('[role="alert"]')?.textContent).toContain(
				'Could not load recent work.'
			)
		);
		fetchLibraryContinue.mockResolvedValue({
			items: [place('album', 'a-sonne', 'Sonnenlauf', '2026-09-21T10:00:00Z')]
		});
		root.querySelector<HTMLButtonElement>('[role="alert"] button')?.click();

		await vi.waitFor(() => expect(tileTitles(root)[0]).toBe('Sonnenlauf'));
		expect(root.querySelector('[role="alert"]')).toBeNull();
	});

	it('sorts the complete set, reading every album page before ordering the wall', async () => {
		seedWall();
		libraryBrowse.set({
			status: 'ready',
			error: null,
			albumHasMore: true,
			songHasMore: false,
			albumOffset: 3,
			songOffset: 0
		});
		fetchAlbums.mockResolvedValueOnce({
			items: [album({ id: 'a-arger', title: 'Ärger' })],
			total: 4,
			offset: 3,
			limit: 50,
			has_more: false
		});

		const root = await render();

		await vi.waitFor(() => expect(tileTitles(root)[0]).toBe('Ärger'));
		expect(fetchAlbums).toHaveBeenCalledWith(3, expect.any(Number), { sort: 'newest' });
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
