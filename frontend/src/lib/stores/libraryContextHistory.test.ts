import { pressBack, pressForward, replaceHistoryEntry } from '#lib/test-utils/library-history.ts';
import { makeAlbum as album, makeSong as song } from '#lib/test-utils/factories.ts';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { ApiError } from '#lib/api/fetch.ts';
import { deferred } from '#lib/test-utils/album-cover-editor.ts';
import { openCollection } from '#lib/stores/collection.ts';
import { resetLibrarySearchForTests, searchQuery } from '#lib/stores/librarySearch.ts';
import { albumList, allAlbumsLoad, songList } from '#lib/stores/libraryData.ts';
import { selectedAlbumId, selectedGenerationId, selectedSongId } from '#lib/stores/player.ts';
import { resetPlaylistsForTests } from '#lib/stores/playlists.ts';

const fetchAlbum = vi.fn();
const fetchAlbums = vi.fn();
const fetchSong = vi.fn();
const fetchSongs = vi.fn();
const searchLibrary = vi.fn();

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('$app/state', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppState()
);
vi.mock('#lib/api/library.ts', () => ({
	searchLibrary: (...args: unknown[]) => searchLibrary(...args)
}));
vi.mock('#lib/api/albums.ts', () => ({
	fetchAlbum: (...args: unknown[]) => fetchAlbum(...args),
	fetchAlbums: (...args: unknown[]) => fetchAlbums(...args)
}));
vi.mock('#lib/api/songs.ts', () => ({
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchSongs: (...args: unknown[]) => fetchSongs(...args)
}));
vi.mock('#lib/api/client.ts', () => ({
	fetchAlbums: (...args: unknown[]) => fetchAlbums(...args),
	fetchPlaylists: vi.fn().mockResolvedValue([]),
	fetchPlaylist: vi.fn(),
	fetchSongs: (...args: unknown[]) => fetchSongs(...args),
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchLastFailedGeneration: vi.fn().mockResolvedValue(null),
	fetchActiveGeneration: vi.fn().mockResolvedValue(null),
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
	attachLandingHandler,
	installHistoryController,
	pushEntry,
	replaceEntry
} from '#lib/history/historyController.ts';
import { albumRoutePath, LIBRARY_ROUTE_PATH } from '#lib/routes/addresses.ts';

import {
	applyLibraryHistory,
	isLibraryHistoryState,
	libraryRootState,
	resetLibraryContextForTests,
	type LibraryHistoryState
} from './libraryContext';

function detailState(overrides: Partial<LibraryHistoryState>): LibraryHistoryState {
	return {
		...libraryRootState(),
		surface: 'detail',
		collection: { kind: 'album', id: 'a1' },
		...overrides
	};
}

// The apply under test lands on a pushed entry and waits on the network;
// history moves back before the network answers.
async function applyOutrunByBack(
	state: LibraryHistoryState,
	whenWaiting: () => void,
	release: () => void
) {
	replaceEntry(LIBRARY_ROUTE_PATH, { library: libraryRootState() });
	pushEntry(albumRoutePath('a1'), { library: state });
	const applying = applyLibraryHistory(state);
	await vi.waitFor(whenWaiting);
	await pressBack();
	release();
	return applying;
}

beforeEach(() => {
	for (const fetch of [fetchAlbum, fetchAlbums, fetchSong, fetchSongs, searchLibrary]) {
		fetch.mockReset();
	}
	fetchAlbums.mockResolvedValue({ items: [], total: 0 });
	fetchSongs.mockResolvedValue({ items: [], total: 0 });
	searchLibrary.mockResolvedValue({ items: [], next_cursor: null, has_more: false });
	fetchAlbum.mockResolvedValue(album({ id: 'a1' }));
	fetchSong.mockResolvedValue(song({ id: 's1', album_id: 'a1' }));
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
	searchQuery.set('');
	albumList.set([]);
	allAlbumsLoad.set({ status: 'idle', error: null });
	songList.set([]);
	selectedAlbumId.set(null);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	replaceHistoryEntry('/');
	installHistoryController();
	attachLandingHandler(() => undefined);
});

afterEach(() => {
	vi.useRealTimers();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
});

describe('a history entry stored by an older build', () => {
	it.each([
		{ field: 'surface', value: 'rail' },
		{ field: 'query', value: 7 },
		{ field: 'sort', value: 'sideways' },
		{ field: 'albumOffset', value: '0' },
		{ field: 'songOffset', value: '0' },
		{ field: 'searchLoadedCount', value: '3' },
		{ field: 'searchLoadedCount', value: -1 },
		{ field: 'scrollAnchor', value: '0' },
		{ field: 'searchCursor', value: 4 },
		{ field: 'songId', value: 4 },
		{ field: 'generationId', value: 4 },
		{ field: 'collection', value: 'a1' }
	])('is not a library entry when $field is $value', ({ field, value }) => {
		expect(isLibraryHistoryState({ ...libraryRootState(), [field]: value })).toBe(false);
	});
});

describe('history moves on while an entry is being applied', () => {
	it.each([
		{
			waits: 'the listing',
			state: () =>
				detailState({ collection: null, surface: 'browse', query: 'tide', songId: 's1' }),
			arrange: () => {
				const gate = deferred<{ items: never[]; total: number }>();
				fetchAlbums.mockImplementationOnce(() => gate.promise);
				return () => gate.resolve({ items: [], total: 0 });
			},
			unchanged: () => expect(searchLibrary).not.toHaveBeenCalled()
		},
		{
			waits: 'the search',
			state: () => detailState({ surface: 'browse', query: 'tide', songId: 's1' }),
			arrange: () => {
				const gate = deferred<{ items: never[]; next_cursor: null; has_more: false }>();
				searchLibrary.mockImplementationOnce(() => gate.promise);
				return () => gate.resolve({ items: [], next_cursor: null, has_more: false });
			},
			unchanged: () => expect(fetchAlbum).not.toHaveBeenCalled()
		},
		{
			waits: 'the selected song',
			state: () => detailState({ collection: null, songId: 's1' }),
			arrange: () => {
				const gate = deferred<ReturnType<typeof song>>();
				fetchSong.mockImplementationOnce(() => gate.promise);
				return () => gate.resolve(song({ id: 's1', album_id: 'a1' }));
			},
			unchanged: () => expect(get(songList)).toEqual([])
		},
		{
			waits: "the selected song's album",
			state: () => detailState({ collection: null, songId: 's1' }),
			arrange: () => {
				songList.set([song({ id: 's1', album_id: 'a1', generation_count: 0, generations: [] })]);
				const gate = deferred<ReturnType<typeof album>>();
				fetchAlbum.mockImplementationOnce(() => gate.promise);
				return () => gate.resolve(album({ id: 'a1' }));
			},
			unchanged: () => expect(get(albumList)).toEqual([])
		},
		{
			waits: 'the album of the open collection',
			state: () => detailState({}),
			arrange: () => {
				const gate = deferred<ReturnType<typeof album>>();
				fetchAlbum.mockImplementationOnce(() => gate.promise);
				return () => gate.reject(new ApiError(404, 'gone', '/api/albums/a1'));
			},
			unchanged: () => expect(get(openCollection)).toEqual({ kind: 'album', id: 'a1' })
		}
	])(
		'stops an apply waiting on $waits and changes nothing more',
		async ({ state, arrange, unchanged }) => {
			const release = arrange();
			const target = state();
			const asked = () => {
				expect(
					[fetchAlbums, searchLibrary, fetchSong, fetchAlbum].some(
						(api) => api.mock.calls.length > 0
					)
				).toBe(true);
			};

			const applying = applyOutrunByBack(target, asked, release);

			await expect(applying).resolves.toBe(false);
			unchanged();
			await pressForward();
		}
	);
});

describe('an album the history names that was deleted elsewhere', () => {
	it.each([
		{ failure: new ApiError(404, 'gone', '/api/albums/a1'), kept: null },
		{
			failure: new ApiError(500, 'boom', '/api/albums/a1'),
			kept: { kind: 'album', id: 'a1' }
		}
	])('closes the collection only on a $failure.status', async ({ failure, kept }) => {
		fetchAlbum.mockRejectedValue(failure);

		await applyLibraryHistory(detailState({}));

		expect(get(openCollection)).toEqual(kept);
	});
});
