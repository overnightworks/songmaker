import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { LIBRARY_DEFAULT_SECTION, LIBRARY_HISTORY_KIND } from '$lib/constants';
import { searchQuery } from '$lib/stores/filter';
import { libraryBrowse, librarySort, resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { selectedAlbumId, selectedGenerationId, selectedSongId } from '$lib/stores/player';
import { playlistLoad, selectedPlaylistId } from '$lib/stores/playlists';

const fetchPlaylists = vi.fn();
const fetchPlaylist = vi.fn();

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
	isLibraryHistoryState,
	libraryBrowseStateFrom,
	libraryRootState,
	libraryScrollAnchor,
	librarySection,
	resetLibraryContextForTests,
	setLibrarySection,
	snapshotLibraryHistory,
	toggleAlbumExpanded
} from './libraryContext';

beforeEach(() => {
	fetchPlaylists.mockReset();
	fetchPlaylist.mockReset();
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
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	searchQuery.set('');
	selectedAlbumId.set(null);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	selectedPlaylistId.set(null);
	playlistLoad.set({ status: 'idle', error: null });
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

	it('apply restores stores from a snapshot', () => {
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
		applyLibraryHistory(state);
		expect(get(librarySection)).toBe('shared');
		expect(get(searchQuery)).toBe('Nachtstrom');
		expect(get(librarySort)).toBe('title');
		expect(get(selectedAlbumId)).toBe('a9');
		expect(get(selectedSongId)).toBe('s9');
		expect(get(expandedAlbumIds).has('a9')).toBe(true);
		expect(get(libraryScrollAnchor)).toBe(80);
		expect(fetchPlaylists).toHaveBeenCalled();
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
