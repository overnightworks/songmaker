import { replaceHistoryEntry } from '#lib/test-utils/library-history.ts';
import { makeAlbum as album, makeGeneration, makeSong as song } from '#lib/test-utils/factories.ts';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { ApiError } from '#lib/api/fetch.ts';
import { startFakeRouter } from '#lib/test-utils/app-navigation.ts';
import { installHistoryController } from '#lib/history/historyController.ts';
import { resetLibrarySearchForTests } from '#lib/stores/librarySearch.ts';
import { resetLibraryContextForTests } from '#lib/stores/libraryContext.ts';
import { resetCollectionForTests } from '#lib/stores/collection.ts';
import { albumList, songList } from '#lib/stores/libraryData.ts';
import { selectedGenerationId, selectedSongId } from '#lib/stores/player.ts';
import { resetPlaylistsForTests } from '#lib/stores/playlists.ts';
import { LIBRARY_ROUTE_PATH } from '#lib/routes/addresses.ts';
import { resetGenerationFailuresForTests } from '#lib/stores/jobs.ts';
import { toasts } from '#lib/stores/toast.ts';

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

import {
	followShellLayers,
	initNavigation,
	openAlbum,
	openAppPage,
	openRailSearchTarget,
	selectSong
} from './navigation';

let stopFollowingShellLayers: () => void = () => undefined;
let stopNavigation: () => void = () => undefined;

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
	stopNavigation = initNavigation();
});

afterEach(() => {
	stopNavigation();
	stopFollowingShellLayers();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
	resetCollectionForTests();
});

// A search hit hands navigation its song id alone, and a playlist row its
// song_id alone: neither carries the album or slug a song address names, and
// the song is in no list yet. The address keeps the page the user is on while
// the song loads, then takes the song's own address.
describe('a song opened by id alone', () => {
	const openers = [
		{
			opened: 'a search hit',
			open: () => openRailSearchTarget({ kind: 'song', id: 'unlisted' })
		},
		{ opened: 'a playlist row', open: () => selectSong('unlisted') }
	];

	async function openFromAlbumPage(open: () => Promise<void>): Promise<string> {
		await openAlbum('a1');
		const standing = location.pathname;
		await open();
		return standing;
	}

	it.each(openers)('keeps the page it was opened from while $opened loads', async ({ open }) => {
		let failLoad: (error: Error) => void = () => undefined;
		fetchSong.mockReturnValue(new Promise((_resolve, reject) => (failLoad = reject)));

		const standing = await openFromAlbumPage(open);

		expect(get(selectedSongId)).toBe('unlisted');
		expect(location.pathname).toBe(standing);
		expect(location.search).toBe('');
		failLoad(new ApiError(500, 'unavailable', '/api/songs/unlisted'));
	});

	it.each(openers)("holds the song's own address once $opened has loaded", async ({ open }) => {
		fetchSong.mockResolvedValue(
			song({ id: 'unlisted', album_id: 'a1', slug: 'tide', generations: [makeGeneration()] })
		);

		await openFromAlbumPage(open);

		await vi.waitFor(() => expect(location.pathname).toBe('/album/a1/tide'));
		expect(location.search).toBe('');
	});

	it.each(openers)(
		'keeps the page it was opened from when $opened fails to load',
		async ({ open }) => {
			fetchSong.mockRejectedValue(new ApiError(500, 'unavailable', '/api/songs/unlisted'));

			const standing = await openFromAlbumPage(open);

			await vi.waitFor(() => expect(fetchSong).toHaveBeenCalled());
			expect(location.pathname).toBe(standing);
			expect(location.search).toBe('');
		}
	);

	it('leaves the user on Settings when the song loads after they moved there', async () => {
		let finishLoad: (loaded: ReturnType<typeof song>) => void = () => undefined;
		fetchSong.mockReturnValue(new Promise((resolve) => (finishLoad = resolve)));
		await openFromAlbumPage(openers[0].open);

		await openAppPage('/settings/voices');
		finishLoad(
			song({ id: 'unlisted', album_id: 'a1', slug: 'tide', generations: [makeGeneration()] })
		);

		await vi.waitFor(() => expect(get(songList).some((item) => item.id === 'unlisted')).toBe(true));
		expect(location.pathname).toBe('/settings/voices');
	});
});
