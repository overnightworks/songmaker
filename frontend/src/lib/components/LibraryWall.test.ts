import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type {
	AlbumItem,
	GenerationItem,
	PlaylistItem,
	ShareInventoryItem,
	SongItem
} from '$lib/api/types';
import {
	LIBRARY_ALBUMS_EMPTY,
	LIBRARY_PLAYLISTS_EMPTY,
	LIBRARY_RETRY_LABEL,
	LIBRARY_SEARCH_DEBOUNCE_MS,
	LIBRARY_SEARCH_EMPTY,
	LIBRARY_SHARES_OPEN_LABEL,
	LIBRARY_SHARES_UNSHARE_LABEL
} from '$lib/constants';
import { searchQuery } from '$lib/stores/filter';
import { libraryFilter, resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { openCollection } from '$lib/stores/collection';
import { albumList, songList } from '$lib/stores/player';
import { playlistList, playlistLoad, resetPlaylists } from '$lib/stores/playlists';
import { resetShares } from '$lib/stores/shares';

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
		picked_count: 0,
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

function pickedGeneration(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
		mp3_path: 'g1.mp3',
		wav_path: null,
		seed: 1,
		status: 'completed',
		is_archived: false,
		is_picked: true,
		is_kept: false,
		is_shared: false,
		model_mode: 'sft',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: null,
		scores: null,
		generation_params: null,
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

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's-tide',
		title: 'Tide',
		album_id: 'a-local',
		album_title: 'Local Album',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: '',
		prompt: '',
		bpm: 120,
		audio_duration: 180,
		key_scale: 'Am',
		generation_params: null,
		version_count: 1,
		generation_count: 0,
		best_scores: null,
		best_rating: null,
		generations: [],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null,
		...overrides
	};
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
	resetShares();
	resetPlaylists();
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
	resetShares();
	resetPlaylists();
});

async function render(): Promise<HTMLElement> {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(LibraryWall, { target, props: { oncreate: vi.fn() } }));
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
		expect(root.querySelector('.search')).not.toBeNull();
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
		const tile = requireElement<HTMLButtonElement>(root, '.wall-tile-body');
		tile.click();
		await tick();
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a-local' });
	});

	it('shows the song and pick count beneath the album title', async () => {
		songList.set([
			song({ id: 's1', album_id: 'a-local', generations: [] }),
			song({ id: 's2', album_id: 'a-local', generations: [pickedGeneration()] })
		]);
		albumList.set([album({ song_count: 2 })]);
		const root = await render();
		expect(root.querySelector('.wall-tile-subtitle')?.textContent).toBe('2 songs · 1 pick');
	});

	it('plays the album from the tile play control without opening it', async () => {
		const root = await render();
		const play = requireElement<HTMLButtonElement>(root, '.wall-tile-play');
		play.click();
		await tick();
		expect(get(openCollection)).toBeNull();
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

	it('calls oncreate for the album create action', async () => {
		const oncreate = vi.fn();
		const target = document.createElement('div');
		document.body.append(target);
		mounted.push(mount(LibraryWall, { target, props: { oncreate } }));
		await tick();
		requireElement<HTMLButtonElement>(target, '.new-btn[aria-label="New album"]').click();
		expect(oncreate).toHaveBeenCalledTimes(1);
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
	it('opens a remote inventory album via fetchAlbum, then hydrateAndOpenAlbum', async () => {
		const remote = album({ id: 'a-remote', title: 'Remote Shared', is_shared: true });
		fetchAlbum.mockResolvedValue(remote);
		fetchShares.mockResolvedValue({
			items: [
				shareItem({
					id: 'a-remote',
					title: 'Remote Shared',
					public_path: '/share/remote'
				})
			],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		const root = await render();
		requireElement<HTMLButtonElement>(root, '#library-filter-shared').click();
		await tick();
		await tick();

		requireElement<HTMLButtonElement>(
			root,
			`[aria-label="${LIBRARY_SHARES_OPEN_LABEL} Remote Shared"]`
		).click();
		await Promise.resolve();
		await tick();

		expect(fetchAlbum).toHaveBeenCalledWith('a-remote');
		expect(get(albumList).some((item) => item.id === 'a-remote')).toBe(true);
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a-remote' });
	});

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

	it('unshares on confirm: mutates the album, refreshes the inventory, and closes the dialog', async () => {
		albumList.set([album({ is_shared: true, share_slug: 'abc' })]);
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
		requireElement<HTMLButtonElement>(
			root,
			`[aria-label="${LIBRARY_SHARES_UNSHARE_LABEL}"]`
		).click();
		await tick();
		requireElement<HTMLButtonElement>(document.body, '.confirm-btn').click();
		await tick();
		await Promise.resolve();
		await tick();

		expect(unshareAlbum).toHaveBeenCalledWith('a-local');
		expect(get(albumList).find((item) => item.id === 'a-local')?.is_shared).toBe(false);
		expect(document.body.querySelector('.confirm-btn')).toBeNull();
	});

	it('cancels without mutating the album when the dialog is dismissed', async () => {
		albumList.set([album({ is_shared: true, share_slug: 'abc' })]);
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
		requireElement<HTMLButtonElement>(
			root,
			`[aria-label="${LIBRARY_SHARES_UNSHARE_LABEL}"]`
		).click();
		await tick();
		requireElement<HTMLButtonElement>(document.body, '.cancel-btn').click();
		await tick();

		expect(unshareAlbum).not.toHaveBeenCalled();
		expect(get(albumList).find((item) => item.id === 'a-local')?.is_shared).toBe(true);
	});
});

describe('LibraryWall toolbar consistency', () => {
	it('keeps chips, sort, and search in the same order for every filter', async () => {
		playlistList.set([playlist()]);
		fetchShares.mockResolvedValue({
			items: [shareItem()],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		const root = await render();

		for (const id of ['albums', 'playlists', 'shared']) {
			requireElement<HTMLButtonElement>(root, `#library-filter-${id}`).click();
			await tick();
			await tick();
			const controls = requireElement<HTMLElement>(root, '.wall-controls');
			const order = Array.from(controls.children).map((child) =>
				child.matches('.filter-chips')
					? 'chips'
					: child.matches('.sort-select')
						? 'sort'
						: child.matches('.search')
							? 'search'
							: 'other'
			);
			expect(order.slice(0, 3), `order for ${id}`).toEqual(['chips', 'sort', 'search']);
		}
	});

	it('filters playlists by title', async () => {
		playlistList.set([
			playlist({ id: 'p1', title: 'Night Drive' }),
			playlist({ id: 'p2', title: 'Sunrise' })
		]);
		const root = await render();
		requireElement<HTMLButtonElement>(root, '#library-filter-playlists').click();
		await tick();

		const input = requireElement<HTMLInputElement>(root, '.search');
		input.value = 'sun';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();

		expect(root.textContent).toContain('Sunrise');
		expect(root.textContent).not.toContain('Night Drive');
	});

	it('filters the Shared inventory rows by name', async () => {
		fetchShares.mockResolvedValue({
			items: [
				shareItem({ id: 'a-local', title: 'Local Album' }),
				shareItem({ id: 'a-other', title: 'Other Record' })
			],
			total: 2,
			offset: 0,
			limit: 50,
			has_more: false
		});
		const root = await render();
		requireElement<HTMLButtonElement>(root, '#library-filter-shared').click();
		await tick();
		await tick();

		const input = requireElement<HTMLInputElement>(root, '.search');
		input.value = 'other';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();

		expect(root.textContent).toContain('Other Record');
		expect(root.textContent).not.toContain('Local Album');
	});
});

describe('LibraryWall search', () => {
	beforeEach(() => {
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	async function typeSearch(root: HTMLElement, query: string): Promise<void> {
		const input = requireElement<HTMLInputElement>(root, '.search');
		input.value = query;
		input.dispatchEvent(new Event('input', { bubbles: true }));
		await tick();
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		await tick();
		await Promise.resolve();
		await tick();
	}

	it('searches the server instead of filtering the loaded song list', async () => {
		albumList.set([album({ id: 'a-local', title: 'Local Only' })]);
		searchLibrary.mockResolvedValue({
			items: [{ type: 'album', album: album({ id: 'nachtstrom', title: 'Nachtstrom' }) }],
			next_cursor: null,
			has_more: false
		});
		const root = await render();
		await typeSearch(root, 'Nachtstrom');

		expect(searchLibrary).toHaveBeenCalled();
		expect(root.textContent).toContain('Nachtstrom');
		expect(root.textContent).not.toContain('Local Only');
	});

	it('shows search empty copy distinct from the browse empty copy when the server returns no hits', async () => {
		const root = await render();
		await typeSearch(root, 'missing');

		expect(root.textContent).toContain(LIBRARY_SEARCH_EMPTY);
		expect(root.textContent).not.toContain(LIBRARY_ALBUMS_EMPTY);
	});

	it('shows a retry action that re-runs the same query when search fails', async () => {
		searchLibrary.mockRejectedValue(new Error('offline'));
		const root = await render();
		await typeSearch(root, 'Tide');

		expect(root.textContent).toContain('offline');
		const retry = requireElement<HTMLButtonElement>(root, '.retry-btn');
		expect(retry.textContent).toBe(LIBRARY_RETRY_LABEL);

		searchLibrary.mockResolvedValueOnce({
			items: [{ type: 'album', album: album({ id: 'nachtstrom', title: 'Nachtstrom' }) }],
			next_cursor: null,
			has_more: false
		});
		retry.click();
		await Promise.resolve();
		await tick();
		expect(root.textContent).toContain('Nachtstrom');
	});

	it('groups a song hit under its album and expands it, unlike a bare album hit', async () => {
		searchLibrary.mockResolvedValue({
			items: [
				{ type: 'album', album: album({ id: 'a-collapsed', title: 'Collapsed' }) },
				{
					type: 'song',
					song: song({ id: 's-tide', title: 'Tide', album_id: 'a-expanded' }),
					album_id: 'a-expanded',
					album_title: 'Expanded'
				}
			],
			next_cursor: null,
			has_more: false
		});
		const root = await render();
		await typeSearch(root, 'Tide');

		const cards = Array.from(root.querySelectorAll('.album-card'));
		expect(cards).toHaveLength(2);
		expect(root.querySelector('.song-row')?.textContent).toContain('Tide');
	});

	it('persists search pagination to history after Load more', async () => {
		searchLibrary
			.mockResolvedValueOnce({
				items: [{ type: 'album', album: album({ id: 'a1', title: 'One' }) }],
				next_cursor: 'cursor-1',
				has_more: true
			})
			.mockResolvedValueOnce({
				items: [{ type: 'album', album: album({ id: 'a2', title: 'Two' }) }],
				next_cursor: null,
				has_more: false
			});
		const root = await render();
		await typeSearch(root, 'Catalog');
		expect(root.textContent).toContain('One');

		requireElement<HTMLButtonElement>(root, '.load-more').click();
		await Promise.resolve();
		await Promise.resolve();
		await tick();

		expect(root.textContent).toContain('Two');
		expect((history.state as { searchLoadedCount: number }).searchLoadedCount).toBe(2);
	});
});

describe('LibraryWall share count request storm (#139)', () => {
	it('does not refetch the share count on a fast remount', async () => {
		await render();
		expect(fetchShares).toHaveBeenCalledTimes(1);

		const first = mounted.pop();
		if (first) await unmount(first);

		await render();

		expect(fetchShares).toHaveBeenCalledTimes(1);
	});
});
