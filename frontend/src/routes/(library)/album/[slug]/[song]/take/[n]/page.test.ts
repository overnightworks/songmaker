import {
	makeAlbum as album,
	makeGeneration as generation,
	makeSong as song
} from '$lib/test-utils/factories';
import { mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, GenerationItem, SongItem } from '$lib/api/types';
import { ApiError } from '$lib/api/fetch';
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

const routeParams = vi.hoisted(() => ({ slug: 'anfield', song: 'stadion-lauf-a', n: '1' }));
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
// player.ts's ensureGenerationsLoaded, which openTakeAddress uses to resolve
// a take number against the song's full generations, fetches through
// $lib/api/client rather than $lib/api/songs -- both need the same song back
// so a cold take address (nothing loaded yet) resolves either way.
vi.mock('$lib/api/client', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/client')>()),
	fetchSongs: api.fetchSongs,
	fetchSong: api.fetchSong,
	fetchVersions: api.fetchVersions,
	fetchLastFailedGeneration: api.fetchLastFailedGeneration,
	fetchActiveModels: api.fetchActiveModels
}));

import TakeAddressHarness from './harness.svelte';

const generationDefaults = {
	song_id: 'song-1',
	mp3_path: '/audio/g1.mp3',
	seed: 1
} satisfies Partial<GenerationItem>;

const songDefaults = {
	id: 'song-1',
	bpm: 120,
	audio_duration: 180,
	key_scale: 'Am',
	generation_params: null,
	best_scores: null,
	best_rating: null,
	generations: [generation(generationDefaults)],
	share_slug: null
} satisfies Partial<SongItem>;

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
	mounted.push(mount(TakeAddressHarness, { target }));
	return target;
}

// A tab that knows nothing but the address: no library stores, no history
// state, nothing opened before -- with the live library stream running, which
// routes/+layout.svelte starts for every signed-in library route.
function coldTabAt(pathname: string): void {
	const [, , albumSlug, songSlug, , takeNumber] = pathname.split('/');
	routeParams.slug = albumSlug;
	routeParams.song = songSlug ?? '';
	routeParams.n = takeNumber ?? '';
	routeSearch.forEach((_, key) => routeSearch.delete(key));
	history.replaceState(null, '', pathname);
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
	api.fetchAlbum
		.mockReset()
		.mockResolvedValue(
			album({ id: ALBUM_SLUG, title: ALBUM_TITLE, share_slug: null, cover: null })
		);
	api.fetchAlbums.mockReset().mockResolvedValue(page([]));
	api.fetchSongs.mockReset().mockResolvedValue(
		page([
			song({
				...structuredClone(songDefaults),
				slug: SONG_SLUG,
				title: TRACK_TITLE,
				album_id: ALBUM_SLUG,
				album_title: ALBUM_TITLE
			})
		])
	);
	api.fetchSong.mockReset().mockResolvedValue(
		song({
			...structuredClone(songDefaults),
			slug: SONG_SLUG,
			title: TRACK_TITLE,
			album_id: ALBUM_SLUG,
			album_title: ALBUM_TITLE
		})
	);
	api.fetchVersions.mockReset().mockResolvedValue([]);
	api.fetchLastFailedGeneration.mockReset().mockResolvedValue({ job: null });
	api.fetchActiveModels.mockReset().mockResolvedValue([]);
	coldTabAt(`/album/${ALBUM_SLUG}/${SONG_SLUG}/take/1`);
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

describe('/album/<slug>/<song-slug>/take/<n> opened cold', () => {
	it('shows the song with that take selected', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain(TRACK_TITLE));
		expect(get(selectedSongId)).toBe('song-1');
		expect(get(selectedGenerationId)).toBe('g1');
		expect(get(detailTab)).toBe('takes');
		expect(workspaceWrapper(target).hasAttribute('inert')).toBe(false);
	});

	it('keeps the address it was opened with', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain(TRACK_TITLE));
		expect(window.location.pathname).toBe(`/album/${ALBUM_SLUG}/${SONG_SLUG}/take/1`);
		expect(get(openCollection)).toEqual({ kind: 'album', id: ALBUM_SLUG });
	});

	it('loads the rest of the song generations to find a take the listing did not carry yet', async () => {
		api.fetchSongs.mockResolvedValue(
			page([
				song({
					...structuredClone(songDefaults),
					slug: SONG_SLUG,
					title: TRACK_TITLE,
					album_id: ALBUM_SLUG,
					album_title: ALBUM_TITLE,
					generation_count: 2,
					generations: [generation(generationDefaults)]
				})
			])
		);
		api.fetchSong.mockResolvedValue(
			song({
				...structuredClone(songDefaults),
				slug: SONG_SLUG,
				title: TRACK_TITLE,
				album_id: ALBUM_SLUG,
				album_title: ALBUM_TITLE,
				generation_count: 2,
				generations: [
					generation(generationDefaults),
					generation({ ...generationDefaults, id: 'g2', generation_number: 2 })
				]
			})
		);
		coldTabAt(`/album/${ALBUM_SLUG}/${SONG_SLUG}/take/2`);

		const target = openAddress();

		await vi.waitFor(() => expect(get(selectedGenerationId)).toBe('g2'));
		expect(target.textContent).toContain(TRACK_TITLE);
	});
});

describe('/album/<slug>/<song-slug>/take/<n> naming no take of a known song', () => {
	it('says the address names no take, with a way back to the song', async () => {
		coldTabAt(`/album/${ALBUM_SLUG}/${SONG_SLUG}/take/99`);

		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain('No such take'));
		const back = requireElement(target, 'a.address-action');
		expect(back.getAttribute('href')).toBe(`/album/${ALBUM_SLUG}/${SONG_SLUG}`);
		expect(get(openCollection)).toBeNull();
	});
});

describe('/album/<slug>/<song-slug>/take/<n> naming no song in a known album', () => {
	it('says the address names no song, with a way back to the album', async () => {
		coldTabAt(`/album/${ALBUM_SLUG}/ghost-song/take/1`);

		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain('No such song'));
		const back = requireElement(target, 'a.address-action');
		expect(back.getAttribute('href')).toBe(`/album/${ALBUM_SLUG}`);
	});
});

describe('/album/<slug>/<song-slug>/take/<n> naming no album', () => {
	beforeEach(() => {
		coldTabAt('/album/ghost/some-song/take/1');
		api.fetchAlbum.mockRejectedValue(new ApiError(404, 'Album not found', '/api/albums/ghost'));
	});

	it('says the address names no album instead of showing an empty page', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain('No such album'));
		expect(target.querySelector('[role="alert"]')).not.toBeNull();
	});
});

describe('/album/<slug>/<song-slug>/take/<n> whose song cannot be reached', () => {
	beforeEach(() => {
		api.fetchAlbum.mockRejectedValue(new ApiError(500, 'Album service is down', '/api/albums'));
	});

	it('states the failure instead of claiming the take does not exist', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain('Album service is down'));
		expect(target.textContent).not.toContain('No such');
	});

	it('marks the workspace behind it inert, and lifts that once Try again succeeds', async () => {
		const target = openAddress();
		await vi.waitFor(() => expect(target.textContent).toContain('Album service is down'));
		expect(workspaceWrapper(target).hasAttribute('inert')).toBe(true);

		api.fetchAlbum.mockResolvedValue(
			album({ id: ALBUM_SLUG, title: ALBUM_TITLE, share_slug: null, cover: null })
		);
		requireElement(target, 'button.address-action').click();

		await vi.waitFor(() => expect(target.textContent).toContain(TRACK_TITLE));
		expect(workspaceWrapper(target).hasAttribute('inert')).toBe(false);
	});
});
