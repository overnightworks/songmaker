import { makeAlbum, makeGeneration as makeGen, makeSong } from '$lib/test-utils/factories';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { AlbumItem, PaginatedResponse, SongItem } from '$lib/api/types';
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
	songList,
	upsertSongInList
} from './libraryData';

function loadedSongDefaults(): Partial<SongItem> {
	return {
		slug: 'song',
		title: 'Song',
		generations: [
			makeGen({
				mp3_path: 'a1/song_v1.mp3',
				wav_path: 'a1/song_v1.wav',
				seed: 42,
				model_mode: 'sft',
				created_at: ''
			})
		],
		created_at: ''
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
		songList.set([
			makeSong({
				...loadedSongDefaults(),
				generations: [
					makeGen({
						mp3_path: 'a1/song_v1.mp3',
						wav_path: 'a1/song_v1.wav',
						seed: 42,
						model_mode: 'sft',
						created_at: ''
					})
				]
			})
		]);
		replaceSongInList(makeSong({ ...loadedSongDefaults(), generation_count: 0, generations: [] }));
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
			items: [makeSong({ ...loadedSongDefaults(), id: 's-stale' })],
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
		songList.set([makeSong({ ...loadedSongDefaults(), id: 's-page' })]);
		vi.mocked(fetchSongs).mockResolvedValueOnce({
			items: [
				makeSong({ ...loadedSongDefaults(), id: 's-page', title: 'Page' }),
				makeSong({ ...loadedSongDefaults(), id: 's-hidden', title: 'Hidden' })
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

	it('follows album-song pages and stops after an empty page even when the server says more exists', async () => {
		vi.mocked(fetchSongs)
			.mockResolvedValueOnce({
				items: [makeSong(loadedSongDefaults())],
				total: 2,
				offset: 0,
				limit: 200,
				has_more: true
			})
			.mockResolvedValueOnce({
				items: [],
				total: 2,
				offset: 1,
				limit: 200,
				has_more: true
			});

		await loadSongsForAlbum('a1');

		expect(fetchSongs).toHaveBeenLastCalledWith('a1', 1, 200);
		expect(get(songList).map((item) => item.id)).toEqual(['s1']);
		expect(get(albumSongsLoad).a1).toEqual({ status: 'idle', error: null });
	});

	it('dedupes concurrent requests for the same album songs', async () => {
		vi.mocked(fetchSongs).mockResolvedValueOnce({
			items: [makeSong(loadedSongDefaults())],
			total: 1,
			offset: 0,
			limit: 200,
			has_more: false
		});

		await Promise.all([loadSongsForAlbum('a1'), loadSongsForAlbum('a1')]);

		expect(fetchSongs).toHaveBeenCalledTimes(1);
	});

	it('overlaySongList keeps loaded takes when a summary arrives later', () => {
		const loaded = makeSong({
			...loadedSongDefaults(),
			generations: [
				makeGen({
					mp3_path: 'a1/song_v1.mp3',
					wav_path: 'a1/song_v1.wav',
					seed: 42,
					model_mode: 'sft',
					created_at: ''
				})
			]
		});
		const summary = makeSong({
			...loadedSongDefaults(),
			title: 'Updated title',
			generation_count: 0,
			generations: []
		});
		const merged = overlaySongList([loaded], [summary])[0];
		expect(merged.title).toBe('Updated title');
		expect(merged.generation_count).toBe(1);
		expect(merged.generations).toHaveLength(1);
	});

	it('overlaySongList raises generation_count without dropping loaded takes', () => {
		const loaded = makeSong({
			...loadedSongDefaults(),
			generations: [
				makeGen({
					mp3_path: 'a1/song_v1.mp3',
					wav_path: 'a1/song_v1.wav',
					seed: 42,
					model_mode: 'sft',
					created_at: ''
				})
			]
		});
		const summary = makeSong({
			...loadedSongDefaults(),
			generation_count: 2,
			generations: []
		});
		const merged = overlaySongList([loaded], [summary])[0];
		expect(merged.generation_count).toBe(2);
		expect(merged.generations).toHaveLength(1);
	});

	it('overlaySongList preserves loaded takes across a browse reset', () => {
		const existing = [
			makeSong({
				...loadedSongDefaults(),
				generations: [
					makeGen({
						mp3_path: 'a1/song_v1.mp3',
						wav_path: 'a1/song_v1.wav',
						seed: 42,
						model_mode: 'sft',
						created_at: ''
					})
				]
			})
		];
		const incoming = [makeSong({ ...loadedSongDefaults(), generation_count: 0, generations: [] })];
		expect(overlaySongList(existing, incoming)[0].generations).toHaveLength(1);
	});

	it('upsertSongInList appends an absent song and replaces a present one', () => {
		songList.set([makeSong({ ...loadedSongDefaults(), id: 'a' })]);
		upsertSongInList(makeSong({ ...loadedSongDefaults(), id: 'b', title: 'B' }));
		upsertSongInList(makeSong({ ...loadedSongDefaults(), id: 'a', title: 'A2' }));
		const byId = new Map(get(songList).map((s) => [s.id, s.title]));
		expect([byId.get('a'), byId.get('b')]).toEqual(['A2', 'B']);
	});
});

describe('ensureAllAlbumsLoaded', () => {
	it('follows has_more across pages until the full list is loaded', async () => {
		vi.mocked(fetchAlbums)
			.mockResolvedValueOnce({
				items: [
					makeAlbum({ title: 'Album', song_count: 0, created_at: '' }),
					makeAlbum({ title: 'Album', song_count: 0, created_at: '', id: 'a2' })
				],
				total: 3,
				offset: 0,
				limit: 2,
				has_more: true
			})
			.mockResolvedValueOnce({
				items: [makeAlbum({ title: 'Album', song_count: 0, created_at: '', id: 'a3' })],
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
			items: [makeAlbum({ title: 'Album', song_count: 0, created_at: '' })],
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
			items: [makeAlbum({ title: 'Album', song_count: 0, created_at: '' })],
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
		albumList.set([
			makeAlbum({ title: 'Album', song_count: 0, created_at: '', id: 'a-from-grid' })
		]);
		resolvePage?.({
			items: [makeAlbum({ title: 'Album', song_count: 0, created_at: '' })],
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
