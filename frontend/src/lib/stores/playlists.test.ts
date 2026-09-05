import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import {
	addAlbumToPlaylist,
	addGenerationToPlaylist,
	addSongToPlaylist,
	createPlaylist,
	deletePlaylistApi,
	deletePlaylistCover as deletePlaylistCoverApi,
	fetchPlaylist,
	fetchPlaylists,
	removeFromPlaylist,
	reorderPlaylistEntry,
	uploadPlaylistCover as uploadPlaylistCoverApi,
	updatePlaylist
} from '$lib/api/client';
import { LIBRARY_PLAYLISTS_ERROR } from '$lib/constants';
import { toasts } from '$lib/stores/toast';
import { ApiError } from '$lib/api/fetch';
import type { AddAlbumToPlaylistResult, PlaylistDetailItem, PlaylistItem } from '$lib/api/types';
import {
	createNewPlaylist,
	deletePlaylist,
	deletePlaylistCover,
	ensurePlaylistsLoaded,
	movePlaylistEntry,
	addGenerationToPlaylist as addGeneration,
	addSongToPlaylist as addSong,
	addAlbumToPlaylist as addAlbum,
	loadPlaylistDetail,
	loadPlaylists,
	playlistDetailLoad,
	playlistList,
	playlistLoad,
	renamePlaylist,
	removePlaylistEntry,
	resetPlaylists,
	selectedPlaylistDetail,
	selectedPlaylistId,
	uploadPlaylistCover
} from './playlists';

vi.mock('$lib/api/client', () => ({
	fetchPlaylists: vi.fn(),
	fetchPlaylist: vi.fn(),
	createPlaylist: vi.fn(),
	deletePlaylistApi: vi.fn(),
	deletePlaylistCover: vi.fn(),
	updatePlaylist: vi.fn(),
	addGenerationToPlaylist: vi.fn(),
	addSongToPlaylist: vi.fn(),
	addAlbumToPlaylist: vi.fn(),
	removeFromPlaylist: vi.fn(),
	reorderPlaylistEntry: vi.fn(),
	uploadPlaylistCover: vi.fn()
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

function makePlaylist(id: string, overrides: Partial<PlaylistItem> = {}): PlaylistItem {
	return {
		id,
		title: id,
		slug: id,
		entry_count: 0,
		is_shared: false,
		share_slug: null,
		album_covers: [],
		created_at: '',
		...overrides
	};
}

const albumMutationResult: AddAlbumToPlaylistResult = { added_count: 2, skipped: [] };

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

describe('playlist mutations', () => {
	it('mirrors an uploaded and removed cover into the list and open detail', async () => {
		const original = makePlaylist('p1');
		const customCover = {
			card: '/api/playlists/p1/cover?variant=card&v=custom.png',
			detail: '/api/playlists/p1/cover?variant=detail&v=custom.png'
		};
		playlistList.set([original]);
		vi.mocked(fetchPlaylist).mockResolvedValue(makeDetail('p1'));
		vi.mocked(uploadPlaylistCoverApi).mockResolvedValue(makePlaylist('p1', { cover: customCover }));
		vi.mocked(deletePlaylistCoverApi).mockResolvedValue(makePlaylist('p1', { cover: null }));

		await loadPlaylistDetail('p1');
		const file = new File(['cover'], 'cover.png', { type: 'image/png' });
		await uploadPlaylistCover('p1', file);

		expect(uploadPlaylistCoverApi).toHaveBeenCalledWith('p1', file);
		expect(get(playlistList)[0]?.cover).toEqual(customCover);
		expect(get(selectedPlaylistDetail)?.cover).toEqual(customCover);

		await deletePlaylistCover('p1');

		expect(deletePlaylistCoverApi).toHaveBeenCalledWith('p1');
		expect(get(playlistList)[0]?.cover).toBeNull();
		expect(get(selectedPlaylistDetail)?.cover).toBeNull();
	});

	it('mirrors creating, renaming, and deleting a selected playlist in library state', async () => {
		const original = makePlaylist('p1', { title: 'Original' });
		const created = makePlaylist('p2', { title: 'New playlist' });
		const renamed = makePlaylist('p1', { title: 'Renamed' });
		vi.mocked(fetchPlaylist).mockResolvedValue(makeDetail('p1', { title: 'Original' }));
		vi.mocked(createPlaylist).mockResolvedValue(created);
		vi.mocked(updatePlaylist).mockResolvedValue(renamed);
		vi.mocked(deletePlaylistApi).mockResolvedValue(undefined);
		playlistList.set([original]);

		await loadPlaylistDetail('p1');
		await createNewPlaylist('New playlist');
		await renamePlaylist('p1', 'Renamed');

		expect(createPlaylist).toHaveBeenCalledWith('New playlist');
		expect(updatePlaylist).toHaveBeenCalledWith('p1', 'Renamed');
		expect(get(playlistList)).toEqual([renamed, created]);
		expect(get(selectedPlaylistDetail)?.title).toBe('Renamed');

		await deletePlaylist('p1');

		expect(deletePlaylistApi).toHaveBeenCalledWith('p1');
		expect(get(playlistList)).toEqual([created]);
		expect(get(selectedPlaylistId)).toBeNull();
		expect(get(selectedPlaylistDetail)).toBeNull();
	});

	it.each([
		{
			description: 'adds a generation',
			mutate: () => addGeneration('p1', 'g1'),
			assertRequest: () => expect(addGenerationToPlaylist).toHaveBeenCalledWith('p1', 'g1')
		},
		{
			description: 'adds a song',
			mutate: () => addSong('p1', 's1'),
			assertRequest: () => expect(addSongToPlaylist).toHaveBeenCalledWith('p1', 's1')
		},
		{
			description: 'adds an album',
			mutate: () => addAlbum('p1', 'a1'),
			assertRequest: () => expect(addAlbumToPlaylist).toHaveBeenCalledWith('p1', 'a1'),
			expectedResult: albumMutationResult
		},
		{
			description: 'removes an entry',
			mutate: () => removePlaylistEntry('p1', 'entry-1'),
			assertRequest: () => expect(removeFromPlaylist).toHaveBeenCalledWith('p1', 'entry-1')
		},
		{
			description: 'moves an entry',
			mutate: () => movePlaylistEntry('p1', 'entry-2', 3),
			assertRequest: () => expect(reorderPlaylistEntry).toHaveBeenCalledWith('p1', 'entry-2', 3)
		}
	])(
		'$description refreshes the library summary',
		async ({ mutate, assertRequest, expectedResult }) => {
			const refreshed = makePlaylist('p1', { entry_count: 4 });
			vi.mocked(fetchPlaylists).mockResolvedValue([refreshed]);
			vi.mocked(addAlbumToPlaylist).mockResolvedValue(albumMutationResult);

			const result = await mutate();

			assertRequest();
			if (expectedResult) expect(result).toEqual(expectedResult);
			expect(get(playlistList)).toEqual([refreshed]);
		}
	);

	it('reloads the open playlist detail after an entry mutation', async () => {
		vi.mocked(fetchPlaylist)
			.mockResolvedValueOnce(makeDetail('p1', { entry_count: 1 }))
			.mockResolvedValueOnce(makeDetail('p1', { entry_count: 2 }));
		vi.mocked(fetchPlaylists).mockResolvedValue([makePlaylist('p1', { entry_count: 2 })]);

		await loadPlaylistDetail('p1');
		await addGeneration('p1', 'g1');

		expect(fetchPlaylist).toHaveBeenCalledTimes(2);
		expect(get(selectedPlaylistDetail)?.entry_count).toBe(2);
	});
});
