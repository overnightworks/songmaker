import {
	historyEntry,
	historyLength,
	replaceHistoryEntry
} from '#lib/test-utils/library-history.ts';
import { startFakeRouter } from '#lib/test-utils/app-navigation.ts';
import { makeAlbum as album, makeSong as song } from '#lib/test-utils/factories.ts';
import { mount, unmount, type Component } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AlbumItem, SongItem } from '#lib/api/types.ts';
import { HOME_ROUTE_PATH, LIBRARY_ROUTE_PATH } from '#lib/routes/addresses.ts';
import { resetCollectionForTests } from '#lib/stores/collection.ts';
import { albumList, songList } from '#lib/stores/libraryData.ts';
import { resetLibraryContextForTests } from '#lib/stores/libraryContext.ts';
import { resetLibrarySearchForTests } from '#lib/stores/librarySearch.ts';
import { resetResourceSyncForTests, startLibraryResourceSync } from '#lib/stores/resourceSync.ts';
import { selectedGenerationId, selectedSongId } from '#lib/stores/player.ts';
import { toasts } from '#lib/stores/toast.ts';

const SONG_ID = 'song-uuid-1';
const GENERATION_ID = 'gen-uuid-1';
const ALBUM_SLUG = 'anfield';

const api = vi.hoisted(() => ({
	fetchAlbum: vi.fn(),
	fetchAlbums: vi.fn(),
	fetchSongs: vi.fn(),
	fetchSong: vi.fn(),
	fetchVersions: vi.fn(),
	fetchLastFailedGeneration: vi.fn(),
	fetchActiveModels: vi.fn()
}));

vi.mock('$app/state', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppState()
);
vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('$app/paths', async () => (await import('#lib/test-utils/app-paths.ts')).fakeAppPaths());
vi.mock('#lib/api/songs.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/songs.ts')>()),
	fetchSong: api.fetchSong,
	fetchSongs: api.fetchSongs
}));
vi.mock('#lib/api/albums.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/albums.ts')>()),
	fetchAlbum: api.fetchAlbum,
	fetchAlbums: api.fetchAlbums
}));
vi.mock('#lib/api/library.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/library.ts')>()),
	searchLibrary: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false })
}));
vi.mock('#lib/api/client.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/client.ts')>()),
	fetchSongs: api.fetchSongs,
	fetchSong: api.fetchSong,
	fetchVersions: api.fetchVersions,
	fetchLastFailedGeneration: api.fetchLastFailedGeneration,
	fetchActiveModels: api.fetchActiveModels
}));

import HomeAddressHarness from './harness.svelte';
import LibraryAddressHarness from './library/harness.svelte';

interface RoutePage {
	route: string;
	harness: Component;
	surface: string;
	shown: string;
	hidden: string[];
}

const ROUTE_PAGES: RoutePage[] = [
	{
		route: HOME_ROUTE_PATH,
		harness: HomeAddressHarness,
		surface: 'home',
		shown: '.library-home',
		hidden: ['.library-wall']
	},
	{
		route: LIBRARY_ROUTE_PATH,
		harness: LibraryAddressHarness,
		surface: 'browse',
		shown: '.library-wall',
		hidden: ['.library-home', '[aria-label="Listen"]']
	}
];

// The live stream the workspace bootstrap waits for -- same fake as the
// sibling address suites (issue #276): emitting `hello` is all it takes to
// make the real ResourceSyncController run its snapshot load.
class FakeEventSource {
	private readonly listeners = new Map<string, Array<(event: Event) => void>>();
	onerror: ((event: Event) => void) | null = null;

	constructor() {
		queueMicrotask(() => this.emit('hello', JSON.stringify({ high_water_mark: '0' })));
	}

	addEventListener(type: string, listener: (event: Event) => void): void {
		this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
	}

	removeEventListener(type: string, listener: (event: Event) => void): void {
		this.listeners.set(
			type,
			(this.listeners.get(type) ?? []).filter((l) => l !== listener)
		);
	}

	close(): void {}

	private emit(type: string, data: string): void {
		for (const listener of this.listeners.get(type) ?? []) {
			listener(new MessageEvent(type, { data }));
		}
	}
}

function page(items: SongItem[] | AlbumItem[]) {
	return { items, total: items.length, offset: 0, limit: 50, has_more: false };
}

const mounted: Array<ReturnType<typeof mount>> = [];

function requireElement(root: HTMLElement, selector: string): HTMLElement {
	const found = root.querySelector<HTMLElement>(selector);
	if (!found) throw new Error(`missing ${selector}`);
	return found;
}

// The workspace wrapper `(library)/+layout.svelte` marks `inert` while an
// overlay is up (issue #276 review fix) -- `inert` itself, not tab order,
// carries the contract here: jsdom has no `inert` IDL property, so a real
// keyboard-navigation probe would only prove jsdom's gap, not the app's.
function workspaceWrapper(root: HTMLElement): HTMLElement {
	return requireElement(root, '.workspace-wrapper');
}

function openAddress(harness: Component = HomeAddressHarness): HTMLElement {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(harness, { target }));
	return target;
}

// A tab that knows nothing but its address:
// no library stores, no history state, nothing opened before -- with the
// live library stream running, which routes/+layout.svelte starts for every
// signed-in library route.
function coldTabAt(search: string, route: string = HOME_ROUTE_PATH): void {
	replaceHistoryEntry(route + search);
	startFakeRouter();
	albumList.set([]);
	songList.set([]);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	toasts.set([]);
	resetCollectionForTests();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetResourceSyncForTests();
	startLibraryResourceSync();
}

beforeEach(() => {
	vi.stubGlobal('EventSource', FakeEventSource);
	vi.stubGlobal(
		'fetch',
		vi.fn(async () => Response.json({ items: [] }))
	);
	api.fetchAlbum
		.mockReset()
		.mockResolvedValue(album({ id: ALBUM_SLUG, title: 'Anfield', share_slug: null, cover: null }));
	api.fetchAlbums.mockReset().mockResolvedValue(page([]));
	api.fetchSongs.mockReset().mockResolvedValue(page([]));
	api.fetchSong.mockReset().mockResolvedValue(song());
	api.fetchVersions.mockReset().mockResolvedValue([]);
	api.fetchLastFailedGeneration.mockReset().mockResolvedValue({ job: null });
	api.fetchActiveModels.mockReset().mockResolvedValue([]);
	coldTabAt('');
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

describe.each(ROUTE_PAGES)('$route with no query', ({ route, harness, surface, shown, hidden }) => {
	it('1354_rule_31: resolves its entry without adding a Back step', async () => {
		coldTabAt('', route);
		const length = historyLength();

		const target = openAddress(harness);

		await vi.waitFor(() => expect(target.querySelector(shown)).not.toBeNull());
		await vi.waitFor(() => expect(historyEntry()).toMatchObject({ surface, songId: null }));
		for (const selector of hidden) expect(target.querySelector(selector)).toBeNull();
		expect(location.pathname).toBe(route);
		expect(historyLength()).toBe(length);
	});
});

describe('/library with a query', () => {
	it('1354_rule_31: ignores the query', async () => {
		coldTabAt('?x=1', LIBRARY_ROUTE_PATH);

		const target = openAddress(LibraryAddressHarness);

		await vi.waitFor(() => expect(target.querySelector('.library-wall')).not.toBeNull());
		await vi.waitFor(() =>
			expect(historyEntry()).toMatchObject({ surface: 'browse', songId: null })
		);
		expect(target.querySelector('.address-overlay')).toBeNull();
		expect(api.fetchSong).not.toHaveBeenCalled();
		expect(location.pathname).toBe(LIBRARY_ROUTE_PATH);
	});
});

describe('/ with a query', () => {
	it.each([
		'?song=',
		'?song=&gen=' + GENERATION_ID,
		`?song=${SONG_ID}`,
		`?song=${SONG_ID}&gen=${GENERATION_ID}`,
		'?x=1'
	])('1354_rule_31: shows Home, drops the query and fetches no song for %s', async (query) => {
		coldTabAt(query);
		const target = openAddress();

		await vi.waitFor(() => {
			expect(target.querySelector('.library-home')).not.toBeNull();
			expect(target.querySelector('.library-wall')).toBeNull();
			expect(target.querySelector('.address-overlay')).toBeNull();
			expect(workspaceWrapper(target).hasAttribute('inert')).toBe(false);
			expect(location.search).toBe('');
		});
		expect(api.fetchSong).not.toHaveBeenCalled();
	});
});
