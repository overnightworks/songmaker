import { historyEntry, replaceHistoryEntry } from '#lib/test-utils/library-history.ts';
import { routerHistoryEntry } from '#lib/test-utils/router-history-layout.ts';
import { makeAlbum as album, makeSong as song } from '#lib/test-utils/factories.ts';
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';
import { get } from 'svelte/store';
import { ApiError } from '#lib/api/fetch.ts';
import { startFakeRouter } from '#lib/test-utils/app-navigation.ts';
import { installHistoryController } from '#lib/history/historyController.ts';
import { forgetSyncedSong, resetLibrarySearchForTests } from '#lib/stores/librarySearch.ts';
import {
	libraryRootState,
	librarySurface,
	resetLibraryContextForTests
} from '#lib/stores/libraryContext.ts';
import { resetCollectionForTests } from '#lib/stores/collection.ts';
import { albumList, songList } from '#lib/stores/libraryData.ts';
import { selectedGenerationId, selectedSongId } from '#lib/stores/player.ts';
import { resetPlaylistsForTests } from '#lib/stores/playlists.ts';
import { LIBRARY_ROUTE_PATH } from '#lib/routes/addresses.ts';
import { resetGenerationFailuresForTests } from '#lib/stores/jobs.ts';
import { toasts } from '#lib/stores/toast.ts';
import { SONG_LINK_NOT_FOUND_TOAST } from '#lib/constants.ts';

const fetchSong = vi.fn();

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('$app/state', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppState()
);
vi.mock('$app/paths', () => ({
	resolve: vi.fn((path: string) => path)
}));
vi.mock('#lib/api/library.ts', () => ({
	searchLibrary: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false })
}));
vi.mock('#lib/api/albums.ts', () => ({
	fetchAlbum: vi.fn().mockImplementation(async () => album({ share_slug: null })),
	fetchAlbums: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, has_more: false })
}));
vi.mock('#lib/api/songs.ts', () => ({
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
vi.mock('#lib/api/client.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/client.ts')>()),
	fetchActiveModels: vi.fn().mockResolvedValue([]),
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false }),
	fetchPlaylists: vi.fn().mockResolvedValue([]),
	fetchLastFailedGeneration: vi.fn().mockResolvedValue({ job: null }),
	fetchActiveGeneration: vi.fn().mockResolvedValue(null),
	fetchVersions: vi.fn().mockResolvedValue([])
}));

import { followShellLayers, initNavigation, leaveGoneSong, selectSong } from './navigation';

let stopFollowingShellLayers: () => void = () => undefined;

beforeEach(() => {
	fetchSong.mockReset();
	resetGenerationFailuresForTests();
	toasts.set([]);
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
	stopFollowingShellLayers = followShellLayers();
	albumList.set([album({ share_slug: null })]);
	songList.set([]);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	resetCollectionForTests();
	replaceHistoryEntry(LIBRARY_ROUTE_PATH);
	startFakeRouter();
	installHistoryController();
});

afterEach(() => {
	stopFollowingShellLayers();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
	resetCollectionForTests();
});

describe('a song deleted meanwhile', () => {
	const album = { kind: 'album' as const, id: 'a1' };
	let reportGone = () => {};
	beforeEach(() => {
		const lookup = new Promise<never>((_, reject) => {
			reportGone = () => reject(new ApiError(404, 'Song not found', '/api/songs/gone'));
		});
		fetchSong.mockImplementation((id: string) =>
			id === 'gone' ? lookup : Promise.resolve(song({ slug: 's2', id: 's2' }))
		);
	});
	const backOntoGoneSong = (collection: typeof album | null) => {
		const library = { ...libraryRootState(), collection, songId: 'gone' };
		const entry = routerHistoryEntry({ library });
		replaceHistoryEntry(LIBRARY_ROUTE_PATH, entry);
		window.dispatchEvent(new PopStateEvent('popstate', { state: entry }));
	};
	const opened = [
		['its link is opened', () => selectSong('gone'), 'browse'],
		['Back lands on it, an album open', () => backOntoGoneSong(album), 'detail'],
		['Back lands on it, no collection open', () => backOntoGoneSong(null), 'browse']
	] as const;
	it.each(opened)(
		'tells the person and leaves an address that no longer names it when %s',
		async (_, open, surface) => {
			onTestFinished(initNavigation());
			void open();
			await vi.waitFor(() => expect(fetchSong).toHaveBeenCalledWith('gone'));
			reportGone();

			await vi.waitFor(() =>
				expect(get(toasts).map((t) => t.message)).toContain(SONG_LINK_NOT_FOUND_TOAST)
			);
			expect(get(selectedSongId)).toBeNull();
			expect(get(librarySurface)).toBe(surface);
			await vi.waitFor(() => expect(historyEntry()).toMatchObject({ songId: null }));
		}
	);

	it.each(opened)('keeps a newer selection when the late 404 arrives and %s', async (_, open) => {
		onTestFinished(initNavigation());
		void open();
		await vi.waitFor(() => expect(fetchSong).toHaveBeenCalledWith('gone'));
		await selectSong('s2');
		reportGone();
		await new Promise((resolve) => setTimeout(resolve, 0));

		expect(get(selectedSongId)).toBe('s2');
		expect(get(toasts)).toHaveLength(0);
	});
});

describe('a song deleted elsewhere while open', () => {
	it('tells the person and leaves for its collection', async () => {
		onTestFinished(initNavigation());
		songList.set([song({ id: 'gone', slug: 'gone' })]);
		await selectSong('gone');
		forgetSyncedSong('gone');
		leaveGoneSong('gone');

		expect(get(toasts).map((t) => t.message)).toEqual([SONG_LINK_NOT_FOUND_TOAST]);
		expect(get(selectedSongId)).toBeNull();
		expect(get(librarySurface)).toBe('detail');
		await vi.waitFor(() =>
			expect(historyEntry()).toMatchObject({
				collection: { kind: 'album', id: 'a1' },
				songId: null
			})
		);
	});

	it.each([
		['a library entry of another song', { ...libraryRootState(), songId: 's2' }],
		['an entry that is no library entry', {}]
	])('stays quiet with nothing selected and %s standing', (_, page) => {
		onTestFinished(initNavigation());
		replaceHistoryEntry(LIBRARY_ROUTE_PATH, routerHistoryEntry({ library: page }));
		leaveGoneSong('gone');

		expect(get(toasts)).toEqual([]);
	});
});
