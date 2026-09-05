import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, PlaylistItem } from '$lib/api/types';
import { resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { openCollection } from '$lib/stores/collection';
import { albumList } from '$lib/stores/libraryData';
import { playlistList, playlistLoad, resetPlaylists } from '$lib/stores/playlists';

const fetchPlaylists = vi.fn();
const fetchPlaylist = vi.fn();
const fetchLibraryContinue = vi.fn();

vi.mock('$app/navigation', () => ({ goto: vi.fn().mockResolvedValue(undefined) }));
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('$lib/api/library', () => ({
	fetchLibraryContinue: (...args: unknown[]) => fetchLibraryContinue(...args)
}));
vi.mock('$lib/api/albums', () => ({ fetchAlbum: vi.fn(), fetchAlbums: vi.fn() }));
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

function album(overrides: Partial<AlbumItem> = {}): AlbumItem {
	return {
		id: 'a-local',
		title: 'Local Album',
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 1,
		picked_count: 0,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		is_archived: false,
		...overrides
	};
}

function playlist(overrides: Partial<PlaylistItem> = {}): PlaylistItem {
	return {
		id: 'p-local',
		title: 'Night Drive',
		slug: 'night-drive',
		entry_count: 2,
		is_shared: false,
		share_slug: null,
		album_covers: [],
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

beforeEach(() => {
	fetchPlaylists.mockReset().mockResolvedValue([]);
	fetchPlaylist.mockReset().mockResolvedValue({ ...playlist(), entries: [] });
	fetchLibraryContinue.mockReset().mockResolvedValue({ items: [] });
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylists();
	albumList.set([album()]);
	playlistList.set([]);
	playlistLoad.set({ status: 'ready', error: null });
	history.replaceState(null, '', '/');
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
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

describe('LibraryWall', () => {
	it('loads playlists when the wall mounts', async () => {
		playlistLoad.set({ status: 'idle', error: null });
		fetchPlaylists.mockResolvedValueOnce([playlist()]);

		const root = await render();

		await vi.waitFor(() => expect(fetchPlaylists).toHaveBeenCalledTimes(1));
		await vi.waitFor(() =>
			expect(root.querySelector('[aria-label="Open playlist Night Drive"]')).not.toBeNull()
		);
	});

	it('shows albums and playlists in one chronological grid without filter chips', async () => {
		albumList.set([
			album({ id: 'a-new', title: 'New Album', created_at: '2026-03-03T00:00:00+00:00' }),
			album({ id: 'a-old', title: 'Old Album', created_at: '2026-01-01T00:00:00+00:00' })
		]);
		playlistList.set([
			playlist({
				id: 'p-middle',
				title: 'Middle Playlist',
				created_at: '2026-02-02T00:00:00+00:00'
			})
		]);
		const root = await render();

		expect(tileTitles(root)).toEqual(['New Album', 'Middle Playlist', 'Old Album']);
		expect(root.querySelector('[role="radiogroup"]')).toBeNull();
		expect(root.querySelector('.sort-select')).toBeNull();
	});

	it('uses a playlist cover before its album-cover mosaic', async () => {
		playlistList.set([
			playlist({
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
			playlist({ album_covers: [{ card: '/covers/album.jpg', detail: '/covers/album.jpg' }] })
		]);
		const root = await render();

		expect(root.querySelector('.playlist-cover')).not.toBeNull();
		expect(root.querySelector('.playlist-cover img')?.getAttribute('loading')).toBe('lazy');
	});

	it('opens the matching collection through the navigation store', async () => {
		playlistList.set([playlist()]);
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
