import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { ApiError } from '$lib/api/fetch';
import type { AlbumItem, GenerationItem, SongItem } from '$lib/api/types';
import {
	LIBRARY_DEFAULT_SECTION,
	LIBRARY_HISTORY_KIND,
	LIBRARY_SEARCH_DEBOUNCE_MS,
	LIBRARY_SHARES_HISTORY_SECTION
} from '$lib/constants';
import { searchQuery } from '$lib/stores/filter';
import {
	libraryBrowse,
	librarySearch,
	librarySort,
	resetLibrarySearchForTests,
	syncLibrarySearch
} from '$lib/stores/librarySearch';
import {
	albumList,
	selectedAlbumId,
	selectedGenerationId,
	selectedSongId,
	songList
} from '$lib/stores/player';
import { playlistLoad, selectedPlaylistId } from '$lib/stores/playlists';
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
	browseTrackAlbumId,
	captureLibraryScroll,
	closeSharesView,
	detailTab,
	expandAlbum,
	expandedAlbumIds,
	hydrateLibraryFromHistory,
	isLibraryHistoryState,
	libraryBrowseStateFrom,
	libraryRootState,
	libraryScrollAnchor,
	libraryScrollBySection,
	librarySection,
	librarySurface,
	openSharesView,
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

function generation(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's9',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
		mp3_path: '/audio/g1.mp3',
		wav_path: null,
		seed: 1,
		status: 'complete',
		is_archived: false,
		is_picked: false,
		is_kept: false,
		is_shared: false,
		model_mode: 'base',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: null,
		scores: null,
		generation_params: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
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
	fetchShares.mockReset();
	fetchShares.mockResolvedValue({
		items: [],
		total: 0,
		offset: 0,
		limit: 50,
		has_more: false
	});
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
	resetSharesForTests();
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
	resetSharesForTests();
});

describe('albumIsExpanded', () => {
	it('expands search groups with song hits, not Studio browse', () => {
		expect(albumIsExpanded({ searching: false, songHits: 2 })).toBe(false);
		expect(albumIsExpanded({ searching: false, songHits: 0 })).toBe(false);
		expect(albumIsExpanded({ searching: true, songHits: 1 })).toBe(true);
		expect(albumIsExpanded({ searching: true, songHits: 0 })).toBe(false);
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
			browseTrackAlbumId: null,
			expandedAlbumIds: ['a1'],
			scrollAnchor: 240,
			detailTab: 'generations'
		});
		expect(isLibraryHistoryState(snap)).toBe(true);
	});

	it('accepts older history blobs without browseTrackAlbumId', () => {
		const { browseTrackAlbumId: _browse, ...withoutBrowse } = libraryRootState();
		expect(_browse).toBeNull();
		expect(isLibraryHistoryState(withoutBrowse)).toBe(true);
	});

	it('rejects unknown history payloads instead of guessing a section', () => {
		expect(isLibraryHistoryState(null)).toBe(false);
		expect(isLibraryHistoryState({ kind: LIBRARY_HISTORY_KIND, section: 'queue' })).toBe(false);
		expect(isLibraryHistoryState(libraryRootState())).toBe(true);
		expect(
			isLibraryHistoryState({ ...libraryRootState(), section: LIBRARY_SHARES_HISTORY_SECTION })
		).toBe(true);
		const { detailTab: _detailTab, ...withoutDetailTab } = libraryRootState();
		expect(_detailTab).toBe('generations');
		expect(isLibraryHistoryState(withoutDetailTab)).toBe(true);
		expect(isLibraryHistoryState({ ...libraryRootState(), detailTab: 'lyrics' })).toBe(false);
	});

	it('apply restores stores from a snapshot', async () => {
		const state = {
			...libraryRootState(),
			section: LIBRARY_SHARES_HISTORY_SECTION,
			query: 'Nachtstrom',
			sort: 'title' as const,
			albumId: 'a9',
			songId: 's9',
			expandedAlbumIds: ['a9'],
			scrollAnchor: 80
		};
		await applyLibraryHistory(state);
		expect(get(librarySection)).toBe(LIBRARY_DEFAULT_SECTION);
		expect(get(sharesViewOpen)).toBe(true);
		expect(get(librarySurface)).toBe('browse');
		expect(get(searchQuery)).toBe('Nachtstrom');
		expect(get(librarySort)).toBe('title');
		expect(get(selectedAlbumId)).toBe('a9');
		expect(get(selectedSongId)).toBe('s9');
		expect(get(expandedAlbumIds).has('a9')).toBe(true);
		expect(get(libraryScrollAnchor)).toBe(80);
		expect(fetchPlaylists).not.toHaveBeenCalled();
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
		fetchPlaylist.mockRejectedValueOnce(new ApiError(404, 'not found', '/api/playlists/p-gone'));
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

	it('replaces a browse summary with the full selected song after restore', async () => {
		const summary = song({ id: 's9', album_id: 'a9', generation_count: 1, generations: [] });
		fetchSongs.mockResolvedValue({ ...emptyPage([summary]), limit: 200 });
		fetchSong.mockResolvedValue(
			song({
				id: 's9',
				album_id: 'a9',
				generation_count: 1,
				generations: [generation({ id: 'g1', song_id: 's9' })]
			})
		);
		await applyLibraryHistory({
			...libraryRootState(),
			surface: 'detail',
			albumId: 'a9',
			songId: 's9'
		});
		expect(fetchSong).toHaveBeenCalledWith('s9');
		expect(
			get(songList)
				.find((item) => item.id === 's9')
				?.generations.map((item) => item.id)
		).toEqual(['g1']);
	});

	it('fetches the selected song when retained takes are fewer than generation_count', async () => {
		const summary = song({
			id: 's9',
			album_id: 'a9',
			generation_count: 2,
			generations: []
		});
		songList.set([
			song({
				id: 's9',
				album_id: 'a9',
				generation_count: 1,
				generations: [generation({ id: 'g1', song_id: 's9' })]
			})
		]);
		fetchSongs.mockResolvedValue({ ...emptyPage([summary]), limit: 200 });
		fetchSong.mockResolvedValue(
			song({
				id: 's9',
				album_id: 'a9',
				generation_count: 2,
				generations: [
					generation({ id: 'g1', song_id: 's9' }),
					generation({ id: 'g2', song_id: 's9' })
				]
			})
		);
		await applyLibraryHistory({
			...libraryRootState(),
			surface: 'detail',
			albumId: 'a9',
			songId: 's9'
		});
		expect(fetchSong).toHaveBeenCalledWith('s9');
		expect(
			get(songList)
				.find((item) => item.id === 's9')
				?.generations.map((item) => item.id)
		).toEqual(['g1', 'g2']);
	});

	it('lets a newer history restore win over an in-flight playlist fetch', async () => {
		let resolveFirst: ((value: unknown) => void) | undefined;
		fetchPlaylist.mockImplementationOnce(
			() =>
				new Promise((resolve) => {
					resolveFirst = resolve;
				})
		);
		fetchPlaylist.mockResolvedValue({
			id: 'p2',
			title: 'Second',
			entry_count: 0,
			is_shared: false,
			share_slug: null,
			created_at: '2026-01-01T00:00:00+00:00',
			entries: []
		});
		const first = applyLibraryHistory({
			...libraryRootState(),
			surface: 'detail',
			section: 'playlists',
			playlistId: 'p1'
		});
		const second = applyLibraryHistory({
			...libraryRootState(),
			surface: 'detail',
			section: 'playlists',
			playlistId: 'p2'
		});
		await second;
		resolveFirst?.({
			id: 'p1',
			title: 'First',
			entry_count: 0,
			is_shared: false,
			share_slug: null,
			created_at: '2026-01-01T00:00:00+00:00',
			entries: []
		});
		await first;
		expect(get(selectedPlaylistId)).toBe('p2');
	});

	it('keeps restoring after a transient playlist-detail failure', async () => {
		fetchPlaylist.mockRejectedValueOnce(new ApiError(500, 'boom', '/api/playlists/p1'));
		fetchAlbums.mockResolvedValue(emptyPage([album()]));
		await applyLibraryHistory({
			...libraryRootState(),
			surface: 'detail',
			section: 'playlists',
			playlistId: 'p1'
		});
		expect(get(selectedPlaylistId)).toBe('p1');
		expect(get(albumList).map((item) => item.id)).toEqual(['a1']);
	});

	it('clears missing resources on 404 but keeps them after a transient error', async () => {
		fetchAlbum.mockRejectedValueOnce(new ApiError(500, 'boom', '/api/albums/a9'));
		await applyLibraryHistory({
			...libraryRootState(),
			surface: 'detail',
			albumId: 'a9'
		});
		expect(get(selectedAlbumId)).toBe('a9');
		fetchAlbum.mockRejectedValueOnce(new ApiError(404, 'gone', '/api/albums/a9'));
		await applyLibraryHistory({
			...libraryRootState(),
			surface: 'detail',
			albumId: 'a9'
		});
		expect(get(selectedAlbumId)).toBeNull();
		expect(get(librarySurface)).toBe('browse');
	});

	it('awaits expanded album tracks before history restore finishes', async () => {
		let resolveExtra: ((value: unknown) => void) | undefined;
		fetchAlbums.mockResolvedValue(emptyPage([album(), album({ id: 'a2', title: 'Second' })]));
		fetchSongs.mockImplementation((albumId?: string) => {
			if (albumId === 'a2') {
				return new Promise((resolve) => {
					resolveExtra = resolve;
				});
			}
			return Promise.resolve({
				...emptyPage([
					song({ id: albumId === 'a1' ? 's1' : 's-browse', album_id: albumId ?? 'a1' })
				]),
				limit: 200
			});
		});
		let finished = false;
		const restore = applyLibraryHistory({
			...libraryRootState(),
			expandedAlbumIds: ['a1', 'a2']
		}).then((ok) => {
			finished = true;
			return ok;
		});
		await vi.waitFor(() => expect(resolveExtra).toBeTypeOf('function'));
		expect(finished).toBe(false);
		expect(get(songList).some((item) => item.album_id === 'a2')).toBe(false);
		resolveExtra?.({
			...emptyPage([song({ id: 's2', album_id: 'a2' })]),
			limit: 200
		});
		expect(await restore).toBe(true);
		expect(finished).toBe(true);
		expect(get(songList).some((item) => item.id === 's2')).toBe(true);
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
		fetchPlaylist.mockRejectedValueOnce(new ApiError(404, 'not found', '/api/playlists/p-gone'));
		await hydrateLibraryFromHistory();
		expect(history.state.playlistId).toBeNull();
		expect(history.state.surface).toBe('browse');
	});

	it('defaults a missing detailTab to Takes without failing restore', async () => {
		const { detailTab: recordedTab, ...withoutDetailTab } = libraryRootState();
		expect(recordedTab).toBe('generations');
		detailTab.set('edit');
		await applyLibraryHistory(withoutDetailTab);
		expect(get(detailTab)).toBe('generations');
		expect(get(librarySurface)).toBe('browse');
	});

	it('cancels a pending Studio search when applying Listen', async () => {
		vi.useFakeTimers();
		try {
			searchQuery.set('Tide');
			syncLibrarySearch('Tide');
			const applied = applyLibraryHistory({ ...libraryRootState(), section: 'playlists' });
			await vi.advanceTimersByTimeAsync(LIBRARY_SEARCH_DEBOUNCE_MS);
			expect(await applied).toBe(true);
			expect(searchLibrary).not.toHaveBeenCalled();
			expect(get(libraryBrowse).status).toBe('ready');
		} finally {
			vi.useRealTimers();
		}
	});

	it('restores Studio song detail after visiting Listen', () => {
		selectedAlbumId.set('a1');
		selectedSongId.set('s1');
		librarySurface.set('detail');
		detailTab.set('edit');
		setLibrarySection('playlists');
		expect(get(librarySection)).toBe('playlists');
		expect(get(librarySurface)).toBe('browse');
		expect(get(selectedSongId)).toBeNull();
		setLibrarySection('albums');
		expect(get(librarySection)).toBe('albums');
		expect(get(librarySurface)).toBe('detail');
		expect(get(selectedSongId)).toBe('s1');
		expect(get(selectedAlbumId)).toBe('a1');
		expect(get(detailTab)).toBe('edit');
	});

	it('apply restores the active mode without wiping the Listen bag', async () => {
		selectedAlbumId.set('a1');
		selectedSongId.set('s1');
		librarySurface.set('detail');
		setLibrarySection('playlists');
		selectedPlaylistId.set('p1');
		librarySurface.set('detail');
		setLibrarySection('albums');
		expect(get(selectedSongId)).toBe('s1');
		await applyLibraryHistory({
			...libraryRootState(),
			surface: 'detail',
			albumId: 'a9',
			songId: 's9'
		});
		expect(get(selectedSongId)).toBe('s9');
		setLibrarySection('playlists');
		expect(get(librarySection)).toBe('playlists');
		expect(get(selectedPlaylistId)).toBe('p1');
		expect(get(librarySurface)).toBe('detail');
		expect(get(selectedSongId)).toBeNull();
	});

	it('browse-from-current clears the resource but keeps section, query, sort, and scroll', () => {
		const current = snapshotLibraryHistory(2);
		const next = {
			...current,
			section: 'playlists' as const,
			query: 'x',
			sort: 'oldest' as const,
			songId: 's1',
			browseTrackAlbumId: 'a1',
			scrollAnchor: 12
		};
		const browse = libraryBrowseStateFrom(next);
		expect(browse.songId).toBeNull();
		expect(browse.albumId).toBeNull();
		expect(browse.browseTrackAlbumId).toBeNull();
		expect(browse.section).toBe('playlists');
		expect(browse.query).toBe('x');
		expect(browse.sort).toBe('oldest');
		expect(browse.scrollAnchor).toBe(12);
	});

	it('restores Studio album track browse after visiting Listen', () => {
		selectedAlbumId.set('a1');
		selectedSongId.set('s1');
		browseTrackAlbumId.set('a2');
		librarySurface.set('detail');
		setLibrarySection('playlists');
		expect(get(browseTrackAlbumId)).toBeNull();
		setLibrarySection('albums');
		expect(get(browseTrackAlbumId)).toBe('a2');
		expect(get(selectedSongId)).toBe('s1');
		expect(get(selectedAlbumId)).toBe('a1');
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

	it('closes the share inventory when a library section is chosen', async () => {
		await applyLibraryHistory({
			...libraryRootState(),
			section: LIBRARY_SHARES_HISTORY_SECTION
		});
		expect(get(sharesViewOpen)).toBe(true);
		setLibrarySection('albums');
		expect(get(sharesViewOpen)).toBe(false);
		expect(snapshotLibraryHistory(0).section).toBe('albums');
	});

	it('keeps albums scroll when Shared is opened, scrolled, and closed', () => {
		captureLibraryScroll(240);
		expect(get(libraryScrollBySection).albums).toBe(240);
		openSharesView();
		expect(get(libraryScrollAnchor)).toBe(0);
		captureLibraryScroll(80);
		expect(get(libraryScrollBySection).albums).toBe(240);
		expect(get(libraryScrollBySection)[LIBRARY_SHARES_HISTORY_SECTION]).toBe(80);
		closeSharesView();
		expect(get(libraryScrollBySection).albums).toBe(240);
		expect(get(libraryScrollAnchor)).toBe(240);
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
