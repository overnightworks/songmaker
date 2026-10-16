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

vi.mock('$app/state', async () => (await import('$lib/test-utils/app-navigation')).fakeAppState());
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));

import LibraryAddressHarness from './harness.svelte';

const SONG_ID = 'song-uuid-1';
const EMPTY_PAGE = { items: [], total: 0, offset: 0, limit: 50, has_more: false };

const requested: string[] = [];
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
	requested.length = 0;
	vi.stubGlobal(
		'fetch',
		vi.fn(async (path: string) => {
			requested.push(path);
			return Response.json(path.startsWith('/api/albums') ? EMPTY_PAGE : []);
		})
	);
});

afterEach(() => {
	for (const app of mounted.splice(0)) void unmount(app);
	document.body.innerHTML = '';
	resetResourceSyncForTests();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetCollectionForTests();
	vi.unstubAllGlobals();
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
		expect(requested.filter((path) => path.startsWith('/api/songs'))).toEqual([]);
		expect(location.pathname + location.search).toBe(`${LIBRARY_ROUTE_PATH}?song=${SONG_ID}`);
	});
});
