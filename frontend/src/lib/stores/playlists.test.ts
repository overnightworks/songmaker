import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { createPlaylist, fetchPlaylist, fetchPlaylists } from '$lib/api/client';
import { LIBRARY_PLAYLISTS_ERROR } from '$lib/constants';
import { toasts } from '$lib/stores/toast';
import { ApiError } from '$lib/api/fetch';
import type { PlaylistDetailItem, PlaylistItem } from '$lib/api/types';
import {
	createNewPlaylist,
	ensurePlaylistsLoaded,
	loadPlaylistDetail,
	loadPlaylists,
	playlistDetailLoad,
	playlistList,
	playlistLoad,
	resetPlaylists,
	selectedPlaylistDetail,
	selectedPlaylistId
} from './playlists';

vi.mock('$lib/api/client', () => ({
	fetchPlaylists: vi.fn(),
	fetchPlaylist: vi.fn(),
	createPlaylist: vi.fn(),
	deletePlaylistApi: vi.fn(),
	updatePlaylist: vi.fn(),
	addGenerationToPlaylist: vi.fn(),
	addSongToPlaylist: vi.fn(),
	addAlbumToPlaylist: vi.fn(),
	removeFromPlaylist: vi.fn(),
	reorderPlaylistEntry: vi.fn()
}));

function makeDetail(id: string, overrides: Partial<PlaylistDetailItem> = {}): PlaylistDetailItem {
	return {
		id,
		title: id,
		slug: id,
		entry_count: 0,
		is_shared: false,
		share_slug: null,
		album_covers: [],
		created_at: '',
		entries: [],
		...overrides
	};
}

beforeEach(() => {
	resetPlaylists();
	toasts.set([]);
});

afterEach(() => {
	resetPlaylists();
	toasts.set([]);
	// vitest 4: restoreAllMocks only rewinds vi.spyOn spies now; the
	// module-level vi.fn() stubs from vi.mock('$lib/api/client', ...) above
	// need an explicit clear or their call counts leak into the next test.
	vi.clearAllMocks();
	vi.restoreAllMocks();
	vi.useRealTimers();
});

describe('loadPlaylistDetail', () => {
	it('does not let a slow first load overwrite a later selection', async () => {
		let resolveA: ((value: PlaylistDetailItem) => void) | undefined;
		vi.mocked(fetchPlaylist).mockImplementationOnce(
			() =>
				new Promise((resolve) => {
					resolveA = resolve;
				})
		);
		vi.mocked(fetchPlaylist).mockResolvedValueOnce(makeDetail('b'));

		const first = loadPlaylistDetail('a');
		const second = loadPlaylistDetail('b');
		await second;
		resolveA?.(makeDetail('a'));
		await first;

		expect(get(selectedPlaylistId)).toBe('b');
		expect(get(selectedPlaylistDetail)?.id).toBe('b');
	});

	it('dedupes concurrent opens of the same playlist into a single fetch', async () => {
		vi.mocked(fetchPlaylist).mockResolvedValueOnce(makeDetail('a'));

		await Promise.all([loadPlaylistDetail('a'), loadPlaylistDetail('a')]);

		expect(fetchPlaylist).toHaveBeenCalledTimes(1);
		expect(get(selectedPlaylistDetail)?.id).toBe('a');
		expect(get(playlistDetailLoad).status).toBe('ready');
	});

	it('reuses a still-fresh detail instead of refetching on reopen', async () => {
		vi.useFakeTimers();
		vi.mocked(fetchPlaylist).mockResolvedValueOnce(makeDetail('a'));

		await loadPlaylistDetail('a');
		vi.advanceTimersByTime(1_000);
		await loadPlaylistDetail('a');

		expect(fetchPlaylist).toHaveBeenCalledTimes(1);
		expect(get(selectedPlaylistDetail)?.id).toBe('a');
	});

	it('refetches once the cached detail goes stale', async () => {
		vi.useFakeTimers();
		vi.mocked(fetchPlaylist).mockResolvedValue(makeDetail('a'));

		await loadPlaylistDetail('a');
		vi.advanceTimersByTime(16_000);
		await loadPlaylistDetail('a');

		expect(fetchPlaylist).toHaveBeenCalledTimes(2);
	});

	it('forceRefresh bypasses a still-fresh cached detail', async () => {
		vi.mocked(fetchPlaylist).mockResolvedValue(makeDetail('a'));

		await loadPlaylistDetail('a');
		await loadPlaylistDetail('a', { forceRefresh: true });

		expect(fetchPlaylist).toHaveBeenCalledTimes(2);
	});

	it('forceRefresh bypasses an in-flight fetch so the later call wins', async () => {
		// Two quick mutations on the same playlist (e.g. add then remove a
		// track) both force-refresh. The first's fetch must not be adopted
		// by the second -- each gets its own request, and the request that
		// is still current when its fetch resolves wins (#139).
		let resolveFirst: ((value: PlaylistDetailItem) => void) | undefined;
		vi.mocked(fetchPlaylist).mockImplementationOnce(
			() =>
				new Promise((resolve) => {
					resolveFirst = resolve;
				})
		);
		vi.mocked(fetchPlaylist).mockResolvedValueOnce(makeDetail('a', { title: 'Second' }));

		const first = loadPlaylistDetail('a', { forceRefresh: true });
		const second = loadPlaylistDetail('a', { forceRefresh: true });
		await second;
		resolveFirst?.(makeDetail('a', { title: 'First' }));
		await first;

		expect(fetchPlaylist).toHaveBeenCalledTimes(2);
		expect(get(selectedPlaylistDetail)?.title).toBe('Second');
	});

	it('does not let a superseded request poison the cache for a later reopen', async () => {
		// remove A -> R1 (forced), remove B -> R2 (forced); R1 (now stale)
		// lands last. A later plain reopen within the freshness window must
		// serve R2's snapshot from the cache, not R1's stale one (#139).
		let resolveFirst: ((value: PlaylistDetailItem) => void) | undefined;
		vi.mocked(fetchPlaylist).mockImplementationOnce(
			() =>
				new Promise((resolve) => {
					resolveFirst = resolve;
				})
		);
		vi.mocked(fetchPlaylist).mockResolvedValueOnce(makeDetail('a', { title: 'Second' }));

		const first = loadPlaylistDetail('a', { forceRefresh: true });
		const second = loadPlaylistDetail('a', { forceRefresh: true });
		await second;
		resolveFirst?.(makeDetail('a', { title: 'First' }));
		await first;

		await loadPlaylistDetail('a');

		expect(fetchPlaylist).toHaveBeenCalledTimes(2);
		expect(get(selectedPlaylistDetail)?.title).toBe('Second');
	});

	it('clears the collection when the playlist is gone', async () => {
		vi.mocked(fetchPlaylist).mockRejectedValueOnce(
			new ApiError(404, 'gone', '/api/playlists/gone')
		);

		await loadPlaylistDetail('gone');

		expect(get(selectedPlaylistId)).toBeNull();
		expect(get(selectedPlaylistDetail)).toBeNull();
		expect(get(playlistDetailLoad)).toEqual({ status: 'idle', error: null });
		expect(get(toasts)).toEqual([]);
	});

	it('never leaves the previous playlist rows under a rate-limited open', async () => {
		vi.mocked(fetchPlaylist).mockResolvedValueOnce(makeDetail('a'));
		await loadPlaylistDetail('a');
		expect(get(selectedPlaylistDetail)?.id).toBe('a');

		vi.mocked(fetchPlaylist).mockRejectedValueOnce(
			new ApiError(429, 'Too many requests', '/api/playlists/b')
		);
		await loadPlaylistDetail('b');

		expect(get(selectedPlaylistId)).toBe('b');
		expect(get(selectedPlaylistDetail)).toBeNull();
		expect(get(playlistDetailLoad)).toEqual({
			status: 'error',
			error: 'Too many requests'
		});
		expect(get(toasts)).toEqual([
			expect.objectContaining({ message: 'Too many requests', type: 'error' })
		]);
	});
});

describe('loadPlaylists', () => {
	it('records an error without throwing so the albums section can stay up', async () => {
		vi.mocked(fetchPlaylists).mockRejectedValueOnce(new Error('offline'));
		const ok = await loadPlaylists();
		expect(ok).toBe(false);
		expect(get(playlistLoad)).toEqual({ status: 'error', error: 'offline' });
	});

	it('ensurePlaylistsLoaded does not refetch when already ready', async () => {
		vi.mocked(fetchPlaylists).mockResolvedValueOnce([]);
		expect(await ensurePlaylistsLoaded()).toBe(true);
		expect(await ensurePlaylistsLoaded()).toBe(true);
		expect(fetchPlaylists).toHaveBeenCalledTimes(1);
		expect(get(playlistList)).toEqual([]);
		expect(get(playlistLoad).status).toBe('ready');
	});

	it('dedupes concurrent playlist-list loads', async () => {
		vi.mocked(fetchPlaylists).mockResolvedValueOnce([]);

		await Promise.all([loadPlaylists(), loadPlaylists()]);

		expect(fetchPlaylists).toHaveBeenCalledTimes(1);
	});

	it('uses the named load error when the failure is not an Error', async () => {
		vi.mocked(fetchPlaylists).mockRejectedValueOnce('nope');
		await loadPlaylists();
		expect(get(playlistLoad).error).toBe(LIBRARY_PLAYLISTS_ERROR);
	});

	it('keeps a playlist created while the lazy fetch is still in flight', async () => {
		let resolveList: ((value: PlaylistItem[]) => void) | undefined;
		vi.mocked(fetchPlaylists).mockImplementationOnce(
			() =>
				new Promise((resolve) => {
					resolveList = resolve;
				})
		);
		vi.mocked(createPlaylist).mockResolvedValueOnce({
			id: 'new',
			title: 'New',
			slug: 'new',
			entry_count: 0,
			is_shared: false,
			share_slug: null,
			album_covers: [],
			created_at: '2026-01-01T00:00:00+00:00'
		});

		const pending = loadPlaylists();
		await createNewPlaylist('New');
		expect(get(playlistList).map((item) => item.id)).toEqual(['new']);
		resolveList?.([]);
		await pending;
		expect(get(playlistList).map((item) => item.id)).toEqual(['new']);
	});
});
