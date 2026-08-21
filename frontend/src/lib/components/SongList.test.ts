import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, PlaylistItem, ShareInventoryItem, SongItem } from '$lib/api/types';
import {
	LIBRARY_ALBUMS_EMPTY,
	LIBRARY_PLAYLISTS_EMPTY,
	LIBRARY_LOAD_MORE,
	LIBRARY_RETRY_LABEL,
	LIBRARY_SEARCH_DEBOUNCE_MS,
	LIBRARY_SEARCH_EMPTY,
	LIBRARY_SEARCH_LOADING,
	LIBRARY_SEARCH_PLACEHOLDER,
	LIBRARY_SECTION_LABELS,
	LIBRARY_SHARED_EMPTY,
	LIBRARY_SHARED_LOADING,
	LIBRARY_SHARES_HISTORY_SECTION,
	LIBRARY_SHARES_OPEN_LABEL,
	LIBRARY_SHARES_TYPE_LABELS,
	LIBRARY_SHARES_UNSHARE_LABEL
} from '$lib/constants';
import { searchQuery } from '$lib/stores/filter';
import {
	applyLibraryHistory,
	libraryRootState,
	librarySurface,
	resetLibraryContextForTests,
	setLibrarySurface
} from '$lib/stores/libraryContext';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { albumList, selectedAlbumId, selectedSongId, songList } from '$lib/stores/player';
import { playlistList, playlistLoad } from '$lib/stores/playlists';
import { openSharesInventory, resetSharesForTests } from '$lib/stores/shares';

const searchLibrary = vi.fn();
const fetchPlaylists = vi.fn();
const fetchShares = vi.fn();
const fetchAlbum = vi.fn();
const fetchAlbums = vi.fn();
const fetchSong = vi.fn();
const fetchSongs = vi.fn();
const unshareAlbum = vi.fn();

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
	fetchSongs: vi.fn().mockResolvedValue({
		items: [],
		total: 0,
		offset: 0,
		limit: 200,
		has_more: false
	}),
	createPlaylist: vi.fn(),
	unshareAlbum: (...args: unknown[]) => unshareAlbum(...args),
	unshareSong: vi.fn(),
	unsharePlaylist: vi.fn(),
	unshareGeneration: vi.fn()
}));
vi.mock('$lib/stores/toast', () => ({
	addToast: vi.fn()
}));

import SongList from './SongList.svelte';

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

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's-local',
		title: 'Local Only',
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

function playlist(overrides: Partial<PlaylistItem> = {}): PlaylistItem {
	return {
		id: 'p1',
		title: 'Late Night',
		entry_count: 2,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function render() {
	const target = document.createElement('div');
	document.body.appendChild(target);
	const component = mount(SongList, { target });
	mounted.push(component);
	return target;
}

function sectionTab(target: HTMLElement, label: string): HTMLButtonElement {
	const tab = [...target.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find(
		(button) => button.textContent === label
	);
	if (!tab) throw new Error(`Expected section tab ${label}`);
	return tab;
}

function shareItem(overrides: Partial<ShareInventoryItem> = {}): ShareInventoryItem {
	return {
		type: 'song',
		id: 's-server',
		title: 'Server Shared',
		share_slug: 'slug-server',
		created_at: '2026-01-01T00:00:00+00:00',
		public_path: '/share/song/slug-server',
		...overrides
	};
}

beforeEach(() => {
	vi.useFakeTimers();
	searchLibrary.mockReset();
	fetchPlaylists.mockReset();
	fetchShares.mockReset();
	fetchPlaylists.mockResolvedValue([]);
	fetchShares.mockResolvedValue({
		items: [],
		total: 0,
		offset: 0,
		limit: 50,
		has_more: false
	});
	fetchAlbums.mockReset();
	fetchAlbum.mockReset();
	fetchAlbum.mockImplementation(async (id: unknown) => album({ id: String(id) }));
	fetchSong.mockReset();
	fetchSong.mockImplementation(async (id: unknown) =>
		song({ id: String(id), album_id: 'a-local' })
	);
	unshareAlbum.mockReset();
	unshareAlbum.mockResolvedValue(undefined);
	fetchSongs.mockReset();
	fetchAlbums.mockResolvedValue({
		items: [],
		total: 0,
		offset: 0,
		limit: 50,
		has_more: false
	});
	fetchSongs.mockResolvedValue({
		items: [],
		total: 0,
		offset: 0,
		limit: 200,
		has_more: false
	});
	resetLibrarySearchForTests();
	resetLibraryContextForTests();
	resetSharesForTests();
	searchQuery.set('');
	playlistList.set([]);
	playlistLoad.set({ status: 'idle', error: null });
	albumList.set([album()]);
	songList.set([song()]);
	selectedAlbumId.set(null);
	selectedSongId.set(null);
	history.replaceState(null, '', '/');
});

afterEach(async () => {
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	for (const component of mounted.splice(0)) await unmount(component);
	document.body.replaceChildren();
	vi.useRealTimers();
	resetSharesForTests();
	searchQuery.set('');
	selectedAlbumId.set(null);
	selectedSongId.set(null);
});

describe('SongList search', () => {
	it('uses a library-wide placeholder', async () => {
		const target = render();
		await tick();
		const input = target.querySelector('input.search') as HTMLInputElement;
		expect(input.placeholder).toBe(LIBRARY_SEARCH_PLACEHOLDER);
	});

	it('shows albums empty copy when there are no albums', async () => {
		albumList.set([]);
		songList.set([]);
		const target = render();
		await tick();
		expect(target.textContent).toContain(LIBRARY_ALBUMS_EMPTY);
		expect(target.textContent).not.toContain(LIBRARY_SEARCH_EMPTY);
	});

	it('searches the server instead of filtering the loaded song list', async () => {
		searchLibrary.mockResolvedValue({
			items: [
				{
					type: 'album',
					album: album({ id: 'nachtstrom', title: 'Nachtstrom' })
				}
			],
			next_cursor: null,
			has_more: false
		});
		const target = render();
		await tick();
		searchQuery.set('Nachtstrom');
		await tick();
		expect(target.textContent).toContain(LIBRARY_SEARCH_LOADING);
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		await tick();
		await Promise.resolve();
		await tick();
		expect(searchLibrary).toHaveBeenCalled();
		expect(target.textContent).toContain('Nachtstrom');
		expect(target.textContent).not.toContain('Local Only');
		expect(get(songList)[0].title).toBe('Local Only');
	});

	it('shows search empty copy when the server returns no hits', async () => {
		searchLibrary.mockResolvedValue({ items: [], next_cursor: null, has_more: false });
		const target = render();
		await tick();
		searchQuery.set('missing');
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		await tick();
		await Promise.resolve();
		await tick();
		expect(target.textContent).toContain(LIBRARY_SEARCH_EMPTY);
		expect(target.textContent).not.toContain(LIBRARY_ALBUMS_EMPTY);
	});

	it('shows retry when search fails', async () => {
		searchLibrary.mockRejectedValue(new Error('offline'));
		const target = render();
		await tick();
		searchQuery.set('Tide');
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		await tick();
		await Promise.resolve();
		await tick();
		expect(target.textContent).toContain('offline');
		const retry = [...target.querySelectorAll('button')].find(
			(button) => button.textContent === LIBRARY_RETRY_LABEL
		);
		expect(retry).toBeDefined();
	});

	it('keeps album context on song hits and expands those albums', async () => {
		searchLibrary.mockResolvedValue({
			items: [
				{
					type: 'song',
					song: song({ id: 's-tide', title: 'Tide', album_id: 'nachtstrom' }),
					album_id: 'nachtstrom',
					album_title: 'Nachtstrom'
				}
			],
			next_cursor: null,
			has_more: false
		});
		const target = render();
		await tick();
		searchQuery.set('Tide');
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		await tick();
		await Promise.resolve();
		await tick();
		expect(target.textContent).toContain('Nachtstrom');
		expect(target.textContent).toContain('Tide');
		expect(target.querySelector('.song-row')?.textContent).toContain('Tide');
	});

	it('persists search pagination after load more', async () => {
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
		const target = render();
		await tick();
		searchQuery.set('Catalog');
		await tick();
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		await tick();
		await Promise.resolve();
		await tick();
		expect(target.textContent).toContain('One');
		const loadMore = [...target.querySelectorAll('button')].find(
			(button) => button.textContent === LIBRARY_LOAD_MORE
		);
		expect(loadMore).toBeDefined();
		await loadMore?.click();
		await tick();
		await Promise.resolve();
		await Promise.resolve();
		await tick();
		expect(target.textContent).toContain('Two');
		expect(history.state.searchLoadedCount).toBe(2);
	});
});

describe('SongList sections', () => {
	it('starts on albums with albums collapsed and playlists/shared not rendered as lists', async () => {
		playlistList.set([playlist()]);
		playlistLoad.set({ status: 'ready', error: null });
		albumList.set([
			album({ id: 'a1', title: 'First', song_count: 2 }),
			album({ id: 'a2', title: 'Second', artist: 'Other', song_count: 3 })
		]);
		songList.set([
			song({ id: 's1', album_id: 'a1', title: 'Song One' }),
			song({ id: 's2', album_id: 'a2', title: 'Song Two' })
		]);
		albumList.update((list) =>
			list.map((item) => (item.id === 'a1' ? { ...item, is_shared: true } : item))
		);
		const target = render();
		await tick();

		expect(target.querySelector('[data-library-section="albums"]')).not.toBeNull();
		expect(target.querySelector('[data-library-section="playlists"]')).toBeNull();
		expect(target.querySelector('[data-library-section="shares"]')).toBeNull();
		expect(target.querySelector('.song-row')).toBeNull();
		expect(target.querySelector('.share-row')).toBeNull();
		expect(target.textContent).not.toContain('Late Night');
		expect(target.textContent).toContain('First');
		expect(target.textContent).toContain('Artist');
		expect(target.textContent).toContain('Other');
		expect(sectionTab(target, LIBRARY_SECTION_LABELS.albums).getAttribute('aria-selected')).toBe(
			'true'
		);
		expect(sectionTab(target, LIBRARY_SECTION_LABELS.playlists).getAttribute('aria-selected')).toBe(
			'false'
		);
		expect([...target.querySelectorAll('[role="tab"]')].map((tab) => tab.textContent)).toEqual([
			LIBRARY_SECTION_LABELS.albums,
			LIBRARY_SECTION_LABELS.playlists
		]);
	});

	it('keeps exactly one section active and restores Studio song detail after Listen', async () => {
		playlistList.set([playlist()]);
		playlistLoad.set({ status: 'ready', error: null });
		selectedAlbumId.set('a-local');
		selectedSongId.set('s-local');
		setLibrarySurface('detail');
		const target = render();
		await tick();

		sectionTab(target, LIBRARY_SECTION_LABELS.playlists).click();
		await tick();
		expect(target.querySelector('[data-library-section="playlists"]')).not.toBeNull();
		expect(target.querySelector('[data-library-section="albums"]')).toBeNull();
		expect(target.querySelector('input.search')).toBeNull();
		expect(target.textContent).toContain('Late Night');
		expect(get(librarySurface)).toBe('browse');
		expect(
			[...target.querySelectorAll('[role="tab"][aria-selected="true"]')].map(
				(tab) => tab.textContent
			)
		).toEqual([LIBRARY_SECTION_LABELS.playlists]);

		sectionTab(target, LIBRARY_SECTION_LABELS.albums).click();
		await tick();
		expect(target.querySelector('[data-library-section="albums"]')).not.toBeNull();
		expect(get(librarySurface)).toBe('detail');
		expect(get(selectedSongId)).toBe('s-local');
		expect(target.querySelector('input.search')).not.toBeNull();
	});

	it('hides search on Listen and does not query library search', async () => {
		const target = render();
		await tick();
		sectionTab(target, LIBRARY_SECTION_LABELS.playlists).click();
		await tick();
		expect(target.querySelector('input.search')).toBeNull();
		searchQuery.set('Tide');
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		await tick();
		expect(searchLibrary).not.toHaveBeenCalled();
		expect(target.querySelector('[data-library-section="playlists"]')).not.toBeNull();
	});

	it('does not fire a pending Studio search after switching to Listen', async () => {
		const target = render();
		await tick();
		searchQuery.set('Tide');
		await tick();
		expect(searchLibrary).not.toHaveBeenCalled();
		sectionTab(target, LIBRARY_SECTION_LABELS.playlists).click();
		await tick();
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		await tick();
		expect(searchLibrary).not.toHaveBeenCalled();
		expect(target.querySelector('input.search')).toBeNull();
	});

	it('moves focus with the active section tab on arrow keys', async () => {
		const target = render();
		await tick();
		const albums = sectionTab(target, LIBRARY_SECTION_LABELS.albums);
		albums.focus();
		albums.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
		await tick();
		expect(sectionTab(target, LIBRARY_SECTION_LABELS.playlists)).toBe(document.activeElement);
		expect(sectionTab(target, LIBRARY_SECTION_LABELS.playlists).getAttribute('aria-selected')).toBe(
			'true'
		);
		sectionTab(target, LIBRARY_SECTION_LABELS.playlists).dispatchEvent(
			new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })
		);
		await tick();
		expect(sectionTab(target, LIBRARY_SECTION_LABELS.albums)).toBe(document.activeElement);
		expect(sectionTab(target, LIBRARY_SECTION_LABELS.albums).getAttribute('aria-selected')).toBe(
			'true'
		);
	});

	it('shows playlists empty copy for that section', async () => {
		playlistLoad.set({ status: 'ready', error: null });
		const target = render();
		await tick();

		sectionTab(target, LIBRARY_SECTION_LABELS.playlists).click();
		await tick();
		expect(target.textContent).toContain(LIBRARY_PLAYLISTS_EMPTY);
	});

	it('does not build share inventory from loaded lists', async () => {
		albumList.update((list) =>
			list.map((item) => ({ ...item, is_shared: true, title: 'Loaded Shared' }))
		);
		fetchShares.mockResolvedValue({
			items: [shareItem()],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		const target = render();
		await tick();
		openSharesInventory();
		await tick();
		await Promise.resolve();
		await tick();
		expect(target.querySelector('[data-library-section="shares"]')).not.toBeNull();
		expect(target.textContent).toContain('Server Shared');
		expect(target.textContent).toContain(LIBRARY_SHARES_TYPE_LABELS.song);
		expect(target.textContent).not.toContain('Loaded Shared');
		expect(fetchShares).toHaveBeenCalled();
	});

	it('opens inventory from history.section shared and waits for a complete empty response', async () => {
		let resolvePage: ((value: unknown) => void) | undefined;
		fetchShares.mockImplementationOnce(
			() =>
				new Promise((resolve) => {
					resolvePage = resolve;
				})
		);
		const target = render();
		await tick();
		const restore = applyLibraryHistory({
			...libraryRootState(),
			section: LIBRARY_SHARES_HISTORY_SECTION
		});
		await tick();
		expect(target.querySelector('[data-library-section="shares"]')).not.toBeNull();
		expect(target.textContent).toContain(LIBRARY_SHARED_LOADING);
		expect(target.textContent).not.toContain(LIBRARY_SHARED_EMPTY);
		resolvePage?.({
			items: [],
			total: 0,
			offset: 0,
			limit: 50,
			has_more: false
		});
		await restore;
		await tick();
		await Promise.resolve();
		await tick();
		expect(target.textContent).toContain(LIBRARY_SHARED_EMPTY);
	});

	it('auto-opens only the selected album', async () => {
		albumList.set([
			album({ id: 'a1', title: 'First', song_count: 1 }),
			album({ id: 'a2', title: 'Second', song_count: 1 })
		]);
		songList.set([
			song({ id: 's1', album_id: 'a1', title: 'Song One' }),
			song({ id: 's2', album_id: 'a2', title: 'Song Two' })
		]);
		selectedAlbumId.set('a1');
		const target = render();
		await tick();
		const rows = [...target.querySelectorAll('.song-row')].map((row) => row.textContent);
		expect(rows.some((text) => text?.includes('Song One'))).toBe(true);
		expect(rows.some((text) => text?.includes('Song Two'))).toBe(false);
	});
});

describe('SongList share inventory', () => {
	async function showShares(items: ShareInventoryItem[]): Promise<HTMLElement> {
		fetchShares.mockResolvedValueOnce({
			items,
			total: items.length,
			offset: 0,
			limit: 50,
			has_more: false
		});
		const target = render();
		await tick();
		openSharesInventory();
		await tick();
		await Promise.resolve();
		await tick();
		return target;
	}

	it('hydrates an inventory album that is not in albumList', async () => {
		const remote = album({
			id: 'a-remote',
			title: 'Remote Shared',
			is_shared: true,
			share_slug: 'slug-album'
		});
		fetchAlbum.mockResolvedValue(remote);
		const target = await showShares([
			shareItem({
				type: 'album',
				id: 'a-remote',
				title: 'Remote Shared',
				share_slug: 'slug-album',
				public_path: '/share/album/slug-album'
			})
		]);
		const open = [...target.querySelectorAll('button')].find(
			(button) => button.getAttribute('aria-label') === `${LIBRARY_SHARES_OPEN_LABEL} Remote Shared`
		);
		expect(open).toBeDefined();
		open?.click();
		await Promise.resolve();
		await Promise.resolve();
		await tick();
		expect(get(albumList).some((item) => item.id === 'a-remote')).toBe(true);
		expect(get(selectedAlbumId)).toBe('a-remote');
	});

	it('clears is_shared on an inventory album already in albumList', async () => {
		albumList.set([
			album({ id: 'a-local', title: 'Local Album', is_shared: true, share_slug: 'slug-local' })
		]);
		const target = await showShares([
			shareItem({
				type: 'album',
				id: 'a-local',
				title: 'Local Album',
				share_slug: 'slug-local',
				public_path: '/share/album/slug-local'
			})
		]);
		const unshare = [...target.querySelectorAll('button')].find(
			(button) => button.getAttribute('aria-label') === LIBRARY_SHARES_UNSHARE_LABEL
		);
		expect(unshare).toBeDefined();
		unshare?.click();
		await tick();
		const confirm = target.querySelector('.confirm-btn');
		expect(confirm).toBeInstanceOf(HTMLButtonElement);
		(confirm as HTMLButtonElement).click();
		await Promise.resolve();
		await Promise.resolve();
		await tick();
		const updated = get(albumList).find((item) => item.id === 'a-local');
		expect(updated?.is_shared).toBe(false);
		expect(updated?.share_slug).toBeNull();
	});
});
