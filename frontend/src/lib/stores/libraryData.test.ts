import { makeAlbum, makeGeneration as makeGen, makeSong } from '$lib/test-utils/factories';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { AlbumItem, PaginatedResponse, SongItem } from '$lib/api/types';
import { ApiError, NetworkError } from '$lib/api/fetch';
import { RAIL_LIBRARY_LOAD_ERROR, UNREACHABLE_RELOAD_DELAYS_MS } from '$lib/constants';
import {
	reportResourceStreamReachable,
	resetConnectivityForTests,
	whenBackOnline
} from './connectivity';

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
	albumSongsLoadFailure,
	allAlbumsLoad,
	allAlbumsLoadFailure,
	cancelAlbumSongLoads,
	ensureAllAlbumsLoaded,
	loadSongsForAlbum,
	overlaySongList,
	replaceSongInList,
	rereadAllAlbums,
	resetLibraryDataForTests,
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
	vi.useRealTimers();
	songList.set([]);
	albumList.set([]);
	resetLibraryDataForTests();
	resetConnectivityForTests();
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
		'names a refusal ($failure) readably when album songs fail to load',
		async ({ err, error }) => {
			vi.mocked(fetchSongs).mockRejectedValueOnce(err);
			await loadSongsForAlbum('a1');
			expect(get(albumSongsLoad).a1).toBe('failed');
			expect(get(albumSongsLoadFailure('a1'))).toBe(error);
		}
	);

	it('under the offline strip names no album-songs failure and loads the songs once back online', async () => {
		reportResourceStreamReachable(false);
		vi.mocked(fetchSongs)
			.mockRejectedValueOnce(OFFLINE)
			.mockResolvedValueOnce({
				items: [makeSong({ ...loadedSongDefaults(), album_id: 'a1' })],
				total: 1,
				offset: 0,
				limit: 200,
				has_more: false
			});
		await loadSongsForAlbum('a1');
		expect(get(albumSongsLoad).a1).toBe('unreachable');
		expect(get(albumSongsLoadFailure('a1'))).toBeNull();

		reportResourceStreamReachable(true);

		await vi.waitFor(() => expect(get(albumSongsLoad).a1).toBe('idle'));
		expect(get(songList).map((item) => item.id)).toEqual(['s1']);
		expect(fetchSongs).toHaveBeenCalledTimes(2);
	});

	it('while no strip shows, reloads album songs on a bounded backoff, then names the failure', async () => {
		vi.useFakeTimers();
		vi.mocked(fetchSongs).mockRejectedValue(OFFLINE);

		await loadSongsForAlbum('a1');
		expect(get(albumSongsLoadFailure('a1'))).toBeNull();
		await vi.advanceTimersByTimeAsync(UNREACHABLE_RELOAD_DELAYS_MS.reduce((a, b) => a + b, 0));

		expect(fetchSongs).toHaveBeenCalledTimes(1 + UNREACHABLE_RELOAD_DELAYS_MS.length);
		expect(get(albumSongsLoadFailure('a1'))).toBe('Failed to load songs');
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
		expect(get(albumSongsLoad).a1).toBe('idle');
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

	it('records a load the network swallowed as unreachable, with no failure text of its own', async () => {
		vi.mocked(fetchAlbums).mockRejectedValueOnce(OFFLINE);
		const ok = await ensureAllAlbumsLoaded();
		expect(ok).toBe(false);
		expect(get(allAlbumsLoad)).toEqual({ status: 'unreachable', error: null });
		expect(get(allAlbumsLoadFailure)).toBeNull();
	});

	it('while no strip shows, reloads on a bounded backoff, then names the failure until a load starts', async () => {
		vi.useFakeTimers();
		vi.mocked(fetchAlbums).mockRejectedValue(OFFLINE);

		await ensureAllAlbumsLoaded();
		await vi.advanceTimersByTimeAsync(UNREACHABLE_RELOAD_DELAYS_MS.reduce((a, b) => a + b, 0));

		expect(fetchAlbums).toHaveBeenCalledTimes(1 + UNREACHABLE_RELOAD_DELAYS_MS.length);
		expect(get(allAlbumsLoadFailure)).toBe(RAIL_LIBRARY_LOAD_ERROR);

		let resolvePage: ((value: PaginatedResponse<AlbumItem>) => void) | undefined;
		vi.mocked(fetchAlbums).mockImplementationOnce(
			() => new Promise((resolve) => (resolvePage = resolve))
		);
		const retry = ensureAllAlbumsLoaded();
		expect(get(allAlbumsLoadFailure)).toBeNull();
		resolvePage?.({ items: [makeAlbum()], total: 1, offset: 0, limit: 50, has_more: false });

		expect(await retry).toBe(true);
		expect(get(allAlbumsLoadFailure)).toBeNull();
	});

	it('under the offline strip names no failure and loads again once back online', async () => {
		reportResourceStreamReachable(false);
		vi.mocked(fetchAlbums).mockRejectedValueOnce(OFFLINE);
		await ensureAllAlbumsLoaded();
		expect(get(allAlbumsLoadFailure)).toBeNull();

		reportResourceStreamReachable(true);

		await vi.waitFor(() => expect(get(allAlbumsLoad).status).toBe('ready'));
		expect(fetchAlbums).toHaveBeenCalledTimes(2);
	});

	it('a gap re-read the network swallowed reads every album again on the same backoff', async () => {
		vi.useFakeTimers();
		albumList.set([makeAlbum({ id: 'a1' }), makeAlbum({ id: 'deleted-elsewhere' })]);
		allAlbumsLoad.set({ status: 'ready', error: null });
		vi.mocked(fetchAlbums)
			.mockRejectedValueOnce(OFFLINE)
			.mockResolvedValueOnce({
				items: [makeAlbum({ id: 'a1' })],
				total: 1,
				offset: 0,
				limit: 50,
				has_more: false
			});

		expect(await rereadAllAlbums()).toBe(false);
		await vi.advanceTimersByTimeAsync(UNREACHABLE_RELOAD_DELAYS_MS[0]);

		expect(get(allAlbumsLoad).status).toBe('ready');
		expect(get(albumList).map((a) => a.id)).toEqual(['a1']);
	});

	it('a gap re-read swallowed offline still replaces the list when a merge reads first on reconnect', async () => {
		albumList.set([makeAlbum({ id: 'a1' }), makeAlbum({ id: 'deleted-elsewhere' })]);
		allAlbumsLoad.set({ status: 'ready', error: null });
		const stopWallCatchUp = whenBackOnline(() => void ensureAllAlbumsLoaded());
		reportResourceStreamReachable(false);
		vi.mocked(fetchAlbums)
			.mockRejectedValueOnce(OFFLINE)
			.mockResolvedValueOnce({
				items: [makeAlbum({ id: 'a1' })],
				total: 1,
				offset: 0,
				limit: 50,
				has_more: false
			});
		expect(await rereadAllAlbums()).toBe(false);

		reportResourceStreamReachable(true);

		await vi.waitFor(() => expect(get(allAlbumsLoad).status).toBe('ready'));
		expect(get(albumList).map((a) => a.id)).toEqual(['a1']);
		stopWallCatchUp();
	});

	it.each([
		{
			failure: 'a server answer without a reason',
			err: new ApiError(500, '', '/api/x'),
			shown: RAIL_LIBRARY_LOAD_ERROR
		},
		{
			failure: 'a server reason',
			err: new ApiError(503, 'Library is migrating', '/api/x'),
			shown: 'Library is migrating'
		}
	])(
		'records a retryable error naming $failure readably when albums fail to load',
		async ({ err, shown }) => {
			vi.mocked(fetchAlbums).mockRejectedValueOnce(err);
			const ok = await ensureAllAlbumsLoaded();
			expect(ok).toBe(false);
			expect(get(allAlbumsLoad).status).toBe('error');
			expect(get(allAlbumsLoadFailure)).toBe(shown);
		}
	);
});
