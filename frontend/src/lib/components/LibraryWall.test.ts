import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, PlaylistItem, ShareInventoryItem } from '$lib/api/types';
import {
	LIBRARY_ALBUMS_EMPTY,
	LIBRARY_PLAYLISTS_EMPTY,
	LIBRARY_SHARES_OPEN_LABEL,
	LIBRARY_SHARES_UNSHARE_LABEL
} from '$lib/constants';
import { searchQuery } from '$lib/stores/filter';
import { libraryFilter, resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { openCollection } from '$lib/stores/collection';
import { albumList, songList } from '$lib/stores/player';
import { playlistList, playlistLoad, resetPlaylistsForTests } from '$lib/stores/playlists';
import { resetSharesForTests } from '$lib/stores/shares';

const searchLibrary = vi.fn();
const fetchPlaylists = vi.fn();
const fetchShares = vi.fn();
const fetchAlbum = vi.fn();
const fetchAlbums = vi.fn();
const fetchSong = vi.fn();
const fetchSongs = vi.fn();
const unshareAlbum = vi.fn();

vi.mock('$app/navigation', () => ({ goto: vi.fn().mockResolvedValue(undefined) }));
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('$lib/api/library', () => ({
	searchLibrary: (...args: unknown[]) => searchLibrary(...args),
	fetchShares: (...args: unknown[]) => fetchShares(...args)
}));
vi.mock('$lib/api/albums', () => ({
	fetchAlbum: (...args: unknown[]) => fetchAlbum(...args),
	fetchAlbums: (...args: unknown[]) => fetchAlbums(...args)
}));
vi.mock('$lib/api/songs', () => ({
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchSongs: (...args: unknown[]) => fetchSongs(...args)
}));
vi.mock('$lib/api/client', () => ({
	fetchPlaylists: (...args: unknown[]) => fetchPlaylists(...args),
	fetchPlaylist: vi.fn(),
	fetchSong: vi.fn(),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false }),
	createPlaylist: vi.fn().mockResolvedValue({
		id: 'new-playlist',
		title: 'Playlist',
		entry_count: 0,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00'
	}),
	unshareAlbum: (...args: unknown[]) => unshareAlbum(...args),
	unshareSong: vi.fn(),
	unsharePlaylist: vi.fn(),
	unshareGeneration: vi.fn()
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
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function playlist(overrides: Partial<PlaylistItem> = {}): PlaylistItem {
	return {
		id: 'p-local',
		title: 'Night Drive',
		entry_count: 2,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function shareItem(overrides: Partial<ShareInventoryItem> = {}): ShareInventoryItem {
	return {
		type: 'album',
		id: 'a-local',
		title: 'Local Album',
		public_path: '/share/abc',
		is_archived: false,
		...overrides
	} as ShareInventoryItem;
}

beforeEach(() => {
	searchLibrary.mockReset().mockResolvedValue({ items: [], next_cursor: null, has_more: false });
	fetchPlaylists.mockReset().mockResolvedValue([]);
	fetchShares
		.mockReset()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, has_more: false });
	fetchAlbum.mockReset();
	fetchAlbums
		.mockReset()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, has_more: false });
	fetchSong.mockReset();
	fetchSongs
		.mockReset()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false });
	unshareAlbum.mockReset().mockResolvedValue(undefined);
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetSharesForTests();
	resetPlaylistsForTests();
	searchQuery.set('');
	albumList.set([album()]);
	songList.set([]);
	playlistList.set([]);
	playlistLoad.set({ status: 'ready', error: null });
	history.replaceState(null, '', '/');
});

afterEach(async () => {
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetSharesForTests();
	resetPlaylistsForTests();
});

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(LibraryWall, { target, props: { onNewSong: vi.fn() } }));
	await tick();
	return target;
}

function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

describe('LibraryWall filter chips', () => {
	it('is single-select and switches with arrow keys', async () => {
		const root = await render();
		const albumsChip = requireElement<HTMLButtonElement>(root, '#library-filter-albums');
		const playlistsChip = requireElement<HTMLButtonElement>(root, '#library-filter-playlists');
		expect(albumsChip.getAttribute('aria-checked')).toBe('true');
		expect(playlistsChip.getAttribute('aria-checked')).toBe('false');

		albumsChip.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
		await tick();
		expect(get(libraryFilter)).toBe('playlists');
	});

	it('shows the playlists wall when the Playlists chip is picked', async () => {
		playlistList.set([playlist()]);
		const root = await render();
		requireElement<HTMLButtonElement>(root, '#library-filter-playlists').click();
		await tick();
		expect(root.textContent).toContain('Night Drive');
		expect(root.querySelector('.search')).toBeNull();
	});

	it('shows an empty state for a filter with nothing in it', async () => {
		albumList.set([]);
		const root = await render();
		expect(root.textContent).toContain(LIBRARY_ALBUMS_EMPTY);
		requireElement<HTMLButtonElement>(root, '#library-filter-playlists').click();
		await tick();
		expect(root.textContent).toContain(LIBRARY_PLAYLISTS_EMPTY);
	});
});

describe('LibraryWall selection', () => {
	it('opens an album collection when its tile is clicked', async () => {
		const root = await render();
		const tile = requireElement<HTMLButtonElement>(root, '.album-card');
		tile.click();
		await tick();
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a-local' });
	});
});

describe('LibraryWall sort', () => {
	it('persists the sort choice to history', async () => {
		const root = await render();
		const before = history.state?.index ?? 0;
		const select = requireElement<HTMLSelectElement>(root, '.sort-select');
		select.value = 'oldest';
		select.dispatchEvent(new Event('change', { bubbles: true }));
		await tick();
		const state = history.state as { index: number; sort: string } | null;
		expect(state?.index).toBe(before);
		expect(state?.sort).toBe('oldest');
	});
});

describe('LibraryWall create actions', () => {
	it('creates and opens a new playlist', async () => {
		const root = await render();
		requireElement<HTMLButtonElement>(root, '#library-filter-playlists').click();
		await tick();
		requireElement<HTMLButtonElement>(root, '.new-btn[aria-label="New playlist"]').click();
		await tick();
		await tick();
		expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'new-playlist' });
		expect(get(libraryFilter)).toBe('playlists');
	});

	it('calls onNewSong for the album create action', async () => {
		const onNewSong = vi.fn();
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(LibraryWall, { target, props: { onNewSong } }));
		await tick();
		requireElement<HTMLButtonElement>(target, '.new-btn[aria-label="New album"]').click();
		expect(onNewSong).toHaveBeenCalledTimes(1);
	});

	it('shows only the create action for the active filter, never both at once', async () => {
		const root = await render();
		expect(root.querySelector('.new-btn[aria-label="New album"]')).not.toBeNull();
		expect(root.querySelector('.new-btn[aria-label="New playlist"]')).toBeNull();

		requireElement<HTMLButtonElement>(root, '#library-filter-playlists').click();
		await tick();
		expect(root.querySelector('.new-btn[aria-label="New album"]')).toBeNull();
		expect(root.querySelector('.new-btn[aria-label="New playlist"]')).not.toBeNull();

		requireElement<HTMLButtonElement>(root, '#library-filter-shared').click();
		await tick();
		expect(root.querySelector('.new-btn')).toBeNull();
	});
});

describe('LibraryWall shared filter', () => {
	it('renders the share inventory with open and unshare actions', async () => {
		fetchShares.mockResolvedValue({
			items: [shareItem()],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		const root = await render();
		requireElement<HTMLButtonElement>(root, '#library-filter-shared').click();
		await tick();
		await tick();
		expect(
			root.querySelector(`[aria-label="${LIBRARY_SHARES_OPEN_LABEL} Local Album"]`)
		).not.toBeNull();
		expect(root.querySelector(`[aria-label="${LIBRARY_SHARES_UNSHARE_LABEL}"]`)).not.toBeNull();
	});
});
