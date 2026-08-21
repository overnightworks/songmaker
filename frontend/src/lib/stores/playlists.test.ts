import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { createPlaylist, fetchPlaylist, fetchPlaylists } from '$lib/api/client';
import { LIBRARY_PLAYLISTS_ERROR } from '$lib/constants';
import type { PlaylistDetailItem, PlaylistItem } from '$lib/api/types';
import {
	createNewPlaylist,
	ensurePlaylistsLoaded,
	loadPlaylistDetail,
	loadPlaylists,
	playlistList,
	playlistLoad,
	resetPlaylistsForTests,
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

function makeDetail(id: string): PlaylistDetailItem {
	return {
		id,
		title: id,
		entry_count: 0,
		is_shared: false,
		share_slug: null,
		created_at: '',
		entries: []
	};
}

beforeEach(() => {
	resetPlaylistsForTests();
});

afterEach(() => {
	resetPlaylistsForTests();
	vi.restoreAllMocks();
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
			entry_count: 0,
			is_shared: false,
			share_slug: null,
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
