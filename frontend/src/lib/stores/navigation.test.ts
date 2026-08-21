import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { goto } from '$app/navigation';
import { resolve } from '$app/paths';

import { searchQuery } from '$lib/stores/filter';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import {
	hydrateLibraryFromHistory,
	librarySection,
	librarySurface,
	resetLibraryContextForTests,
	setLibrarySection
} from '$lib/stores/libraryContext';
import {
	albumList,
	selectedAlbumId,
	selectedGenerationId,
	selectedSongId,
	songList
} from '$lib/stores/player';
import { selectedPlaylistId } from '$lib/stores/playlists';
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
	fetchAlbums: vi.fn().mockResolvedValue({
		items: [],
		total: 0,
		offset: 0,
		limit: 50,
		has_more: false
	})
}));
vi.mock('$lib/api/songs', () => ({
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchSongs: vi.fn().mockResolvedValue({
		items: [],
		total: 0,
		offset: 0,
		limit: 200,
		has_more: false
	})
}));

vi.mock('$lib/api/client', () => ({
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchSongs: vi.fn().mockResolvedValue({
		items: [],
		total: 0,
		offset: 0,
		limit: 200,
		has_more: false
	}),
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
	backToAlbum,
	backToSong,
	canGoBack,
	goBack,
	initNavigation,
	isLibraryWorkspacePath,
	openLibraryCreate,
	resetNavigationForTests,
	revealPlayingSong,
	selectAlbumOverview,
	selectGeneration,
	selectLibrarySection,
	selectSong
} from './navigation';

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
	vi.mocked(goto).mockClear();
	vi.mocked(resolve).mockClear();
	fetchSong.mockReset();
	fetchAlbum.mockReset();
	fetchPlaylists.mockReset();
	fetchPlaylist.mockReset();
	fetchPlaylists.mockResolvedValue([]);
	fetchSong.mockResolvedValue(song());
	fetchAlbum.mockImplementation(async (albumId: unknown) => ({
		id: String(albumId),
		title: 'Nachtstrom',
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 1,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00'
	}));
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetNavigationForTests();
	searchQuery.set('');
	selectedAlbumId.set(null);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	selectedPlaylistId.set(null);
	songList.set([song()]);
	history.replaceState(null, '', '/');
});

afterEach(() => {
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetNavigationForTests();
	history.replaceState(null, '', '/');
});

describe('library history', () => {
	it('pushes a songmaker state so goBack can pop to the previous library context', () => {
		const cleanup = initNavigation();
		searchQuery.set('Tide');
		selectLibrarySection('albums');
		selectAlbumOverview('a1');
		selectSong('s1');
		expect(history.state).toMatchObject({
			kind: 'songmaker',
			songId: 's1',
			section: 'albums',
			query: 'Tide'
		});
		expect(history.state.index).toBeGreaterThan(0);
		const back = vi.spyOn(history, 'back');
		goBack();
		expect(back).toHaveBeenCalled();
		back.mockRestore();
		cleanup();
	});

	it('popstate restores section, query, sort, and selection', () => {
		const cleanup = initNavigation();
		searchQuery.set('Tide');
		selectLibrarySection('albums');
		const libraryState = history.state;
		selectSong('s1');
		expect(get(selectedSongId)).toBe('s1');

		window.dispatchEvent(new PopStateEvent('popstate', { state: libraryState }));
		expect(get(selectedSongId)).toBeNull();
		expect(get(librarySection)).toBe('albums');
		expect(get(searchQuery)).toBe('Tide');
		cleanup();
	});

	it('goBack without a predecessor clears the resource through the same apply path', () => {
		const cleanup = initNavigation();
		selectedSongId.set('s1');
		selectLibrarySection('playlists');
		expect(get(canGoBack)).toBe(true);
		expect(get(librarySurface)).toBe('browse');
		goBack();
		expect(get(selectedSongId)).toBe('s1');
		expect(get(librarySurface)).toBe('detail');
		goBack();
		expect(get(selectedSongId)).toBeNull();
		expect(get(selectedAlbumId)).toBeNull();
		expect(get(librarySurface)).toBe('browse');
		expect(get(librarySection)).toBe('playlists');
		expect(window.location.pathname).toBe('/');
		cleanup();
	});

	it('goBack from a generation deep-link restores the library root when history has no predecessor', () => {
		history.replaceState(null, '', '/?song=s1&gen=g1');
		selectedSongId.set('s1');
		selectedGenerationId.set('g1');
		const cleanup = initNavigation();
		goBack();
		expect(get(selectedSongId)).toBeNull();
		expect(get(selectedGenerationId)).toBeNull();
		expect(get(librarySurface)).toBe('browse');
		expect(window.location.pathname).toBe('/');
		cleanup();
	});

	it('keeps a valid songmaker history entry instead of replacing it on init', async () => {
		history.replaceState(
			{
				kind: 'songmaker',
				index: 0,
				section: 'playlists',
				surface: 'browse',
				query: 'Tide',
				sort: 'newest',
				albumOffset: 0,
				songOffset: 0,
				searchCursor: null,
				searchLoadedCount: 0,
				albumId: null,
				songId: null,
				generationId: null,
				playlistId: null,
				expandedAlbumIds: [],
				scrollAnchor: 80
			},
			'',
			'/'
		);
		await hydrateLibraryFromHistory();
		expect(get(librarySection)).toBe('playlists');
		expect(get(searchQuery)).toBe('Tide');
		expect(get(librarySurface)).toBe('browse');
		expect(history.state.scrollAnchor).toBe(80);
	});

	it('backToSong from a generation URL keeps the song at history index 0', () => {
		history.replaceState(null, '', '/?song=s1&gen=g1');
		selectedSongId.set('s1');
		selectedGenerationId.set('g1');
		const cleanup = initNavigation();
		backToSong();
		expect(get(selectedSongId)).toBe('s1');
		expect(get(selectedGenerationId)).toBeNull();
		cleanup();
	});

	it('selectGeneration replaces the current history entry and does not push', () => {
		const cleanup = initNavigation();
		selectSong('s1');
		const index = history.state.index;
		const push = vi.spyOn(history, 'pushState');
		selectGeneration(generation(), song());
		expect(push).not.toHaveBeenCalled();
		expect(history.state.index).toBe(index);
		expect(history.state.generationId).toBe('g1');
		expect(get(selectedSongId)).toBe('s1');
		expect(get(selectedGenerationId)).toBe('g1');
		push.mockRestore();
		cleanup();
	});

	it('goBack from a song with a selected take leaves the song', () => {
		const cleanup = initNavigation();
		selectSong('s1');
		const songIndex = history.state.index;
		selectGeneration(generation(), song());
		expect(history.state.index).toBe(songIndex);
		expect(get(selectedSongId)).toBe('s1');
		expect(get(selectedGenerationId)).toBe('g1');
		const back = vi.spyOn(history, 'back');
		goBack();
		expect(back).toHaveBeenCalled();
		back.mockRestore();
		cleanup();
	});

	it('?gen= selects a take without a second history page', () => {
		history.replaceState(null, '', '/?song=s1&gen=g1');
		const push = vi.spyOn(history, 'pushState');
		const cleanup = initNavigation();
		expect(push).not.toHaveBeenCalled();
		expect(history.state.index).toBe(0);
		expect(history.state.songId).toBe('s1');
		expect(history.state.generationId).toBe('g1');
		expect(get(selectedSongId)).toBe('s1');
		expect(get(selectedGenerationId)).toBe('g1');
		selectGeneration(generation({ id: 'g2' }), song());
		expect(push).not.toHaveBeenCalled();
		expect(history.state.index).toBe(0);
		expect(history.state.generationId).toBe('g2');
		push.mockRestore();
		cleanup();
	});

	it('switching section does not clear the selected song', () => {
		selectedSongId.set('s1');
		setLibrarySection('playlists');
		expect(get(selectedSongId)).toBe('s1');
		expect(get(librarySection)).toBe('playlists');
	});

	it('create surface is a backable library destination', () => {
		const cleanup = initNavigation();
		openLibraryCreate();
		expect(get(librarySurface)).toBe('create');
		expect(get(canGoBack)).toBe(true);
		const back = vi.spyOn(history, 'back');
		goBack();
		expect(back).toHaveBeenCalled();
		back.mockRestore();
		cleanup();
	});

	it('backToAlbum keeps the album when a song was opened without album history', () => {
		const cleanup = initNavigation();
		selectSong('s1');
		backToAlbum();
		expect(get(selectedSongId)).toBeNull();
		expect(get(selectedAlbumId)).toBe('a1');
		expect(get(librarySurface)).toBe('detail');
		cleanup();
	});

	it('treats only the home path as the library workspace', () => {
		expect(isLibraryWorkspacePath('/')).toBe(true);
		expect(isLibraryWorkspacePath('/loras')).toBe(false);
		expect(isLibraryWorkspacePath('/settings')).toBe(false);
	});

	it('revealPlayingSong opens library detail without navigating from the library', async () => {
		const cleanup = initNavigation();
		await revealPlayingSong(song(), 'g1');
		expect(goto).not.toHaveBeenCalled();
		expect(get(selectedSongId)).toBe('s1');
		expect(get(selectedGenerationId)).toBe('g1');
		expect(get(librarySurface)).toBe('detail');
		cleanup();
	});

	it('revealPlayingSong navigates from another workspace through the resolved library root', async () => {
		history.replaceState(null, '', '/loras');
		await revealPlayingSong(song(), 'g1');
		expect(resolve).toHaveBeenCalledWith('/');
		expect(goto).toHaveBeenCalledWith('/');
	});

	it('hydrates a search-only song and its album into the library', async () => {
		const cleanup = initNavigation();
		selectSong('s-remote', {
			...song(),
			id: 's-remote',
			album_id: 'a-remote',
			album_title: 'Remote Album'
		});
		await Promise.resolve();
		await Promise.resolve();
		expect(get(selectedSongId)).toBe('s-remote');
		expect(get(selectedAlbumId)).toBe('a-remote');
		expect(get(songList).some((item) => item.id === 's-remote')).toBe(true);
		expect(get(albumList).some((item) => item.id === 'a-remote')).toBe(true);
		cleanup();
	});
});
