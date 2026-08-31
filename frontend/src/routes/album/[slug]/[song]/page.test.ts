import { mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, SongItem } from '$lib/api/types';
import { ApiError } from '$lib/api/fetch';
import { EDITOR_LYRICS_LABEL } from '$lib/constants';
import { openCollection, resetCollectionForTests } from '$lib/stores/collection';
import { albumList, songList } from '$lib/stores/libraryData';
import { detailTab, resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { resetResourceSyncForTests, startLibraryResourceSync } from '$lib/stores/resourceSync';
import { selectedGenerationId, selectedSongId } from '$lib/stores/player';

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
const routeSearch = vi.hoisted(() => new URLSearchParams());

vi.mock('$app/state', () => ({
	page: {
		params: routeParams,
		get url() {
			return { searchParams: routeSearch };
		}
	}
}));
// Stands in for the router the way the real one behaves for this app: it
// moves the history entry, but nothing here re-resolves the mounted route.
vi.mock('$app/navigation', () => ({
	goto: vi.fn((url: string, options?: { replaceState?: boolean }) => {
		if (options?.replaceState) history.replaceState(null, '', url);
		else history.pushState(null, '', url);
		return Promise.resolve();
	}),
	afterNavigate: vi.fn()
}));
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('$lib/api/albums', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/albums')>()),
	fetchAlbum: api.fetchAlbum,
	fetchAlbums: api.fetchAlbums
}));
vi.mock('$lib/api/songs', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/songs')>()),
	fetchSong: api.fetchSong,
	fetchSongs: api.fetchSongs,
	fetchVersions: api.fetchVersions
}));
vi.mock('$lib/api/library', () => ({
	searchLibrary: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false })
}));
vi.mock('$lib/api/client', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/client')>()),
	fetchSongs: api.fetchSongs,
	fetchSong: api.fetchSong,
	fetchVersions: api.fetchVersions,
	fetchLastFailedGeneration: api.fetchLastFailedGeneration,
	fetchActiveModels: api.fetchActiveModels
}));

import SongAddressPage from './+page.svelte';

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

function album(overrides: Partial<AlbumItem> = {}): AlbumItem {
	return {
		id: ALBUM_SLUG,
		title: ALBUM_TITLE,
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 1,
		picked_count: 0,
		is_shared: false,
		share_slug: null,
		cover: null,
		created_at: '2026-01-01T00:00:00+00:00',
		is_archived: false,
		...overrides
	};
}

function song(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 'song-1',
		slug: SONG_SLUG,
		title: TRACK_TITLE,
		album_id: ALBUM_SLUG,
		album_title: ALBUM_TITLE,
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: '',
		prompt: '',
		bpm: 120,
		audio_duration: 180,
		key_scale: 'Am',
		generation_params: null,
		version_count: 1,
		generation_count: 0,
		best_scores: null,
		best_rating: null,
		generations: [],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null,
		...overrides
	};
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

function openAddress(): HTMLElement {
	const target = document.createElement('div');
	document.body.append(target);
	mounted.push(mount(SongAddressPage, { target }));
	return target;
}

// A tab that knows nothing but the address: no library stores, no history
// state, nothing opened before -- with the live library stream running, which
// routes/+layout.svelte starts for every signed-in library route.
function coldTabAt(pathname: string, search = ''): void {
	const [, , albumSlug, songSlug] = pathname.split('/');
	routeParams.slug = albumSlug;
	routeParams.song = songSlug ?? '';
	routeSearch.forEach((_, key) => routeSearch.delete(key));
	new URLSearchParams(search).forEach((value, key) => routeSearch.set(key, value));
	history.replaceState(null, '', pathname + search);
	albumList.set([]);
	songList.set([]);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	resetCollectionForTests();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetResourceSyncForTests();
	startLibraryResourceSync();
}

beforeEach(() => {
	vi.stubGlobal('EventSource', FakeEventSource);
	api.fetchAlbum.mockReset().mockResolvedValue(album());
	api.fetchAlbums.mockReset().mockResolvedValue(page([]));
	api.fetchSongs.mockReset().mockResolvedValue(page([song()]));
	api.fetchSong.mockReset().mockResolvedValue(song());
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
	it('shows the song in the editor', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain(TRACK_TITLE));
		expect(target.textContent).toContain(EDITOR_LYRICS_LABEL);
	});

	it('keeps the address it was opened with', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain(TRACK_TITLE));
		expect(window.location.pathname).toBe(`/album/${ALBUM_SLUG}/${SONG_SLUG}`);
		expect(get(openCollection)).toEqual({ kind: 'album', id: ALBUM_SLUG });
	});

	it('opens the addressed song even when the album listing does not carry it yet', async () => {
		api.fetchAlbums.mockResolvedValue(page([]));
		api.fetchSongs.mockResolvedValue(page([song()]));

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

	it('shows the song after Try again once the failure is over', async () => {
		const target = openAddress();
		await vi.waitFor(() => expect(target.textContent).toContain('Album service is down'));
		api.fetchAlbum.mockResolvedValue(album());

		requireElement(target, 'button.address-action').click();

		await vi.waitFor(() => expect(target.textContent).toContain(TRACK_TITLE));
	});
});
