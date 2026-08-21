import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, SongItem } from '$lib/api/types';
import { LIBRARY_SEARCH_DEBOUNCE_MS, LIBRARY_SEARCH_PAGE_SIZE } from '$lib/constants';
import { searchQuery } from '$lib/stores/filter';
import { albumList, songList } from '$lib/stores/player';

const searchLibrary = vi.fn();
const fetchAlbums = vi.fn();
const fetchSongs = vi.fn();

vi.mock('$lib/api/library', () => ({
	searchLibrary: (...args: unknown[]) => searchLibrary(...args)
}));
vi.mock('$lib/api/albums', () => ({
	fetchAlbums: (...args: unknown[]) => fetchAlbums(...args)
}));
vi.mock('$lib/api/songs', () => ({
	fetchSongs: (...args: unknown[]) => fetchSongs(...args)
}));

import {
	changeLibrarySort,
	groupSearchHits,
	librarySearch,
	libraryBrowse,
	loadLibraryBrowse,
	loadMoreLibrarySearch,
	resetLibrarySearchForTests,
	restoreLibraryBrowse,
	restoreLibrarySearch,
	retryLibrarySearch,
	syncLibrarySearch
} from './librarySearch';

function album(overrides: Partial<AlbumItem> = {}): AlbumItem {
	return {
		id: 'a1',
		title: 'Nachtstrom',
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
		id: 's1',
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

beforeEach(() => {
	vi.useFakeTimers();
	searchLibrary.mockReset();
	fetchAlbums.mockReset();
	fetchSongs.mockReset();
	resetLibrarySearchForTests();
	searchQuery.set('');
	albumList.set([album({ id: 'a-local', title: 'Local Album' })]);
	songList.set([song()]);
});

afterEach(() => {
	vi.useRealTimers();
	resetLibrarySearchForTests();
});

describe('syncLibrarySearch', () => {
	it('does not call the server for an empty query', async () => {
		syncLibrarySearch('   ');
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		expect(searchLibrary).not.toHaveBeenCalled();
		expect(get(librarySearch).status).toBe('idle');
	});

	it('debounces then searches the server instead of the loaded song list', async () => {
		searchLibrary.mockResolvedValue({
			items: [
				{
					type: 'album',
					album: album()
				}
			],
			next_cursor: null,
			has_more: false
		});
		syncLibrarySearch('Nachtstrom');
		expect(searchLibrary).not.toHaveBeenCalled();
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		expect(searchLibrary).toHaveBeenCalledWith({
			q: 'Nachtstrom',
			sort: 'newest',
			limit: LIBRARY_SEARCH_PAGE_SIZE,
			cursor: null
		});
		expect(get(librarySearch).items).toHaveLength(1);
		expect(get(librarySearch).items[0]).toMatchObject({ type: 'album' });
		expect(get(songList)[0].title).toBe('Local Only');
	});

	it('ignores a stale response after the query is cleared', async () => {
		let resolveSearch: (value: unknown) => void = () => {};
		searchLibrary.mockReturnValue(
			new Promise((resolve) => {
				resolveSearch = resolve;
			})
		);
		syncLibrarySearch('Nachtstrom');
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		syncLibrarySearch('');
		resolveSearch({
			items: [{ type: 'album', album: album() }],
			next_cursor: null,
			has_more: false
		});
		await Promise.resolve();
		expect(get(librarySearch).status).toBe('idle');
		expect(get(librarySearch).items).toEqual([]);
	});

	it('records an error without swallowing it and retries the same query', async () => {
		searchLibrary.mockRejectedValueOnce(new Error('boom'));
		syncLibrarySearch('Tide');
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		expect(get(librarySearch).status).toBe('error');
		expect(get(librarySearch).error).toBe('boom');
		searchLibrary.mockResolvedValueOnce({
			items: [],
			next_cursor: null,
			has_more: false
		});
		retryLibrarySearch();
		await Promise.resolve();
		await Promise.resolve();
		expect(searchLibrary).toHaveBeenCalledTimes(2);
		expect(get(librarySearch).status).toBe('ready');
	});

	it('load more appends using the next cursor', async () => {
		searchLibrary.mockResolvedValueOnce({
			items: [{ type: 'album', album: album({ id: 'a1' }) }],
			next_cursor: 'cursor-1',
			has_more: true
		});
		syncLibrarySearch('Catalog');
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		searchLibrary.mockResolvedValueOnce({
			items: [{ type: 'album', album: album({ id: 'a2', title: 'Catalog 2' }) }],
			next_cursor: null,
			has_more: false
		});
		loadMoreLibrarySearch();
		await Promise.resolve();
		await Promise.resolve();
		expect(searchLibrary).toHaveBeenLastCalledWith({
			q: 'Catalog',
			sort: 'newest',
			limit: LIBRARY_SEARCH_PAGE_SIZE,
			cursor: 'cursor-1'
		});
		expect(get(librarySearch).items).toHaveLength(2);
		expect(get(librarySearch).hasMore).toBe(false);
	});

	it('restoreLibrarySearch replays pages until the saved count is loaded', async () => {
		searchLibrary
			.mockResolvedValueOnce({
				items: [{ type: 'album', album: album({ id: 'a1' }) }],
				next_cursor: 'cursor-1',
				has_more: true
			})
			.mockResolvedValueOnce({
				items: [{ type: 'album', album: album({ id: 'a2', title: 'Catalog 2' }) }],
				next_cursor: null,
				has_more: false
			});
		await restoreLibrarySearch('Catalog', 'newest', 2);
		expect(searchLibrary).toHaveBeenCalledTimes(2);
		expect(get(librarySearch).items).toHaveLength(2);
		syncLibrarySearch('Catalog');
		expect(searchLibrary).toHaveBeenCalledTimes(2);
	});

	it('does not re-fetch a restored search that already settled with zero hits', async () => {
		searchLibrary.mockResolvedValue({ items: [], next_cursor: null, has_more: false });
		await restoreLibrarySearch('zzz', 'newest', 0);
		expect(searchLibrary).toHaveBeenCalledTimes(1);
		expect(get(librarySearch).status).toBe('ready');
		expect(get(librarySearch).items).toHaveLength(0);
		syncLibrarySearch('zzz');
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		expect(searchLibrary).toHaveBeenCalledTimes(1);
	});
});

describe('changeLibrarySort', () => {
	it('re-searches immediately when a query is active', async () => {
		searchLibrary.mockResolvedValue({ items: [], next_cursor: null, has_more: false });
		syncLibrarySearch('Nachtstrom');
		await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
		searchLibrary.mockClear();
		changeLibrarySort('title', 'Nachtstrom');
		expect(searchLibrary).toHaveBeenCalledWith({
			q: 'Nachtstrom',
			sort: 'title',
			limit: LIBRARY_SEARCH_PAGE_SIZE,
			cursor: null
		});
	});
});

describe('restoreLibraryBrowse', () => {
	it('replays pages until the saved offsets are loaded', async () => {
		fetchAlbums
			.mockResolvedValueOnce({
				items: [album({ id: 'a1' })],
				total: 2,
				offset: 0,
				limit: 50,
				has_more: true
			})
			.mockResolvedValueOnce({
				items: [album({ id: 'a2', title: 'Second' })],
				total: 2,
				offset: 1,
				limit: 50,
				has_more: false
			});
		fetchSongs
			.mockResolvedValueOnce({
				items: [song({ id: 's1' })],
				total: 1,
				offset: 0,
				limit: 200,
				has_more: false
			})
			.mockResolvedValueOnce({
				items: [],
				total: 1,
				offset: 1,
				limit: 200,
				has_more: false
			});
		await restoreLibraryBrowse('newest', 2, 1);
		expect(fetchAlbums).toHaveBeenCalledTimes(2);
		expect(get(libraryBrowse).albumOffset).toBe(2);
		expect(get(albumList).map((item) => item.id)).toEqual(['a1', 'a2']);
	});

	it('stops paging a resource once it is exhausted even if the other target remains', async () => {
		fetchAlbums.mockResolvedValue({
			items: [album({ id: 'a1' })],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		fetchSongs
			.mockResolvedValueOnce({
				items: [song({ id: 's1' })],
				total: 1,
				offset: 0,
				limit: 200,
				has_more: false
			})
			.mockResolvedValueOnce({
				items: [],
				total: 1,
				offset: 1,
				limit: 200,
				has_more: false
			});
		await restoreLibraryBrowse('newest', 50, 1);
		expect(fetchAlbums).toHaveBeenCalledTimes(1);
		expect(fetchSongs).toHaveBeenCalledTimes(1);
	});
});

describe('loadLibraryBrowse', () => {
	it('keeps browse offsets independent of songs appended from search', async () => {
		fetchAlbums.mockResolvedValue({
			items: [album({ id: 'a-page' })],
			total: 2,
			offset: 0,
			limit: 50,
			has_more: true
		});
		fetchSongs.mockResolvedValue({
			items: [song({ id: 's-page' })],
			total: 2,
			offset: 0,
			limit: 200,
			has_more: true
		});
		await loadLibraryBrowse({ reset: true });
		expect(get(libraryBrowse).songOffset).toBe(1);

		songList.update((songs) => [...songs, song({ id: 's-search-only' })]);
		fetchAlbums.mockResolvedValue({
			items: [],
			total: 2,
			offset: 1,
			limit: 50,
			has_more: false
		});
		fetchSongs.mockResolvedValue({
			items: [song({ id: 's-page-2' })],
			total: 2,
			offset: 1,
			limit: 200,
			has_more: false
		});
		await loadLibraryBrowse({ reset: false });
		expect(fetchSongs).toHaveBeenLastCalledWith(undefined, 1, expect.any(Number), {
			sort: 'newest'
		});
		expect(get(libraryBrowse).songOffset).toBe(2);
	});
});

describe('groupSearchHits', () => {
	it('keeps album hits without matching songs and attaches song hits to album context', () => {
		const groups = groupSearchHits([
			{ type: 'album', album: album({ id: 'nachtstrom', title: 'Nachtstrom' }) },
			{
				type: 'song',
				song: song({ id: 's-tide', title: 'Tide', album_id: 'nachtstrom' }),
				album_id: 'nachtstrom',
				album_title: 'Nachtstrom'
			},
			{
				type: 'song',
				song: song({ id: 's-other', title: 'Other', album_id: 'other', album_title: 'Other' }),
				album_id: 'other',
				album_title: 'Other'
			}
		]);
		expect(groups).toHaveLength(2);
		expect(groups[0].album.title).toBe('Nachtstrom');
		expect(groups[0].songs.map((s) => s.id)).toEqual(['s-tide']);
		expect(groups[1].album.id).toBe('other');
		expect(groups[1].album.title).toBe('Other');
		expect(groups[1].songs).toHaveLength(1);
		expect(groups[1].album.song_count).toBe(1);
	});
});
