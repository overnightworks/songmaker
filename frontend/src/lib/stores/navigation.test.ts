import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { goto } from '$app/navigation';
import { resolve } from '$app/paths';

import { searchQuery } from '$lib/stores/filter';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { librarySurface, resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { openCollection, resetCollectionForTests } from '$lib/stores/collection';
import { albumList, selectedGenerationId, selectedSongId, songList } from '$lib/stores/player';
import { resetPlaylistsForTests, selectedPlaylistId } from '$lib/stores/playlists';
import { sidebarOpen, toggleSidebar } from '$lib/stores/ui';
import type { GenerationItem, SongItem } from '$lib/api/types';

const fetchSong = vi.fn();
const fetchAlbum = vi.fn();
const fetchPlaylists = vi.fn();
const fetchPlaylist = vi.fn();

vi.mock('$app/navigation', () => ({
	goto: vi.fn().mockResolvedValue(undefined)
}));
vi.mock('$app/paths', () => ({
	resolve: vi.fn((path: string) => path)
}));
vi.mock('$lib/api/library', () => ({
	searchLibrary: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false })
}));
vi.mock('$lib/api/albums', () => ({
	fetchAlbum: (...args: unknown[]) => fetchAlbum(...args),
	fetchAlbums: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, has_more: false })
}));
vi.mock('$lib/api/songs', () => ({
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
vi.mock('$lib/api/client', () => ({
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false }),
	fetchPlaylists: (...args: unknown[]) => fetchPlaylists(...args),
	fetchPlaylist: (...args: unknown[]) => fetchPlaylist(...args),
	createPlaylist: vi.fn(),
	deletePlaylistApi: vi.fn(),
	updatePlaylist: vi.fn(),
	addGenerationToPlaylist: vi.fn(),
	addSongToPlaylist: vi.fn(),
	addAlbumToPlaylist: vi.fn(),
	removeFromPlaylist: vi.fn(),
	reorderPlaylistEntry: vi.fn(),
	fetchVersions: vi.fn().mockResolvedValue([]),
	updateSong: vi.fn(),
	deleteVersion: vi.fn()
}));

import {
	albumTrackNeighbors,
	backToCollection,
	goBack,
	initNavigation,
	isLibraryWorkspacePath,
	openAlbum,
	openCollectionEntry,
	openLibraryCreate,
	openLibraryWall,
	openPlaylist,
	pendingDirtyNavigation,
	resetNavigationForTests,
	revealPlayingSong,
	selectLibraryFilter,
	selectNeighborSong,
	selectSong
} from './navigation';
import { discardDraft, editLyrics, loadSongData, setDraftLyrics } from '$lib/stores/editor';
import { updateSong } from '$lib/api/client';
import { libraryRootState } from '$lib/stores/libraryContext';
import { toasts } from '$lib/stores/toast';

function generation(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
		mp3_path: 'g1.mp3',
		wav_path: null,
		seed: 7,
		status: 'completed',
		is_archived: false,
		is_picked: false,
		is_kept: false,
		is_shared: false,
		model_mode: 'turbo',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: null,
		scores: null,
		generation_params: null,
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
		generation_count: 1,
		best_scores: null,
		best_rating: null,
		generations: [generation()],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

beforeEach(() => {
	fetchSong.mockReset();
	fetchAlbum.mockReset();
	fetchPlaylists.mockReset();
	fetchPlaylist.mockReset();
	vi.mocked(updateSong).mockReset();
	toasts.set([]);
	fetchPlaylists.mockResolvedValue([]);
	fetchPlaylist.mockResolvedValue({
		id: 'p1',
		title: 'Night Drive',
		entry_count: 0,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		entries: []
	});
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
	resetNavigationForTests();
	searchQuery.set('');
	albumList.set([album('a1', 'Nachtstrom'), album('a2', 'Other')]);
	songList.set([song()]);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	// Must run after selectedSongId is cleared: the album/song-list reset
	// above briefly recomputes `selectedSong` against the previous test's
	// stale selectedSongId and re-derives openCollection through the
	// selectedSong subscription in navigation.ts before this line clears it.
	resetCollectionForTests();
	history.replaceState(null, '', '/');
	vi.mocked(goto).mockClear();
});

afterEach(() => {
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
	resetCollectionForTests();
});

function album(id: string, title: string) {
	return {
		id,
		title,
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 1,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00'
	};
}

describe('isLibraryWorkspacePath', () => {
	it('is only the home path', () => {
		expect(isLibraryWorkspacePath('/')).toBe(true);
		expect(isLibraryWorkspacePath('/settings')).toBe(false);
	});
});

describe('openAlbum / openPlaylist', () => {
	it('opens an album collection and pushes one history entry', () => {
		const before = history.state?.index ?? 0;
		openAlbum('a1');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
		expect(get(librarySurface)).toBe('detail');
		expect(history.state.index).toBe(before + 1);
	});

	it('opens a playlist collection and pushes one history entry', async () => {
		const before = history.state?.index ?? 0;
		openPlaylist('p1');
		await Promise.resolve();
		expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p1' });
		expect(get(selectedPlaylistId)).toBe('p1');
		expect(history.state.index).toBe(before + 1);
	});

	it('clears the open song when a new collection opens', () => {
		selectSong('s1');
		openAlbum('a2');
		expect(get(selectedSongId)).toBeNull();
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a2' });
	});
});

describe.each([
	['openAlbum', () => openAlbum('a1')],
	['openPlaylist', () => openPlaylist('p1')],
	['openLibraryWall', () => openLibraryWall()],
	['openLibraryCreate', () => openLibraryCreate()]
])('%s closes the rail drawer', (_name, action) => {
	it('closes an open drawer instead of leaving it over the new surface', async () => {
		toggleSidebar();
		expect(get(sidebarOpen)).toBe(true);
		await action();
		expect(get(sidebarOpen)).toBe(false);
	});
});

describe('selectSong keeps the rail context pinned to the song album', () => {
	it('opens a song and sets the collection to that song album, even with no prior collection', () => {
		expect(get(openCollection)).toBeNull();
		selectSong('s1');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('switches the collection when the open collection is a different album', () => {
		openAlbum('a2');
		selectSong('s1', song({ id: 's1', album_id: 'a1' }));
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('switches the collection when a playlist was open (song open beats playlist context)', async () => {
		openPlaylist('p1');
		await Promise.resolve();
		expect(get(openCollection)?.kind).toBe('playlist');
		selectSong('s1', song({ id: 's1', album_id: 'a1' }));
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
		expect(get(selectedPlaylistId)).toBeNull();
	});

	it('leaves the collection untouched when it already matches the song album', () => {
		openAlbum('a1');
		const stateBefore = get(openCollection);
		selectSong('s1', song({ id: 's1', album_id: 'a1' }));
		expect(get(openCollection)).toBe(stateBefore);
	});

	it('pushes a new history entry per selectSong call', () => {
		const before = history.state?.index ?? 0;
		selectSong('s1');
		expect(history.state.index).toBe(before + 1);
	});

	it('pushes a new history entry when opening the first song from the album interior', () => {
		songList.set([song({ id: 's1', album_id: 'a1' }), song({ id: 's2', album_id: 'a1' })]);
		openAlbum('a1');
		const afterOpen = history.state.index;
		selectSong('s1', song({ id: 's1', album_id: 'a1' }));
		expect(history.state.index).toBe(afterOpen + 1);
		expect(get(selectedSongId)).toBe('s1');
	});

	it('replaces the current history entry when moving to another song already inside the open collection', () => {
		songList.set([song({ id: 's1', album_id: 'a1' }), song({ id: 's2', album_id: 'a1' })]);
		openAlbum('a1');
		selectSong('s1', song({ id: 's1', album_id: 'a1' }));
		const afterFirstSong = history.state.index;
		selectSong('s2', song({ id: 's2', album_id: 'a1' }));
		expect(history.state.index).toBe(afterFirstSong);
		expect(get(selectedSongId)).toBe('s2');
	});

	it('pushes a new history entry when the song is outside the open collection', () => {
		songList.set([song({ id: 's1', album_id: 'a1' }), song({ id: 's2', album_id: 'a2' })]);
		openAlbum('a1');
		const afterOpen = history.state.index;
		selectSong('s2', song({ id: 's2', album_id: 'a2' }));
		expect(history.state.index).toBe(afterOpen + 1);
		expect(get(selectedSongId)).toBe('s2');
	});

	it('lands back on the album, not the wall, after opening two tracks in a row (issue #99)', () => {
		songList.set([song({ id: 's1', album_id: 'a1' }), song({ id: 's2', album_id: 'a1' })]);
		const wallIndex = history.state?.index ?? 0;
		openAlbum('a1');
		const albumIndex = history.state.index;
		expect(albumIndex).toBe(wallIndex + 1);
		selectSong('s1', song({ id: 's1', album_id: 'a1' }));
		const track1Index = history.state.index;
		expect(track1Index).toBe(albumIndex + 1);
		selectSong('s2', song({ id: 's2', album_id: 'a1' }));
		expect(history.state.index).toBe(track1Index);
	});
});

describe('selectNeighborSong', () => {
	it('replaces the current history entry instead of pushing', () => {
		selectSong('s1');
		const afterFirst = history.state.index;
		selectNeighborSong(song({ id: 's2', album_id: 'a1' }));
		expect(history.state.index).toBe(afterFirst);
		expect(get(selectedSongId)).toBe('s2');
	});
});

describe('backToCollection', () => {
	it('leaves the song and returns to the open collection detail', () => {
		openAlbum('a1');
		selectSong('s1');
		backToCollection();
		expect(get(selectedSongId)).toBeNull();
		expect(get(librarySurface)).toBe('detail');
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('falls back to the wall when there is no open collection', () => {
		selectSong('s1');
		openCollection.set(null);
		backToCollection();
		expect(get(librarySurface)).toBe('browse');
	});
});

describe('a dirty draft guards song switch / leave', () => {
	afterEach(() => {
		discardDraft();
	});

	it('defers selectSong instead of switching while the draft is dirty', () => {
		openAlbum('a1');
		selectSong('s1');
		loadSongData(song({ id: 's1' }));
		setDraftLyrics('unsaved edit');

		selectSong('s2', song({ id: 's2', album_id: 'a1' }));

		expect(get(selectedSongId)).toBe('s1');
		expect(get(pendingDirtyNavigation)).not.toBeNull();
	});

	it('runs the deferred switch on Discard', () => {
		openAlbum('a1');
		selectSong('s1');
		loadSongData(song({ id: 's1' }));
		setDraftLyrics('unsaved edit');
		songList.set([song({ id: 's1' }), song({ id: 's2', album_id: 'a1' })]);

		selectSong('s2', song({ id: 's2', album_id: 'a1' }));
		discardDraft();
		void get(pendingDirtyNavigation)?.();
		pendingDirtyNavigation.set(null);

		expect(get(selectedSongId)).toBe('s2');
	});

	it('stays put on Cancel', () => {
		openAlbum('a1');
		selectSong('s1');
		loadSongData(song({ id: 's1' }));
		setDraftLyrics('unsaved edit');

		selectSong('s2', song({ id: 's2', album_id: 'a1' }));
		pendingDirtyNavigation.set(null);

		expect(get(selectedSongId)).toBe('s1');
		expect(get(editLyrics)).toBe('unsaved edit');
	});

	it('defers backToCollection and openLibraryWall the same way', async () => {
		openAlbum('a1');
		selectSong('s1');
		loadSongData(song({ id: 's1' }));
		setDraftLyrics('unsaved edit');

		backToCollection();
		expect(get(selectedSongId)).toBe('s1');
		expect(get(pendingDirtyNavigation)).not.toBeNull();
		pendingDirtyNavigation.set(null);

		await openLibraryWall();
		expect(get(selectedSongId)).toBe('s1');
		expect(get(pendingDirtyNavigation)).not.toBeNull();
	});

	it('defers selectNeighborSong the same way', () => {
		openAlbum('a1');
		selectSong('s1');
		loadSongData(song({ id: 's1' }));
		setDraftLyrics('unsaved edit');

		selectNeighborSong(song({ id: 's2', album_id: 'a1' }));

		expect(get(selectedSongId)).toBe('s1');
		expect(get(pendingDirtyNavigation)).not.toBeNull();
	});

	it('defers revealPlayingSong the same way', async () => {
		history.replaceState(null, '', '/');
		openAlbum('a1');
		selectSong('s1');
		loadSongData(song({ id: 's1' }));
		setDraftLyrics('unsaved edit');

		await revealPlayingSong(song({ id: 's2', album_id: 'a1' }), 'g2');

		expect(get(selectedSongId)).toBe('s1');
		expect(get(selectedGenerationId)).toBeNull();
		expect(get(pendingDirtyNavigation)).not.toBeNull();
	});

	it('never prompts when the draft is clean', () => {
		openAlbum('a1');
		selectSong('s1');
		loadSongData(song({ id: 's1' }));

		selectSong('s2', song({ id: 's2', album_id: 'a1' }));

		expect(get(selectedSongId)).toBe('s2');
		expect(get(pendingDirtyNavigation)).toBeNull();
	});
});

describe('openCollectionEntry', () => {
	it('goes back to the collection when a song inside it is open', () => {
		openAlbum('a1');
		selectSong('s1');
		openCollectionEntry({ kind: 'album', id: 'a1' });
		expect(get(selectedSongId)).toBeNull();
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
	});

	it('opens the collection when no song is open', () => {
		openCollectionEntry({ kind: 'playlist', id: 'p1' });
		expect(get(openCollection)?.kind).toBe('playlist');
	});
});

describe('goBack', () => {
	it('defers to the browser history when a predecessor exists', () => {
		openAlbum('a1');
		selectSong('s1');
		const backSpy = vi.spyOn(history, 'back').mockImplementation(() => undefined);
		goBack();
		expect(backSpy).toHaveBeenCalledTimes(1);
		backSpy.mockRestore();
	});

	it('returns to the wall and clears selection when there is no predecessor', () => {
		selectSong('s1');
		history.replaceState(null, '', '/');
		goBack();
		expect(get(librarySurface)).toBe('browse');
		expect(get(selectedSongId)).toBeNull();
	});

	it('leaves the create surface for the wall when there is no predecessor', () => {
		librarySurface.set('create');
		goBack();
		expect(get(librarySurface)).toBe('browse');
	});
});

describe('selectLibraryFilter', () => {
	it('replaces history instead of pushing', () => {
		const before = history.state?.index ?? 0;
		selectLibraryFilter('playlists');
		expect(history.state.index).toBe(before);
	});
});

describe('revealPlayingSong', () => {
	it('opens the song in place when already on the library workspace', async () => {
		history.replaceState(null, '', '/');
		await revealPlayingSong(song({ id: 's1' }), 'g1');
		expect(goto).not.toHaveBeenCalled();
		expect(get(selectedSongId)).toBe('s1');
		expect(get(selectedGenerationId)).toBe('g1');
	});

	it('navigates home first from another route', async () => {
		history.replaceState(null, '', '/settings');
		await revealPlayingSong(song({ id: 's1' }), 'g1');
		expect(goto).toHaveBeenCalledWith(resolve('/'));
	});
});

describe('initNavigation', () => {
	it('opens the song from a ?song= deep link and pins the collection once loaded', async () => {
		fetchSong.mockResolvedValue(song({ id: 's1', album_id: 'a1' }));
		history.replaceState(null, '', '/?song=s1');
		const cleanup = initNavigation();
		expect(get(selectedSongId)).toBe('s1');
		await Promise.resolve();
		await Promise.resolve();
		expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' });
		cleanup();
	});

	it('auto-saves a dirty draft before applying a browser-back navigation', async () => {
		history.replaceState(null, '', '/');
		openAlbum('a1');
		selectSong('s1');
		loadSongData(song({ id: 's1' }));
		setDraftLyrics('unsaved edit');
		vi.mocked(updateSong).mockResolvedValue(song({ id: 's1', lyrics: 'unsaved edit' }));

		const cleanup = initNavigation();
		window.dispatchEvent(new PopStateEvent('popstate', { state: libraryRootState() }));
		await vi.waitFor(() => expect(get(selectedSongId)).toBeNull());

		expect(updateSong).toHaveBeenCalledWith(
			's1',
			expect.objectContaining({ lyrics: 'unsaved edit' })
		);
		cleanup();
	});

	it('still applies the browser-back navigation when the auto-save fails', async () => {
		history.replaceState(null, '', '/');
		openAlbum('a1');
		selectSong('s1');
		loadSongData(song({ id: 's1' }));
		setDraftLyrics('unsaved edit');
		vi.mocked(updateSong).mockRejectedValue(new Error('Network error'));

		const cleanup = initNavigation();
		window.dispatchEvent(new PopStateEvent('popstate', { state: libraryRootState() }));
		await vi.waitFor(() => expect(get(selectedSongId)).toBeNull());

		expect(get(toasts).some((t) => t.type === 'error')).toBe(true);
		cleanup();
	});

	it('does not attempt a save on browser-back when the draft is clean', async () => {
		history.replaceState(null, '', '/');
		openAlbum('a1');
		selectSong('s1');
		loadSongData(song({ id: 's1' }));

		const cleanup = initNavigation();
		window.dispatchEvent(new PopStateEvent('popstate', { state: libraryRootState() }));
		await vi.waitFor(() => expect(get(selectedSongId)).toBeNull());

		expect(updateSong).not.toHaveBeenCalled();
		cleanup();
	});
});

describe('album track neighbors', () => {
	it('orders same-album tracks by track number without wrapping', () => {
		const songs = [
			song({ id: 's1', track_number: 1 }),
			song({ id: 's2', track_number: 2 }),
			song({ id: 's3', track_number: 3 })
		];
		expect(albumTrackNeighbors('s2', songs)).toEqual({ previous: songs[0], next: songs[2] });
		expect(albumTrackNeighbors('s1', songs)).toEqual({ previous: null, next: songs[1] });
		expect(albumTrackNeighbors('s3', songs)).toEqual({ previous: songs[1], next: null });
	});
});
