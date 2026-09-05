import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { AlbumItem, GenerationItem, PaginatedResponse, SongItem } from '$lib/api/types';
import { ApiError } from '$lib/api/fetch';
import { API_ERROR_GENERIC_MESSAGE } from '$lib/constants';

vi.mock('$lib/api/client', () => ({
	fetchSongs: vi.fn().mockResolvedValue({
		items: [],
		total: 0,
		offset: 0,
		limit: 200,
		has_more: false
	}),
	fetchAlbums: vi.fn().mockResolvedValue({
		items: [],
		total: 0,
		offset: 0,
		limit: 50,
		has_more: false
	})
}));

vi.mock('$lib/api/library', () => ({
	fetchLibraryContinue: vi.fn()
}));

import { fetchAlbums, fetchSongs } from '$lib/api/client';
import { fetchLibraryContinue } from '$lib/api/library';
import {
	albumList,
	albumSongsLoad,
	allAlbumsLoad,
	cancelAlbumSongLoads,
	ensureAllAlbumsLoaded,
	loadLibraryContinueItems,
	loadSongsForAlbum,
	overlaySongList,
	replaceSongInList,
	resetLibraryContinueItems,
	retainRicherSong,
	songList,
	updateGenerationScores,
	upsertSongInList
} from './libraryData';

function makeAlbum(overrides: Partial<AlbumItem> = {}): AlbumItem {
	return {
		id: 'a1',
		title: 'Album',
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 0,
		picked_count: 0,
		is_shared: false,
		share_slug: null,
		created_at: '',
		is_archived: false,
		...overrides
	};
}

function makeSong(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		slug: 'song',
		title: 'Song',
		album_id: 'a1',
		album_title: 'Album',
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
		generations: [makeGen()],
		created_at: '',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

function makeGen(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
		mp3_path: 'a1/song_v1.mp3',
		wav_path: 'a1/song_v1.wav',
		seed: 42,
		status: 'completed',
		is_archived: false,
		is_picked: false,
		is_kept: false,
		model_mode: 'sft',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: null,
		scores: null,
		generation_params: null,
		audio_duration_sec: null,
		created_at: '',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

beforeEach(() => {
	resetLibraryContinueItems();
	vi.mocked(fetchSongs).mockResolvedValue({
		items: [],
		total: 0,
		offset: 0,
		limit: 200,
		has_more: false
	});
	vi.mocked(fetchAlbums).mockResolvedValue({
		items: [],
		total: 0,
		offset: 0,
		limit: 50,
		has_more: false
	});
});

describe('Continue items', () => {
	it('reloads Continue after a mutation clears the cache for a wall remount', async () => {
		const beforeListen = [{ type: 'song' as const, id: 'before', title: 'Before' }];
		const afterListen = [{ type: 'song' as const, id: 'after', title: 'After' }];
		vi.mocked(fetchLibraryContinue)
			.mockResolvedValueOnce({ items: beforeListen })
			.mockResolvedValueOnce({ items: afterListen });

		await expect(loadLibraryContinueItems()).resolves.toEqual(beforeListen);
		await expect(loadLibraryContinueItems()).resolves.toEqual(beforeListen);

		expect(fetchLibraryContinue).toHaveBeenCalledOnce();
		// recordSongListen and the editor mutation owners call this before the
		// library wall mounts again in the same SPA document.
		resetLibraryContinueItems();
		await expect(loadLibraryContinueItems()).resolves.toEqual(afterListen);
		expect(fetchLibraryContinue).toHaveBeenCalledTimes(2);
	});

	it('retries after a failed request', async () => {
		vi.mocked(fetchLibraryContinue)
			.mockRejectedValueOnce(new Error('offline'))
			.mockResolvedValueOnce({ items: [] });

		await expect(loadLibraryContinueItems()).rejects.toThrow('offline');
		await expect(loadLibraryContinueItems()).resolves.toEqual([]);
		expect(fetchLibraryContinue).toHaveBeenCalledTimes(2);
	});
});

afterEach(() => {
	vi.clearAllMocks();
	vi.restoreAllMocks();
	songList.set([]);
	albumList.set([]);
	allAlbumsLoad.set({ status: 'idle', error: null });
});

describe('song list mutations', () => {
	it('replaceSongInList applies an authoritative empty generation list', () => {
		songList.set([makeSong({ generation_count: 1, generations: [makeGen()] })]);
		replaceSongInList(makeSong({ generation_count: 0, generations: [] }));
		expect(get(songList)[0].generations).toEqual([]);
		expect(get(songList)[0].generation_count).toBe(0);
	});

	it('cancelAlbumSongLoads drops an in-flight album merge', async () => {
		let resolvePage: ((value: PaginatedResponse<SongItem>) => void) | undefined;
		vi.mocked(fetchSongs).mockImplementationOnce(
			() =>
				new Promise<PaginatedResponse<SongItem>>((resolve) => {
					resolvePage = resolve;
				})
		);
		const pending = loadSongsForAlbum('a1');
		cancelAlbumSongLoads();
		resolvePage?.({
			items: [makeSong({ id: 's-stale', album_id: 'a1' })],
			total: 1,
			offset: 0,
			limit: 200,
			has_more: false
		});
		await pending;
		expect(get(songList).some((item) => item.id === 's-stale')).toBe(false);
	});

	it('records a retryable error when album songs fail to load', async () => {
		vi.mocked(fetchSongs).mockRejectedValueOnce(new Error('offline'));
		await loadSongsForAlbum('a1');
		expect(get(albumSongsLoad).a1).toEqual({ status: 'error', error: 'offline' });
	});

	it('shows a readable sentence, not a raw status line, when the server sends no detail', async () => {
		vi.mocked(fetchSongs).mockRejectedValueOnce(new ApiError(500, '', '/api/albums/a1/songs'));
		await loadSongsForAlbum('a1');
		expect(get(albumSongsLoad).a1).toEqual({
			status: 'error',
			error: API_ERROR_GENERIC_MESSAGE
		});
	});

	it('loadSongsForAlbum merges album tracks that were outside the browse slice', async () => {
		songList.set([makeSong({ id: 's-page', album_id: 'a1' })]);
		vi.mocked(fetchSongs).mockResolvedValueOnce({
			items: [
				makeSong({ id: 's-page', album_id: 'a1', title: 'Page' }),
				makeSong({ id: 's-hidden', album_id: 'a1', title: 'Hidden' })
			],
			total: 2,
			offset: 0,
			limit: 200,
			has_more: false
		});
		await loadSongsForAlbum('a1');
		expect(vi.mocked(fetchSongs)).toHaveBeenCalledWith('a1', 0, 200);
		expect(
			get(songList)
				.map((item) => item.id)
				.sort()
		).toEqual(['s-hidden', 's-page']);
	});

	it('dedupes concurrent requests for the same album songs', async () => {
		vi.mocked(fetchSongs).mockResolvedValueOnce({
			items: [makeSong({ id: 's1', album_id: 'a1' })],
			total: 1,
			offset: 0,
			limit: 200,
			has_more: false
		});

		await Promise.all([loadSongsForAlbum('a1'), loadSongsForAlbum('a1')]);

		expect(fetchSongs).toHaveBeenCalledTimes(1);
	});

	it('retainRicherSong keeps loaded takes when a summary arrives later', () => {
		const loaded = makeSong({
			id: 's1',
			generation_count: 1,
			generations: [makeGen()]
		});
		const summary = makeSong({
			id: 's1',
			title: 'Updated title',
			generation_count: 0,
			generations: []
		});
		const merged = retainRicherSong(loaded, summary);
		expect(merged.title).toBe('Updated title');
		expect(merged.generation_count).toBe(1);
		expect(merged.generations).toHaveLength(1);
	});

	it('retainRicherSong raises generation_count without dropping loaded takes', () => {
		const loaded = makeSong({
			id: 's1',
			generation_count: 1,
			generations: [makeGen()]
		});
		const summary = makeSong({
			id: 's1',
			generation_count: 2,
			generations: []
		});
		const merged = retainRicherSong(loaded, summary);
		expect(merged.generation_count).toBe(2);
		expect(merged.generations).toHaveLength(1);
	});

	it('overlaySongList preserves loaded takes across a browse reset', () => {
		const existing = [
			makeSong({
				id: 's1',
				generation_count: 1,
				generations: [makeGen()]
			})
		];
		const incoming = [makeSong({ id: 's1', generation_count: 0, generations: [] })];
		expect(overlaySongList(existing, incoming)[0].generations).toHaveLength(1);
	});

	it('upsertSongInList appends an absent song and replaces a present one', () => {
		songList.set([makeSong({ id: 'a' })]);
		upsertSongInList(makeSong({ id: 'b', title: 'B' }));
		upsertSongInList(makeSong({ id: 'a', title: 'A2' }));
		const byId = new Map(get(songList).map((s) => [s.id, s.title]));
		expect([byId.get('a'), byId.get('b')]).toEqual(['A2', 'B']);
	});
});

describe('updateGenerationScores', () => {
	it('updates scores for matching generation', () => {
		songList.set([makeSong()]);
		updateGenerationScores('g1', { dynamics: 80 });
		const songs = get(songList);
		expect(songs[0].generations[0].scores).toEqual({ dynamics: 80 });
	});

	it('does not affect other generations', () => {
		const gen2 = makeGen({ id: 'g2', seed: 99 });
		songList.set([makeSong({ generations: [makeGen(), gen2] })]);
		updateGenerationScores('g1', { dynamics: 80 });
		const songs = get(songList);
		expect(songs[0].generations[1].scores).toBeNull();
	});
});

describe('ensureAllAlbumsLoaded', () => {
	it('follows has_more across pages until the full list is loaded', async () => {
		vi.mocked(fetchAlbums)
			.mockResolvedValueOnce({
				items: [makeAlbum({ id: 'a1' }), makeAlbum({ id: 'a2' })],
				total: 3,
				offset: 0,
				limit: 2,
				has_more: true
			})
			.mockResolvedValueOnce({
				items: [makeAlbum({ id: 'a3' })],
				total: 3,
				offset: 2,
				limit: 2,
				has_more: false
			});
		const ok = await ensureAllAlbumsLoaded();
		expect(ok).toBe(true);
		expect(
			get(albumList)
				.map((a) => a.id)
				.sort()
		).toEqual(['a1', 'a2', 'a3']);
		expect(get(allAlbumsLoad)).toEqual({ status: 'ready', error: null });
	});

	it('does not refetch once the list is loaded', async () => {
		vi.mocked(fetchAlbums).mockResolvedValueOnce({
			items: [makeAlbum({ id: 'a1' })],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		await ensureAllAlbumsLoaded();
		await ensureAllAlbumsLoaded();
		expect(vi.mocked(fetchAlbums)).toHaveBeenCalledTimes(1);
	});

	it('dedupes concurrent requests for all albums', async () => {
		vi.mocked(fetchAlbums).mockResolvedValueOnce({
			items: [makeAlbum({ id: 'a1' })],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});

		await Promise.all([ensureAllAlbumsLoaded(), ensureAllAlbumsLoaded()]);

		expect(fetchAlbums).toHaveBeenCalledTimes(1);
	});

	it('preserves an album a concurrent load added while merging its own fetch', async () => {
		let resolvePage: ((value: PaginatedResponse<AlbumItem>) => void) | undefined;
		vi.mocked(fetchAlbums).mockImplementationOnce(
			() =>
				new Promise<PaginatedResponse<AlbumItem>>((resolve) => {
					resolvePage = resolve;
				})
		);
		const pending = ensureAllAlbumsLoaded();
		albumList.set([makeAlbum({ id: 'a-from-grid' })]);
		resolvePage?.({
			items: [makeAlbum({ id: 'a1' })],
			total: 1,
			offset: 0,
			limit: 50,
			has_more: false
		});
		await pending;
		expect(
			get(albumList)
				.map((a) => a.id)
				.sort()
		).toEqual(['a-from-grid', 'a1']);
	});

	it('records a retryable error when albums fail to load', async () => {
		vi.mocked(fetchAlbums).mockRejectedValueOnce(new Error('offline'));
		const ok = await ensureAllAlbumsLoaded();
		expect(ok).toBe(false);
		expect(get(allAlbumsLoad)).toEqual({ status: 'error', error: 'offline' });
	});

	it('shows a readable sentence, not a raw status line, when the server sends no detail', async () => {
		vi.mocked(fetchAlbums).mockRejectedValueOnce(new ApiError(500, '', '/api/albums'));
		const ok = await ensureAllAlbumsLoaded();
		expect(ok).toBe(false);
		expect(get(allAlbumsLoad)).toEqual({
			status: 'error',
			error: API_ERROR_GENERIC_MESSAGE
		});
	});
});
