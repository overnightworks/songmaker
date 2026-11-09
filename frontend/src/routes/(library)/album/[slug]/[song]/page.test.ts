import { mountAddressRoute, replaceHistoryEntry } from '#lib/test-utils/library-history.ts';
import { makeAlbum as album, makeSong as song } from '#lib/test-utils/factories.ts';
import { mount, tick, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, SongItem } from '#lib/api/types.ts';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import { browserReportsOnline } from '#lib/test-utils/network.ts';
import { EDITOR_LYRICS_LABEL } from '#lib/constants.ts';
import { RESOURCE_SYNC_ERROR } from '#lib/constants/resource-sync.ts';
import { openCollection, resetCollectionForTests } from '#lib/stores/collection.ts';
import { albumList, songList } from '#lib/stores/libraryData.ts';
import {
	detailTab,
	libraryRootState,
	resetLibraryContextForTests
} from '#lib/stores/libraryContext.ts';
import { resetLibrarySearchForTests } from '#lib/stores/librarySearch.ts';
import {
	resetResourceSyncForTests,
	retryResourceSync,
	startLibraryResourceSync
} from '#lib/stores/resourceSync.ts';
import { selectedGenerationId, selectedSongId } from '#lib/stores/player.ts';

const ALBUM_SLUG = 'anfield';
const ALBUM_TITLE = 'Anfield';
const SONG_SLUG = 'stadion-lauf-a';
const TRACK_TITLE = 'Stadion Lauf A';

const api = vi.hoisted(() => ({
	fetchAlbum: vi.fn(),
	fetchAlbums: vi.fn(),
	fetchSongs: vi.fn(),
	fetchSong: vi.fn(),
	fetchVersions: vi.fn(),
	fetchLastFailedGeneration: vi.fn(),
	fetchActiveModels: vi.fn()
}));

const routeParams = vi.hoisted(() => ({ slug: 'anfield', song: 'stadion-lauf-a' }));

vi.mock('$app/state', async () => {
	const { fakePage } = await import('#lib/test-utils/app-navigation.ts');
	return {
		page: {
			params: routeParams,
			get url() {
				return fakePage.url;
			}
		}
	};
});
// Stands in for the router the way the real one behaves for this app: it
// moves the history entry, but nothing here re-resolves the mounted route.
vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('#lib/api/albums.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/albums.ts')>()),
	fetchAlbum: api.fetchAlbum,
	fetchAlbums: api.fetchAlbums
}));
vi.mock('#lib/api/songs.ts', async (importOriginal) => ({
	...(await importOriginal<typeof import('#lib/api/songs.ts')>()),
	fetchSong: api.fetchSong,
	fetchSongs: api.fetchSongs,
	fetchVersions: api.fetchVersions
}));
vi.mock('#lib/api/library.ts', () => ({
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

import SongAddressHarness from './harness.svelte';

// The live stream the workspace bootstrap waits for. Emitting `hello` is all
// it takes to make the real ResourceSyncController run its snapshot load, so
// the cold start below exercises the production restore path instead of a
// stand-in for it.
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

function openAddress(): HTMLElement {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(SongAddressHarness, { target }));
	return target;
}

// A tab that knows nothing but the address: no library stores, no history
// state, nothing opened before -- with the live library stream running, which
// routes/+layout.svelte starts for every signed-in library route.
function coldTabAt(pathname: string, search = ''): void {
	const [, , albumSlug, songSlug] = pathname.split('/');
	routeParams.slug = albumSlug;
	routeParams.song = songSlug ?? '';
	mountAddressRoute(pathname + search);
	albumList.set([]);
	songList.set([]);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	resetCollectionForTests();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetResourceSyncForTests();
	startLibraryResourceSync(vi.fn());
}

beforeEach(() => {
	vi.stubGlobal('EventSource', FakeEventSource);
	api.fetchAlbum.mockReset().mockResolvedValue(album({ id: ALBUM_SLUG, title: ALBUM_TITLE }));
	api.fetchAlbums.mockReset().mockResolvedValue(page([]));
	api.fetchSongs.mockReset().mockResolvedValue(
		page([
			song({
				id: 'song-1',
				generation_count: 0,
				slug: SONG_SLUG,
				title: TRACK_TITLE,
				album_id: ALBUM_SLUG,
				album_title: ALBUM_TITLE
			})
		])
	);
	api.fetchSong.mockReset().mockResolvedValue(
		song({
			id: 'song-1',
			generation_count: 0,
			slug: SONG_SLUG,
			title: TRACK_TITLE,
			album_id: ALBUM_SLUG,
			album_title: ALBUM_TITLE
		})
	);
	api.fetchVersions.mockReset().mockResolvedValue([]);
	api.fetchLastFailedGeneration.mockReset().mockResolvedValue({ job: null });
	api.fetchActiveModels.mockReset().mockResolvedValue([]);
	coldTabAt(`/album/${ALBUM_SLUG}/${SONG_SLUG}`);
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

describe('/album/<slug>/<song-slug> opened cold', () => {
	it('shows the song in the editor on the Edit tab', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain(TRACK_TITLE));
		expect(target.textContent).toContain(EDITOR_LYRICS_LABEL);
		expect(get(detailTab)).toBe('edit');
		expect(workspaceWrapper(target).hasAttribute('inert')).toBe(false);
	});

	it.each(['write', 'generations', 'chat'])(
		'opens the addressed song on Edit when a reload history entry holds the old tab name %s',
		async (oldTabName) => {
			coldTabAt(`/album/${ALBUM_SLUG}/${SONG_SLUG}`);
			replaceHistoryEntry(`/album/${ALBUM_SLUG}/${SONG_SLUG}`, {
				...libraryRootState(),
				surface: 'detail',
				collection: { kind: 'album', id: ALBUM_SLUG },
				songId: 'song-1',
				detailTab: oldTabName as never
			});

			const target = openAddress();

			await vi.waitFor(() => expect(target.textContent).toContain(TRACK_TITLE));
			expect(get(detailTab)).toBe('edit');
		}
	);

	it('keeps the address it was opened with', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain(TRACK_TITLE));
		expect(window.location.pathname).toBe(`/album/${ALBUM_SLUG}/${SONG_SLUG}`);
		expect(get(openCollection)).toEqual({ kind: 'album', id: ALBUM_SLUG });
	});

	it('opens the addressed song even when the album listing does not carry it yet', async () => {
		api.fetchAlbums.mockResolvedValue(page([]));
		api.fetchSongs.mockResolvedValue(
			page([
				song({
					id: 'song-1',
					generation_count: 0,
					slug: SONG_SLUG,
					title: TRACK_TITLE,
					album_id: ALBUM_SLUG,
					album_title: ALBUM_TITLE
				})
			])
		);

		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain(TRACK_TITLE));
		expect(get(selectedSongId)).toBe('song-1');
	});

	it('opens the take named by ?gen alongside the song', async () => {
		coldTabAt(`/album/${ALBUM_SLUG}/${SONG_SLUG}`, '?gen=gen-9');

		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain(TRACK_TITLE));
		expect(get(selectedGenerationId)).toBe('gen-9');
		expect(get(detailTab)).toBe('takes');
	});
});

describe('/album/<slug>/<song-slug> naming no song in a known album', () => {
	it('says the address names no song, with a way back to the album', async () => {
		coldTabAt(`/album/${ALBUM_SLUG}/ghost-song`);

		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain('No such song'));
		const back = requireElement(target, 'a.address-action');
		expect(back.getAttribute('href')).toBe(`/album/${ALBUM_SLUG}`);
		expect(get(openCollection)).toBeNull();
	});
});

describe('/album/<slug>/<song-slug> naming no album', () => {
	beforeEach(() => {
		coldTabAt('/album/ghost/some-song');
		api.fetchAlbum.mockRejectedValue(new ApiError(404, 'Album not found', '/api/albums/ghost'));
	});

	it('says the address names no album instead of showing an empty page', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain('No such album'));
		expect(target.querySelector('[role="alert"]')).not.toBeNull();
	});

	it('stays on the address instead of redirecting to the library', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain('No such album'));
		expect(window.location.pathname).toBe('/album/ghost/some-song');
	});
});

describe('/album/<slug>/<song-slug> whose song cannot be reached', () => {
	beforeEach(() => {
		api.fetchAlbum.mockRejectedValue(new ApiError(500, 'Album service is down', '/api/albums'));
	});

	it('states the failure instead of claiming the song does not exist', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain('Album service is down'));
		expect(target.textContent).not.toContain('No such');
	});

	it('names a lost connection in its own words, never the browser text', async () => {
		api.fetchAlbum.mockRejectedValue(new NetworkError('/api/x', new TypeError('Failed to fetch')));
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain('This song could not be loaded.'));
		expect(target.textContent).not.toContain('Failed to fetch');
	});

	it('offline, shows its one line with Try again and opens by itself once back online', async () => {
		browserReportsOnline(false);
		api.fetchAlbum.mockRejectedValue(new NetworkError('/api/x', new TypeError('Failed to fetch')));
		const target = openAddress();
		await vi.waitFor(() => expect(target.textContent).toContain('This song could not be loaded.'));
		expect(requireElement(target, 'button.address-action').textContent).toBe('Try again');

		api.fetchAlbum.mockResolvedValue(album({ id: ALBUM_SLUG, title: ALBUM_TITLE }));
		browserReportsOnline(true);

		await vi.waitFor(() => expect(target.textContent).toContain(TRACK_TITLE));
	});

	it('shows the song after Try again once the failure is over', async () => {
		const target = openAddress();
		await vi.waitFor(() => expect(target.textContent).toContain('Album service is down'));
		api.fetchAlbum.mockResolvedValue(album({ id: ALBUM_SLUG, title: ALBUM_TITLE }));

		requireElement(target, 'button.address-action').click();

		await vi.waitFor(() => expect(target.textContent).toContain(TRACK_TITLE));
	});

	it('marks the workspace behind it inert, and lifts that once Try again succeeds', async () => {
		const target = openAddress();
		await vi.waitFor(() => expect(target.textContent).toContain('Album service is down'));
		expect(workspaceWrapper(target).hasAttribute('inert')).toBe(true);

		api.fetchAlbum.mockResolvedValue(album({ id: ALBUM_SLUG, title: ALBUM_TITLE }));
		requireElement(target, 'button.address-action').click();

		await vi.waitFor(() => expect(target.textContent).toContain(TRACK_TITLE));
		expect(workspaceWrapper(target).hasAttribute('inert')).toBe(false);
	});
});

describe('/album/<slug>/<song-slug> after the library load failed', () => {
	const LIBRARY_DOWN = 'Library service is down';
	const ALBUM_DOWN = 'Album service is down';
	const libraryUp = () =>
		api.fetchSongs.mockResolvedValue(
			page([
				song({
					id: 'song-1',
					generation_count: 0,
					slug: SONG_SLUG,
					title: TRACK_TITLE,
					album_id: ALBUM_SLUG,
					album_title: ALBUM_TITLE
				})
			])
		);

	function failLibrary(): void {
		api.fetchSongs.mockRejectedValue(new ApiError(500, LIBRARY_DOWN, '/api/songs'));
		api.fetchAlbum.mockRejectedValue(new ApiError(500, ALBUM_DOWN, '/api/albums'));
		coldTabAt(`/album/${ALBUM_SLUG}/${SONG_SLUG}`);
	}

	function recoverLibrary(): void {
		libraryUp();
		api.fetchAlbum.mockResolvedValue(album({ id: ALBUM_SLUG, title: ALBUM_TITLE }));
	}

	async function openFailedAddress(): Promise<HTMLElement> {
		failLibrary();
		const target = openAddress();
		await vi.waitFor(() => expect(target.textContent).toContain(ALBUM_DOWN));
		await vi.waitFor(() => expect(target.textContent).toContain(RESOURCE_SYNC_ERROR));
		return target;
	}

	it('Try again retries the library, shows loading meanwhile, and the song replaces overlay and card on the ready edge', async () => {
		const target = await openFailedAddress();
		recoverLibrary();

		requireElement(target, 'button.address-action').click();
		await tick();
		expect(target.textContent).toContain('Loading song...');
		expect(target.textContent).not.toContain(ALBUM_DOWN);

		await vi.waitFor(() => expect(target.textContent).toContain(TRACK_TITLE));
		expect(target.querySelector('.address-overlay')).toBeNull();
		expect(target.textContent).not.toContain(RESOURCE_SYNC_ERROR);
		expect(workspaceWrapper(target).hasAttribute('inert')).toBe(false);
	});

	it('shows its failure words again when the library retry fails again, and recovers on the next press', async () => {
		const target = await openFailedAddress();

		requireElement(target, 'button.address-action').click();
		await tick();
		expect(target.textContent).toContain('Loading song...');
		await vi.waitFor(() => expect(target.querySelector('button.address-action')).not.toBeNull());
		expect(target.textContent).toContain(ALBUM_DOWN);
		expect(target.textContent).not.toContain(TRACK_TITLE);

		recoverLibrary();
		requireElement(target, 'button.address-action').click();
		await vi.waitFor(() => expect(target.textContent).toContain(TRACK_TITLE));
	});

	it('opens the song when its own load began before the library was ready and failed after it', async () => {
		let failAddress!: (error: Error) => void;
		api.fetchSongs.mockRejectedValue(new ApiError(500, LIBRARY_DOWN, '/api/songs'));
		let releaseRerun!: () => void;
		api.fetchAlbum
			.mockImplementationOnce(() => new Promise((_, reject) => (failAddress = reject)))
			.mockImplementationOnce(
				() =>
					new Promise((resolve) => {
						releaseRerun = () => resolve(album({ id: ALBUM_SLUG, title: ALBUM_TITLE }));
					})
			);
		coldTabAt(`/album/${ALBUM_SLUG}/${SONG_SLUG}`);
		const target = openAddress();
		await vi.waitFor(() => expect(failAddress).toBeDefined());

		recoverLibrary();
		await retryResourceSync();
		failAddress(new ApiError(500, ALBUM_DOWN, '/api/albums'));
		await tick();
		expect(target.querySelector('.address-overlay')?.textContent).toContain('Loading song...');
		expect(target.textContent).not.toContain(ALBUM_DOWN);
		releaseRerun();
		await vi.waitFor(() => expect(target.textContent).toContain(TRACK_TITLE));
		expect(target.querySelector('.address-overlay')).toBeNull();
	});
});
