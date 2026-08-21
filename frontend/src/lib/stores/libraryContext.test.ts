import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, SongItem } from '$lib/api/types';
import { LIBRARY_DEFAULT_SECTION, LIBRARY_HISTORY_KIND } from '$lib/constants';
import { searchQuery } from '$lib/stores/filter';
import {
	libraryBrowse,
	librarySearch,
	librarySort,
	resetLibrarySearchForTests
} from '$lib/stores/librarySearch';
import {
	albumList,
	selectedAlbumId,
	selectedGenerationId,
	selectedSongId,
	songList
} from '$lib/stores/player';
import { playlistLoad, selectedPlaylistId } from '$lib/stores/playlists';

const fetchPlaylists = vi.fn();
const fetchPlaylist = vi.fn();
const fetchAlbum = vi.fn();
const fetchAlbums = vi.fn();
const fetchSong = vi.fn();
const fetchSongs = vi.fn();
const searchLibrary = vi.fn();

vi.mock('$lib/api/library', () => ({
	searchLibrary: (...args: unknown[]) => searchLibrary(...args)
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
	expandAlbum,
	expandedAlbumIds,
	hydrateLibraryFromHistory,
	isLibraryHistoryState,
	libraryBrowseStateFrom,
	libraryRootState,
	libraryScrollAnchor,
	librarySection,
	librarySurface,
	resetLibraryContextForTests,
	setLibrarySection,
	snapshotLibraryHistory,
	toggleAlbumExpanded
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

function emptyPage<T>(items: T[] = []) {
	return {
		items,
		total: items.length,
		offset: 0,
		limit: 50,
		has_more: false
	};
}

beforeEach(() => {
	fetchPlaylists.mockReset();
	fetchPlaylist.mockReset();
	fetchAlbum.mockReset();
	fetchAlbums.mockReset();
	fetchSong.mockReset();
	fetchSongs.mockReset();
	searchLibrary.mockReset();
	fetchPlaylists.mockResolvedValue([]);
	fetchPlaylist.mockResolvedValue({
		id: 'p1',
		title: 'P',
		entry_count: 0,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		entries: []
	});
	fetchAlbums.mockResolvedValue(emptyPage());
	fetchSongs.mockResolvedValue({ ...emptyPage(), limit: 200 });
	searchLibrary.mockResolvedValue({ items: [], next_cursor: null, has_more: false });
	fetchAlbum.mockResolvedValue(album({ id: 'a9', title: 'Remote' }));
	fetchSong.mockResolvedValue(song({ id: 's9', album_id: 'a9', album_title: 'Remote' }));
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	searchQuery.set('');
	albumList.set([]);
	songList.set([]);
	selectedAlbumId.set(null);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	selectedPlaylistId.set(null);
	playlistLoad.set({ status: 'idle', error: null });
	history.replaceState(null, '', '/');
});

afterEach(() => {
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
});

describe('albumIsExpanded', () => {
	it('keeps albums collapsed until selected, toggled, or a search hit lists songs', () => {
		const expanded = new Set<string>();
		expect(
			albumIsExpanded('a1', expanded, { selectedAlbumId: null, searching: false, songHits: 2 })
		).toBe(false);
		expect(
			albumIsExpanded('a1', expanded, { selectedAlbumId: 'a1', searching: false, songHits: 2 })
		).toBe(true);
		expect(
			albumIsExpanded('a1', new Set(['a1']), {
				selectedAlbumId: null,
				searching: false,
				songHits: 0
			})
		).toBe(true);
		expect(
			albumIsExpanded('a1', expanded, { selectedAlbumId: null, searching: true, songHits: 1 })
		).toBe(true);
		expect(
			albumIsExpanded('a1', expanded, { selectedAlbumId: null, searching: true, songHits: 0 })
		).toBe(false);
	});
});

describe('library history snapshot', () => {
	it('round-trips section, query, sort, selection, and scroll', () => {
		setLibrarySection('playlists');
		searchQuery.set('Tide');
		librarySort.set('oldest');
		selectedAlbumId.set('a1');
		selectedSongId.set('s1');
		expandAlbum('a1');
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
			section: 'playlists',
			surface: 'browse',
			query: 'Tide',
			sort: 'oldest',
			albumOffset: 50,
			songOffset: 200,
			albumId: 'a1',
			songId: 's1',
			expandedAlbumIds: ['a1'],
			scrollAnchor: 240
		});
		expect(isLibraryHistoryState(snap)).toBe(true);
	});

	it('rejects unknown history payloads instead of guessing a section', () => {
		expect(isLibraryHistoryState(null)).toBe(false);
		expect(isLibraryHistoryState({ kind: LIBRARY_HISTORY_KIND, section: 'queue' })).toBe(false);
		expect(isLibraryHistoryState(libraryRootState())).toBe(true);
	});

	it('apply restores stores from a snapshot', async () => {
		const state = {
			...libraryRootState(),
			section: 'shared' as const,
			query: 'Nachtstrom',
			sort: 'title' as const,
			albumId: 'a9',
			songId: 's9',
			expandedAlbumIds: ['a9'],
			scrollAnchor: 80
		};
		await applyLibraryHistory(state);
		expect(get(librarySection)).toBe('shared');
		expect(get(librarySurface)).toBe('browse');
		expect(get(searchQuery)).toBe('Nachtstrom');
		expect(get(librarySort)).toBe('title');
		expect(get(selectedAlbumId)).toBe('a9');
		expect(get(selectedSongId)).toBe('s9');
		expect(get(expandedAlbumIds).has('a9')).toBe(true);
		expect(get(libraryScrollAnchor)).toBe(80);
		expect(fetchPlaylists).toHaveBeenCalled();
	});

	it('restores browse pages even when a search query is replayed', async () => {
		fetchAlbums.mockResolvedValue(emptyPage([album()]));
		searchLibrary.mockResolvedValue({
			items: [{ type: 'album', album: album({ id: 'a-hit' }) }],
			next_cursor: null,
			has_more: false
		});
		await applyLibraryHistory({ ...libraryRootState(), query: 'Tide' });
		expect(fetchAlbums).toHaveBeenCalled();
		expect(searchLibrary).toHaveBeenCalled();
		expect(get(albumList).map((item) => item.id)).toEqual(['a1']);
		expect(get(librarySearch).items).toHaveLength(1);
	});

	it('fetches a selected album that is not on the restored browse pages', async () => {
		await applyLibraryHistory({
			...libraryRootState(),
			surface: 'detail',
			albumId: 'a9'
		});
		expect(fetchAlbum).toHaveBeenCalledWith('a9');
		expect(get(albumList).some((item) => item.id === 'a9')).toBe(true);
		expect(get(librarySurface)).toBe('detail');
	});

	it('clears a deleted playlist and falls back to browse', async () => {
		fetchPlaylist.mockRejectedValueOnce(new Error('not found'));
		await applyLibraryHistory({
			...libraryRootState(),
			surface: 'detail',
			section: 'playlists',
			playlistId: 'p-gone'
		});
		expect(get(selectedPlaylistId)).toBeNull();
		expect(get(librarySurface)).toBe('browse');
	});

	it('does not snapshot a previous search page count onto a new query', () => {
		searchQuery.set('new');
		librarySearch.set({
			q: 'old',
			status: 'ready',
			error: null,
			items: [
				{ type: 'album', album: album({ id: 'a1' }) },
				{ type: 'album', album: album({ id: 'a2' }) }
			],
			hasMore: true,
			nextCursor: 'cursor-old'
		});
		const snap = snapshotLibraryHistory(1);
		expect(snap.query).toBe('new');
		expect(snap.searchLoadedCount).toBe(0);
		expect(snap.searchCursor).toBeNull();
	});

	it('replaces history after hydrate so a deleted playlist is not replayed', async () => {
		history.replaceState(
			{
				...libraryRootState(),
				surface: 'detail',
				section: 'playlists',
				playlistId: 'p-gone'
			},
			'',
			'/'
		);
		fetchPlaylist.mockRejectedValueOnce(new Error('not found'));
		await hydrateLibraryFromHistory();
		expect(history.state.playlistId).toBeNull();
		expect(history.state.surface).toBe('browse');
	});

	it('browse-from-current clears the resource but keeps section, query, sort, and scroll', () => {
		const current = snapshotLibraryHistory(2);
		const next = {
			...current,
			section: 'playlists' as const,
			query: 'x',
			sort: 'oldest' as const,
			songId: 's1',
			scrollAnchor: 12
		};
		const browse = libraryBrowseStateFrom(next);
		expect(browse.songId).toBeNull();
		expect(browse.albumId).toBeNull();
		expect(browse.section).toBe('playlists');
		expect(browse.query).toBe('x');
		expect(browse.sort).toBe('oldest');
		expect(browse.scrollAnchor).toBe(12);
	});
});

describe('setLibrarySection', () => {
	it('defaults to albums and only loads playlists when that section is chosen', () => {
		expect(get(librarySection)).toBe(LIBRARY_DEFAULT_SECTION);
		expect(fetchPlaylists).not.toHaveBeenCalled();
		setLibrarySection('albums');
		expect(fetchPlaylists).not.toHaveBeenCalled();
		setLibrarySection('playlists');
		expect(fetchPlaylists).toHaveBeenCalled();
	});

	it('toggleAlbumExpanded adds and removes without expanding the rest', () => {
		toggleAlbumExpanded('a1');
		expect([...get(expandedAlbumIds)]).toEqual(['a1']);
		toggleAlbumExpanded('a2');
		expect(get(expandedAlbumIds).has('a1')).toBe(true);
		expect(get(expandedAlbumIds).has('a2')).toBe(true);
		toggleAlbumExpanded('a1');
		expect(get(expandedAlbumIds).has('a1')).toBe(false);
		expect(get(expandedAlbumIds).has('a2')).toBe(true);
	});
});
