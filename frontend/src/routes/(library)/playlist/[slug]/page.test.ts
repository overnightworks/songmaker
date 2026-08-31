import { mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { PlaylistDetailItem, PlaylistEntryItem, PlaylistItem } from '$lib/api/types';
import { ApiError } from '$lib/api/fetch';
import { openCollection, resetCollectionForTests } from '$lib/stores/collection';
import { albumList, songList } from '$lib/stores/libraryData';
import { resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { resetPlaylists } from '$lib/stores/playlists';
import { resetResourceSyncForTests, startLibraryResourceSync } from '$lib/stores/resourceSync';
import { selectedGenerationId, selectedSongId } from '$lib/stores/player';

const PLAYLIST_SLUG = 'friday-night';
const PLAYLIST_TITLE = 'Friday Night';
const ENTRY_SONG_TITLE = 'Stadion Lauf A';

const api = vi.hoisted(() => ({
	fetchPlaylists: vi.fn(),
	fetchPlaylist: vi.fn(),
	fetchAlbums: vi.fn(),
	fetchSongs: vi.fn(),
	fetchSong: vi.fn(),
	fetchVersions: vi.fn(),
	fetchLastFailedGeneration: vi.fn(),
	fetchActiveModels: vi.fn()
}));

const routeParams = vi.hoisted(() => ({ slug: 'friday-night' }));

vi.mock('$app/state', () => ({ page: { params: routeParams } }));
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
	fetchPlaylists: api.fetchPlaylists,
	fetchPlaylist: api.fetchPlaylist,
	fetchSongs: api.fetchSongs,
	fetchSong: api.fetchSong,
	fetchVersions: api.fetchVersions,
	fetchLastFailedGeneration: api.fetchLastFailedGeneration,
	fetchActiveModels: api.fetchActiveModels
}));

import PlaylistAddressHarness from './harness.svelte';

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

function playlistItem(overrides: Partial<PlaylistItem> = {}): PlaylistItem {
	return {
		id: 'p1',
		title: PLAYLIST_TITLE,
		slug: PLAYLIST_SLUG,
		entry_count: 1,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

function playlistEntry(overrides: Partial<PlaylistEntryItem> = {}): PlaylistEntryItem {
	return {
		id: 'pe1',
		position: 0,
		generation_id: 'g1',
		song_id: 's1',
		song_title: ENTRY_SONG_TITLE,
		album_title: 'Anfield',
		artist: 'Artist',
		generation_number: 1,
		version_number: 1,
		is_picked: true,
		audio_duration: 180,
		mp3_path: 's1/g1.mp3',
		seed: 1,
		model_mode: 'turbo',
		lyrics: null,
		...overrides
	};
}

function playlistDetail(overrides: Partial<PlaylistDetailItem> = {}): PlaylistDetailItem {
	return {
		id: 'p1',
		title: PLAYLIST_TITLE,
		slug: PLAYLIST_SLUG,
		entry_count: 1,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		entries: [playlistEntry()],
		...overrides
	};
}

function page<T>(items: T[]) {
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
	mounted.push(mount(PlaylistAddressHarness, { target }));
	return target;
}

// A tab that knows nothing but the address: no library stores, no history
// state, nothing opened before — with the live library stream running, which
// routes/+layout.svelte starts for every signed-in library route.
function coldTabAt(pathname: string): void {
	routeParams.slug = pathname.slice('/playlist/'.length);
	history.replaceState(null, '', pathname);
	albumList.set([]);
	songList.set([]);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	resetCollectionForTests();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylists();
	resetResourceSyncForTests();
	startLibraryResourceSync();
}

beforeEach(() => {
	vi.stubGlobal('EventSource', FakeEventSource);
	api.fetchPlaylists.mockReset().mockResolvedValue([playlistItem()]);
	api.fetchPlaylist.mockReset().mockResolvedValue(playlistDetail());
	api.fetchAlbums.mockReset().mockResolvedValue(page([]));
	api.fetchSongs.mockReset().mockResolvedValue(page([]));
	api.fetchSong.mockReset();
	api.fetchVersions.mockReset().mockResolvedValue([]);
	api.fetchLastFailedGeneration.mockReset().mockResolvedValue({ job: null });
	api.fetchActiveModels.mockReset().mockResolvedValue([]);
	coldTabAt(`/playlist/${PLAYLIST_SLUG}`);
});

afterEach(() => {
	for (const app of mounted.splice(0)) void unmount(app);
	document.body.innerHTML = '';
	resetResourceSyncForTests();
	resetLibraryContextForTests();
	resetLibrarySearchForTests();
	resetPlaylists();
	resetCollectionForTests();
	vi.unstubAllGlobals();
});

describe('/playlist/<slug> opened cold', () => {
	it('shows the playlist named by the address', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain(PLAYLIST_TITLE));
		expect(target.textContent).toContain(ENTRY_SONG_TITLE);
		expect(workspaceWrapper(target).hasAttribute('inert')).toBe(false);
	});

	it('keeps the address it was opened with', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain(PLAYLIST_TITLE));
		expect(window.location.pathname).toBe(`/playlist/${PLAYLIST_SLUG}`);
	});

	it('opens the addressed playlist as the workspace collection', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain(PLAYLIST_TITLE));
		expect(get(openCollection)).toEqual({ kind: 'playlist', id: 'p1' });
	});
});

describe('/playlist/<slug> whose playlist cannot be reached', () => {
	beforeEach(() => {
		api.fetchPlaylists.mockRejectedValue(
			new ApiError(500, 'Playlist service is down', '/api/playlists')
		);
	});

	it('states the failure instead of claiming the playlist does not exist', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain('Playlist service is down'));
		expect(target.textContent).not.toContain('No such playlist');
	});

	it('shows the playlist after Try again once the failure is over', async () => {
		const target = openAddress();
		await vi.waitFor(() => expect(target.textContent).toContain('Playlist service is down'));
		api.fetchPlaylists.mockResolvedValue([playlistItem()]);

		requireElement(target, 'button.address-action').click();

		await vi.waitFor(() => expect(target.textContent).toContain(PLAYLIST_TITLE));
		expect(target.textContent).toContain(ENTRY_SONG_TITLE);
	});

	it('marks the workspace behind it inert, and lifts that once Try again succeeds', async () => {
		const target = openAddress();
		await vi.waitFor(() => expect(target.textContent).toContain('Playlist service is down'));
		expect(workspaceWrapper(target).hasAttribute('inert')).toBe(true);

		api.fetchPlaylists.mockResolvedValue([playlistItem()]);
		requireElement(target, 'button.address-action').click();

		await vi.waitFor(() => expect(target.textContent).toContain(PLAYLIST_TITLE));
		expect(workspaceWrapper(target).hasAttribute('inert')).toBe(false);
	});
});

describe('/playlist/<slug> naming no playlist', () => {
	beforeEach(() => {
		coldTabAt('/playlist/ghost');
		api.fetchPlaylists.mockResolvedValue([playlistItem()]);
	});

	it('says the address names no playlist instead of showing an empty page', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain('No such playlist'));
		expect(target.querySelector('[role="alert"]')).not.toBeNull();
	});

	it('stays on the address instead of redirecting to the library', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain('No such playlist'));
		expect(window.location.pathname).toBe('/playlist/ghost');
		expect(get(openCollection)).toBeNull();
	});
});
