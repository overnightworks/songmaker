import { historyEntry, historyLength, replaceHistoryEntry } from '$lib/test-utils/library-history';
import { startFakeRouter } from '$lib/test-utils/app-navigation';
import { mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LIBRARY_ROUTE_PATH } from '$lib/routes/addresses';
import { resetCollectionForTests } from '$lib/stores/collection';
import { albumList, songList } from '$lib/stores/libraryData';
import { resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { resetResourceSyncForTests, resourceSync } from '$lib/stores/resourceSync';
import { selectedGenerationId, selectedSongId } from '$lib/stores/player';

const api = vi.hoisted(() => ({
	fetchAlbums: vi.fn(),
	fetchSong: vi.fn(),
	fetchLibraryListen: vi.fn(),
	fetchActiveModels: vi.fn()
}));

vi.mock('$app/state', async () => (await import('$lib/test-utils/app-navigation')).fakeAppState());
vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('$lib/api/albums', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/albums')>()),
	fetchAlbums: api.fetchAlbums
}));
vi.mock('$lib/api/songs', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/songs')>()),
	fetchSong: api.fetchSong
}));
vi.mock('$lib/api/library', () => ({
	searchLibrary: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false }),
	fetchLibraryListen: api.fetchLibraryListen
}));
vi.mock('$lib/api/client', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/client')>()),
	fetchSong: api.fetchSong,
	fetchActiveModels: api.fetchActiveModels
}));

import LibraryAddressHarness from './harness.svelte';

const SONG_ID = 'song-uuid-1';

const mounted: Array<ReturnType<typeof mount>> = [];

function openAddress(): HTMLElement {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(LibraryAddressHarness, { target }));
	return target;
}

function coldTabAt(search: string): void {
	replaceHistoryEntry(LIBRARY_ROUTE_PATH + search);
	startFakeRouter();
	albumList.set([]);
	songList.set([]);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	resetCollectionForTests();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetResourceSyncForTests();
	resourceSync.update((state) => ({ ...state, status: 'live', ready: true }));
}

beforeEach(() => {
	api.fetchAlbums
		.mockReset()
		.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50, has_more: false });
	api.fetchSong.mockReset();
	api.fetchLibraryListen.mockReset().mockResolvedValue({ items: [] });
	api.fetchActiveModels.mockReset().mockResolvedValue([]);
});

afterEach(() => {
	for (const app of mounted.splice(0)) void unmount(app);
	document.body.innerHTML = '';
	resetResourceSyncForTests();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetCollectionForTests();
});

describe('/library', () => {
	it('1354_rule_31: shows the Library wall without Continue and resolves its entry without a Back step', async () => {
		coldTabAt('');
		const length = historyLength();

		const target = openAddress();

		await vi.waitFor(() => expect(target.querySelector('.library-wall')).not.toBeNull());
		await vi.waitFor(() =>
			expect(historyEntry()).toMatchObject({ surface: 'browse', songId: null })
		);
		expect(target.querySelector('[aria-label="Continue"]')).toBeNull();
		expect(target.querySelector('.library-home')).toBeNull();
		expect(location.pathname).toBe(LIBRARY_ROUTE_PATH);
		expect(historyLength()).toBe(length);
	});

	it('1354_rule_31: leaves a ?song= query alone, since only Home redirects the legacy form', async () => {
		coldTabAt(`?song=${SONG_ID}`);

		const target = openAddress();

		await vi.waitFor(() => expect(target.querySelector('.library-wall')).not.toBeNull());
		expect(target.querySelector('.address-overlay')).toBeNull();
		expect(api.fetchSong).not.toHaveBeenCalled();
		expect(location.pathname + location.search).toBe(`${LIBRARY_ROUTE_PATH}?song=${SONG_ID}`);
	});
});
