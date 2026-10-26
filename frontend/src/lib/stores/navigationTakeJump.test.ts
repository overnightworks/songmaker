import {
	historyEntry,
	historyLength,
	pressBack,
	pressForward,
	replaceHistoryEntry
} from '$lib/test-utils/library-history';
import { makeAlbum as album, makeGeneration, makeSong as song } from '$lib/test-utils/factories';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { goto } from '$app/navigation';
import { startFakeRouter } from '$lib/test-utils/app-navigation';
import { installHistoryController } from '$lib/history/historyController';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { libraryHistoryStepsLanded, resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { resetCollectionForTests } from '$lib/stores/collection';
import { albumList, songList } from '$lib/stores/libraryData';
import { selectedGenerationId, selectedSongId } from '$lib/stores/player';
import { resetPlaylistsForTests } from '$lib/stores/playlists';
import { LIBRARY_ROUTE_PATH } from '$lib/routes/addresses';
import { activeJobs, removeJob, resetGenerationFailuresForTests } from '$lib/stores/jobs';
import { toasts } from '$lib/stores/toast';

const fetchSong = vi.fn();
const fetchAlbum = vi.fn();
const fetchPlaylists = vi.fn();
const fetchPlaylist = vi.fn();
const fetchLastFailedGeneration = vi.fn();
const fetchActiveGeneration = vi.fn();

// goto actually changes the URL (via the History API, like the real
// SvelteKit goto) so tests can assert the landed-on route, not just that
// goto was called with some argument (see issue #264's done-when).
vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);
vi.mock('$app/state', async () => (await import('$lib/test-utils/app-navigation')).fakeAppState());
vi.mock('$app/paths', () => ({
	resolve: vi.fn((path: string) => path)
}));
vi.mock('$lib/api/library', () => ({
	searchLibrary: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false })
}));
vi.mock('$lib/api/albums', () => ({
	fetchAlbum: (...args: unknown[]) => fetchAlbum(...args),
	fetchAlbums: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, has_more: false })
}));
vi.mock('$lib/api/songs', () => ({
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false })
}));
vi.mock('$lib/api/loras', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/loras')>()),
	listLoras: vi.fn().mockResolvedValue([])
}));
vi.mock('$lib/api/client', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/client')>()),
	fetchHealth: vi.fn().mockResolvedValue({ status: 'ok' }),
	fetchActiveModels: vi.fn().mockResolvedValue([]),
	fetchSong: (...args: unknown[]) => fetchSong(...args),
	fetchSongs: vi
		.fn()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 200, has_more: false }),
	fetchPlaylists: (...args: unknown[]) => fetchPlaylists(...args),
	fetchPlaylist: (...args: unknown[]) => fetchPlaylist(...args),
	fetchLastFailedGeneration: (...args: unknown[]) => fetchLastFailedGeneration(...args),
	fetchActiveGeneration: (...args: unknown[]) => fetchActiveGeneration(...args),
	createPlaylist: vi.fn(),
	deletePlaylistApi: vi.fn(),
	updatePlaylist: vi.fn(),
	addGenerationToPlaylist: vi.fn(),
	addSongToPlaylist: vi.fn(),
	addAlbumToPlaylist: vi.fn(),
	removeFromPlaylist: vi.fn(),
	reorderPlaylistEntry: vi.fn(),
	fetchVersions: vi.fn().mockResolvedValue([]),
	updateSong: vi.fn(),
	deleteVersion: vi.fn()
}));

import {
	followShellLayers,
	initNavigation,
	jumpToTake,
	openAlbum,
	resetNavigationForTests,
	selectSong
} from './navigation';

const SOURCE_TAKE_ID = 'take-source';
const OTHER_TAKE_ID = 'take-other';
const TIDE_DEFAULTS = { title: 'Tide', album_title: 'Nachtstrom', generations: [makeGeneration()] };

let stopFollowingShellLayers: () => void = () => undefined;
let stopNavigation: () => void = () => undefined;

beforeEach(() => {
	fetchSong.mockReset().mockImplementation(async () => song({ ...TIDE_DEFAULTS, slug: 's1' }));
	fetchAlbum.mockReset();
	fetchPlaylists.mockReset().mockResolvedValue([]);
	fetchPlaylist.mockReset();
	fetchLastFailedGeneration.mockReset().mockResolvedValue({ job: null });
	fetchActiveGeneration.mockReset().mockResolvedValue(null);
	resetGenerationFailuresForTests();
	toasts.set([]);
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
	resetNavigationForTests();
	stopFollowingShellLayers = followShellLayers();
	albumList.set([album({ share_slug: null })]);
	songList.set([song({ ...TIDE_DEFAULTS, slug: 's1' })]);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	resetCollectionForTests();
	replaceHistoryEntry(LIBRARY_ROUTE_PATH);
	startFakeRouter();
	installHistoryController();
	vi.mocked(goto).mockClear();
	stopNavigation = initNavigation();
});

afterEach(() => {
	stopNavigation();
	stopFollowingShellLayers();
	for (const { job } of get(activeJobs)) removeJob(job.id);
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylistsForTests();
	resetCollectionForTests();
});

async function openTheSongFromItsAlbum(): Promise<void> {
	await openAlbum('a1');
	await selectSong('s1');
	await libraryHistoryStepsLanded();
}

function anchor(takeId: string): string {
	return `#take-${takeId}`;
}

describe('jumping to a take of the song on screen', () => {
	it('writes one entry of the song at the take anchor and keeps the song open', async () => {
		await openTheSongFromItsAlbum();
		const entries = historyLength();

		await jumpToTake(SOURCE_TAKE_ID);
		await libraryHistoryStepsLanded();

		expect(location.pathname).toBe('/album/a1/s1');
		expect(location.hash).toBe(anchor(SOURCE_TAKE_ID));
		expect(historyLength()).toBe(entries + 1);
		expect(get(selectedSongId)).toBe('s1');
		expect(historyEntry().songId).toBe('s1');
	});

	it('writes nothing when the address already ends in that anchor', async () => {
		await openTheSongFromItsAlbum();
		await jumpToTake(SOURCE_TAKE_ID);
		await libraryHistoryStepsLanded();
		const entries = historyLength();

		await jumpToTake(SOURCE_TAKE_ID);

		expect(historyLength()).toBe(entries);
		expect(location.hash).toBe(anchor(SOURCE_TAKE_ID));
	});

	it('writes a further entry for another take', async () => {
		await openTheSongFromItsAlbum();
		await jumpToTake(SOURCE_TAKE_ID);
		await libraryHistoryStepsLanded();
		const entries = historyLength();

		await jumpToTake(OTHER_TAKE_ID);
		await libraryHistoryStepsLanded();

		expect(historyLength()).toBe(entries + 1);
		expect(location.hash).toBe(anchor(OTHER_TAKE_ID));
	});

	it('goes Back to the song without the anchor and Forward to the anchor, with the song open', async () => {
		await openTheSongFromItsAlbum();
		await jumpToTake(SOURCE_TAKE_ID);
		await libraryHistoryStepsLanded();

		await pressBack();

		expect(location.pathname).toBe('/album/a1/s1');
		expect(location.hash).toBe('');
		expect(get(selectedSongId)).toBe('s1');

		await pressForward();

		expect(location.hash).toBe(anchor(SOURCE_TAKE_ID));
		expect(get(selectedSongId)).toBe('s1');
	});

	it('steps album, song and anchor in order with no question when the draft is clean', async () => {
		await openTheSongFromItsAlbum();
		await jumpToTake(SOURCE_TAKE_ID);
		await libraryHistoryStepsLanded();

		await pressBack();
		await pressBack();

		expect(location.pathname).toBe('/album/a1');
		expect(get(selectedSongId)).toBeNull();

		await pressForward();
		await pressForward();

		expect(location.pathname).toBe('/album/a1/s1');
		expect(location.hash).toBe(anchor(SOURCE_TAKE_ID));
		expect(get(selectedSongId)).toBe('s1');
	});
});
