import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, PlaylistDetailItem, SongItem } from '$lib/api/types';
import { LIBRARY_HISTORY_KIND } from '$lib/constants';
import { openCollection } from '$lib/stores/collection';
import { searchQuery } from '$lib/stores/filter';
import { libraryBrowse, librarySort, resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { albumList, selectedGenerationId, selectedSongId, songList } from '$lib/stores/player';
import {
	playlistLoad,
	resetPlaylistsForTests,
	selectedPlaylistDetail
} from '$lib/stores/playlists';
import { resetSharesForTests, sharesViewOpen } from '$lib/stores/shares';

const fetchPlaylists = vi.fn();
const fetchPlaylist = vi.fn();
const fetchAlbum = vi.fn();
const fetchAlbums = vi.fn();
const fetchSong = vi.fn();
const fetchSongs = vi.fn();
const searchLibrary = vi.fn();
const fetchShares = vi.fn();

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
	fetchPlaylist: (...args: unknown[]) => fetchPlaylist(...args),
	fetchSongs: (...args: unknown[]) => fetchSongs(...args),
	createPlaylist: vi.fn(),
	deletePlaylistApi: vi.fn(),
	updatePlaylist: vi.fn(),
	addGenerationToPlaylist: vi.fn(),
	addSongToPlaylist: vi.fn(),
	addAlbumToPlaylist: vi.fn(),
	removeFromPlaylist: vi.fn(),
	reorderPlaylistEntry: vi.fn()
}));

import {
	albumIsExpanded,
	applyLibraryHistory,
	captureLibraryScroll,
	isLibraryHistoryState,
	libraryRootState,
	libraryScrollAnchor,
	libraryFilter,
	resetLibraryContextForTests,
	setLibraryFilter,
	snapshotLibraryHistory
} from './libraryContext';

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
		title: 'Tide',
		album_id: 'a1',
		album_title: 'Nachtstrom',
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

function playlistDetail(overrides: Partial<PlaylistDetailItem> = {}): PlaylistDetailItem {
	return {
		id: 'p1',
		title: 'P',
		entry_count: 0,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		entries: [],
		...overrides
	};
}

function emptyPage<T>(items: T[] = []) {
	return { items, total: items.length, offset: 0, limit: 50, has_more: false };
}

beforeEach(() => {
	fetchPlaylists.mockReset();
	fetchPlaylist.mockReset();
	fetchAlbum.mockReset();
	fetchAlbums.mockReset();
	fetchSong.mockReset();
	fetchSongs.mockReset();
	searchLibrary.mockReset();
	fetchShares.mockReset();
	fetchShares.mockResolvedValue(emptyPage());
	fetchPlaylists.mockResolvedValue([]);
	fetchPlaylist.mockResolvedValue(playlistDetail());
	fetchAlbums.mockResolvedValue(emptyPage());
	fetchSongs.mockResolvedValue({ ...emptyPage(), limit: 200 });
	searchLibrary.mockResolvedValue({ items: [], next_cursor: null, has_more: false });
	fetchAlbum.mockResolvedValue(album({ id: 'a9', title: 'Remote' }));
	fetchSong.mockResolvedValue(song({ id: 's9', album_id: 'a9', album_title: 'Remote' }));
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetSharesForTests();
	resetPlaylistsForTests();
	searchQuery.set('');
	albumList.set([]);
	songList.set([]);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	playlistLoad.set({ status: 'idle', error: null });
	history.replaceState(null, '', '/');
});

afterEach(() => {
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetSharesForTests();
	resetPlaylistsForTests();
});

describe('albumIsExpanded', () => {
	it('expands search groups with song hits only', () => {
		expect(albumIsExpanded({ searching: false, songHits: 2 })).toBe(false);
		expect(albumIsExpanded({ searching: true, songHits: 1 })).toBe(true);
		expect(albumIsExpanded({ searching: true, songHits: 0 })).toBe(false);
	});
});

describe('library history snapshot', () => {
	it('round-trips filter, query, sort, collection, and scroll', () => {
		setLibraryFilter('playlists');
		searchQuery.set('Tide');
		librarySort.set('oldest');
		selectedSongId.set('s1');
		captureLibraryScroll(240);
		libraryBrowse.set({
			status: 'ready',
			error: null,
			albumHasMore: true,
			songHasMore: false,
			albumOffset: 50,
			songOffset: 200
		});

		const snap = snapshotLibraryHistory(3);
		expect(snap).toMatchObject({
			kind: LIBRARY_HISTORY_KIND,
			index: 3,
			filter: 'playlists',
			surface: 'browse',
			query: 'Tide',
			sort: 'oldest',
			albumOffset: 50,
			songOffset: 200,
			songId: 's1',
			scrollAnchor: 240,
			detailTab: 'generations'
		});
		expect(isLibraryHistoryState(snap)).toBe(true);
	});

	it('rejects legacy section-based blobs so restore falls back to root', () => {
		expect(isLibraryHistoryState(null)).toBe(false);
		expect(
			isLibraryHistoryState({
				...libraryRootState(),
				filter: undefined,
				section: 'albums',
				browseTrackAlbumId: null
			})
		).toBe(false);
		expect(isLibraryHistoryState(libraryRootState())).toBe(true);
	});

	it('rejects a malformed collection snapshot', () => {
		expect(
			isLibraryHistoryState({ ...libraryRootState(), collection: { kind: 'song', id: 'x' } })
		).toBe(false);
		expect(
			isLibraryHistoryState({ ...libraryRootState(), collection: { kind: 'album', id: 'a1' } })
		).toBe(true);
	});
});

describe('setLibraryFilter', () => {
	it('replaces the filter without touching the open collection', () => {
		openCollection.set({ kind: 'album', id: 'a1' });
		setLibraryFilter('playlists');
		expect(get(libraryFilter)).toBe('playlists');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('opens the shares inventory for the shared filter and closes it otherwise', () => {
		setLibraryFilter('shared');
		expect(get(sharesViewOpen)).toBe(true);
		setLibraryFilter('albums');
		expect(get(sharesViewOpen)).toBe(false);
	});

	it('restores the remembered scroll position per filter', () => {
		libraryScrollAnchor.set(120);
		setLibraryFilter('playlists');
		captureLibraryScroll(0);
		setLibraryFilter('albums');
		expect(get(libraryScrollAnchor)).toBe(120);
	});
});

describe('applyLibraryHistory', () => {
	it('hydrates an album collection that is not yet loaded', async () => {
		const state = { ...libraryRootState(), collection: { kind: 'album' as const, id: 'a9' } };
		await applyLibraryHistory(state);
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a9' });
		expect(get(albumList).some((a) => a.id === 'a9')).toBe(true);
	});

	it('hydrates a playlist collection via loadPlaylistDetail', async () => {
		fetchPlaylist.mockResolvedValueOnce(playlistDetail({ id: 'p1', title: 'Night Drive' }));
		const state = { ...libraryRootState(), collection: { kind: 'playlist' as const, id: 'p1' } };
		await applyLibraryHistory(state);
		expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p1' });
		expect(get(selectedPlaylistDetail)?.title).toBe('Night Drive');
	});

	it('clears a playlist collection that no longer exists', async () => {
		const { ApiError } = await import('$lib/api/fetch');
		fetchPlaylist.mockRejectedValueOnce(new ApiError(404, 'gone', '/api/playlists/gone'));
		const state = { ...libraryRootState(), collection: { kind: 'playlist' as const, id: 'gone' } };
		await applyLibraryHistory(state);
		expect(get(openCollection)).toBeNull();
		expect(get(selectedPlaylistDetail)).toBeNull();
	});
});
