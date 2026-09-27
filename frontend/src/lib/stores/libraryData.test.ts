import { makeAlbum, makeGeneration as makeGen, makeSong } from '$lib/test-utils/factories';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { AlbumItem, PaginatedResponse, SongItem } from '$lib/api/types';
import { ApiError, NetworkError } from '$lib/api/fetch';

const OFFLINE = new NetworkError('/api/x', new TypeError('Failed to fetch'));

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

import { fetchAlbums, fetchSongs } from '$lib/api/client';
import {
	albumList,
	albumSongsLoad,
	allAlbumsLoad,
	cancelAlbumSongLoads,
	ensureAllAlbumsLoaded,
	loadSongsForAlbum,
	overlaySongList,
	replaceSongInList,
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

	it.each([
		{ failure: 'a network failure', err: OFFLINE, error: 'Failed to load songs' },
		{
			failure: 'a server answer without a reason',
			err: new ApiError(500, '', '/api/x'),
			error: 'Failed to load songs'
		},
		{
			failure: 'a browser error',
			err: new Error('Failed to fetch'),
			error: 'Failed to load songs'
		},
		{
			failure: 'a server reason',
			err: new ApiError(409, 'Album is locked', '/api/x'),
			error: 'Album is locked'
		}
	])(
		'records a retryable error naming $failure readably when album songs fail to load',
		async ({ err, error }) => {
			vi.mocked(fetchSongs).mockRejectedValueOnce(err);
			await loadSongsForAlbum('a1');
			expect(get(albumSongsLoad).a1).toEqual({ status: 'error', error });
		}
	);

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

	it.each([
		{ failure: 'a network failure', err: OFFLINE, error: 'Failed to load albums' },
		{
			failure: 'a server answer without a reason',
			err: new ApiError(500, '', '/api/x'),
			error: 'Failed to load albums'
		},
		{
			failure: 'a server reason',
			err: new ApiError(503, 'Library is migrating', '/api/x'),
			error: 'Library is migrating'
		}
	])(
		'records a retryable error naming $failure readably when albums fail to load',
		async ({ err, error }) => {
			vi.mocked(fetchAlbums).mockRejectedValueOnce(err);
			const ok = await ensureAllAlbumsLoaded();
			expect(ok).toBe(false);
			expect(get(allAlbumsLoad)).toEqual({ status: 'error', error });
		}
	);
});
