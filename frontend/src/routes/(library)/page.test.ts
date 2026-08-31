import { mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import type { AlbumItem, SongItem } from '$lib/api/types';
import { ApiError } from '$lib/api/fetch';
import { LEGACY_TAKE_LINK_NOT_FOUND_TOAST } from '$lib/constants';
import { resetCollectionForTests } from '$lib/stores/collection';
import { albumList, songList } from '$lib/stores/libraryData';
import { libraryRootState, resetLibraryContextForTests } from '$lib/stores/libraryContext';
import { resetLibrarySearchForTests } from '$lib/stores/librarySearch';
import { resetResourceSyncForTests, startLibraryResourceSync } from '$lib/stores/resourceSync';
import { selectedGenerationId, selectedSongId } from '$lib/stores/player';
import { toasts } from '$lib/stores/toast';

const SONG_ID = 'song-uuid-1';
const GENERATION_ID = 'gen-uuid-1';
const ALBUM_SLUG = 'anfield';
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

const routeSearch = vi.hoisted(() => new URLSearchParams());

vi.mock('$app/state', () => ({
	page: {
		params: {},
		get url() {
			return { searchParams: routeSearch };
		}
	}
}));
// Stands in for the router the way the real one behaves for a same-shape
// write: it moves the history entry, but nothing here re-resolves the
// mounted route -- a route-crossing `goto` from this page therefore never
// actually swaps in the destination `+page.svelte` the way a real browser
// would (that hop is the sibling suites' own job, plus
// e2e/album-address.spec.ts for the real router). What this file can and
// does pin is that `goto` is called with the right path and options, and
// what the page renders while it waits or fails.
vi.mock('$app/navigation', () => ({
	goto: vi.fn((url: string, options?: { replaceState?: boolean }) => {
		if (options?.replaceState) history.replaceState(null, '', url);
		else history.pushState(null, '', url);
		return Promise.resolve();
	}),
	afterNavigate: vi.fn()
}));
vi.mock('$app/paths', () => ({ resolve: vi.fn((path: string) => path) }));
vi.mock('$lib/api/songs', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/songs')>()),
	fetchSong: api.fetchSong,
	fetchSongs: api.fetchSongs
}));
vi.mock('$lib/api/albums', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/api/albums')>()),
	fetchAlbum: api.fetchAlbum,
	fetchAlbums: api.fetchAlbums
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

import { goto } from '$app/navigation';
import LegacySongQueryHarness from './harness.svelte';

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

function album(overrides: Partial<AlbumItem> = {}): AlbumItem {
	return {
		id: ALBUM_SLUG,
		title: 'Anfield',
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
		id: SONG_ID,
		slug: SONG_SLUG,
		title: TRACK_TITLE,
		album_id: ALBUM_SLUG,
		album_title: 'Anfield',
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
	mounted.push(mount(LegacySongQueryHarness, { target }));
	return target;
}

// A tab that knows nothing but a legacy `?song=` (and maybe `&gen=`) address:
// no library stores, no history state, nothing opened before -- with the
// live library stream running, which routes/+layout.svelte starts for every
// signed-in library route.
function coldTabAt(search: string): void {
	routeSearch.forEach((_, key) => routeSearch.delete(key));
	new URLSearchParams(search).forEach((value, key) => routeSearch.set(key, value));
	history.replaceState(null, '', '/' + search);
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
	vi.mocked(goto).mockClear();
	api.fetchAlbum.mockReset().mockResolvedValue(album());
	api.fetchAlbums.mockReset().mockResolvedValue(page([]));
	api.fetchSongs.mockReset().mockResolvedValue(page([]));
	api.fetchSong.mockReset().mockResolvedValue(song());
	api.fetchVersions.mockReset().mockResolvedValue([]);
	api.fetchLastFailedGeneration.mockReset().mockResolvedValue({ job: null });
	api.fetchActiveModels.mockReset().mockResolvedValue([]);
	coldTabAt(`?song=${SONG_ID}`);
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

describe('/ with no ?song= query', () => {
	it('renders nothing and leaves the workspace reachable', async () => {
		coldTabAt('');

		const target = openAddress();

		await Promise.resolve();
		expect(target.querySelector('.address-overlay')).toBeNull();
		expect(workspaceWrapper(target).hasAttribute('inert')).toBe(false);
	});
});

describe('a legacy /?song= address redirects', () => {
	it('resolves the id and replaces the address with the canonical song address', async () => {
		api.fetchSong.mockResolvedValue(song());

		openAddress();

		await vi.waitFor(() =>
			expect(goto).toHaveBeenCalledWith(`/album/${ALBUM_SLUG}/${SONG_SLUG}`, {
				replaceState: true,
				noScroll: true,
				keepFocus: true
			})
		);
		expect(window.location.pathname).toBe(`/album/${ALBUM_SLUG}/${SONG_SLUG}`);
	});

	it('resolves a song+gen pair onto the canonical take address', async () => {
		coldTabAt(`?song=${SONG_ID}&gen=${GENERATION_ID}`);
		api.fetchSong.mockResolvedValue(
			song({
				generation_count: 1,
				generations: [
					{
						id: GENERATION_ID,
						song_id: SONG_ID,
						version_id: 'v1',
						version_number: 1,
						generation_number: 3,
						mp3_path: '/audio/g.mp3',
						wav_path: null,
						seed: 1,
						status: 'completed',
						is_archived: false,
						is_picked: false,
						is_kept: false,
						is_shared: false,
						model_mode: 'turbo',
						whisper_text: null,
						whisper_cues: null,
						version_lyrics: null,
						scores: null,
						generation_params: null,
						audio_duration_sec: null,
						created_at: '2026-01-01T00:00:00+00:00'
					}
				]
			})
		);

		openAddress();

		await vi.waitFor(() =>
			expect(goto).toHaveBeenCalledWith(
				`/album/${ALBUM_SLUG}/${SONG_SLUG}/take/3`,
				expect.objectContaining({ replaceState: true })
			)
		);
	});

	it('shows the resolving overlay, inert over the workspace, while the fetch is in flight', async () => {
		let resolveFetch: ((value: SongItem) => void) | undefined;
		api.fetchSong.mockReturnValue(
			new Promise((res) => {
				resolveFetch = res;
			})
		);

		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain('Loading song'));
		expect(workspaceWrapper(target).hasAttribute('inert')).toBe(true);

		resolveFetch?.(song());
		await vi.waitFor(() => expect(goto).toHaveBeenCalled());
	});
});

// Issue #265's S7: a song not yet in songList when its address was first
// written keeps the legacy query form as writeLibraryHistory's own
// same-shape fallback (libraryHistoryUrl's comment on the songId branch), so
// a later Back/Forward can land back on it. onPopstate (navigation.ts)
// applies that restore state instantly from history.state -- this page used
// to re-resolve the same address over the network in parallel every time,
// a redundant round trip and a brief overlay flash this check now skips.
describe('a legacy /?song= address whose history.state already carries the answer', () => {
	it('skips the network resolution once a matching restore state is already applied', async () => {
		history.replaceState(
			{
				...libraryRootState(),
				surface: 'detail',
				collection: { kind: 'album', id: ALBUM_SLUG },
				songId: SONG_ID,
				generationId: null
			},
			'',
			`/?song=${SONG_ID}`
		);

		const target = openAddress();
		await Promise.resolve();
		await Promise.resolve();

		expect(api.fetchSong).not.toHaveBeenCalled();
		expect(goto).not.toHaveBeenCalled();
		expect(target.querySelector('.address-overlay')).toBeNull();
	});

	it('still resolves over the network when the restore state names a different song', async () => {
		history.replaceState(
			{
				...libraryRootState(),
				surface: 'detail',
				collection: { kind: 'album', id: ALBUM_SLUG },
				songId: 'some-other-song',
				generationId: null
			},
			'',
			`/?song=${SONG_ID}`
		);
		api.fetchSong.mockResolvedValue(song());

		openAddress();

		await vi.waitFor(() =>
			expect(goto).toHaveBeenCalledWith(`/album/${ALBUM_SLUG}/${SONG_SLUG}`, {
				replaceState: true,
				noScroll: true,
				keepFocus: true
			})
		);
	});
});

describe('a legacy /?song= address naming no song', () => {
	beforeEach(() => {
		api.fetchSong.mockRejectedValue(new ApiError(404, 'Song not found', `/api/songs/${SONG_ID}`));
	});

	it('states the address names no song, with a way back to the library', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain('No such song'));
		expect(target.querySelector('[role="alert"]')).not.toBeNull();
		const back = requireElement(target, 'a.address-action');
		expect(back.getAttribute('href')).toBe('/');
	});

	it('never navigates away -- the query address stays, honestly 404ing in place', async () => {
		openAddress();

		await vi.waitFor(() => expect(vi.mocked(goto)).not.toHaveBeenCalled());
		expect(window.location.pathname + window.location.search).toBe(`/?song=${SONG_ID}`);
	});

	it('marks the workspace inert while the 404 overlay is up', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain('No such song'));
		expect(workspaceWrapper(target).hasAttribute('inert')).toBe(true);
	});
});

describe('a legacy /?song= address whose song cannot be reached', () => {
	beforeEach(() => {
		api.fetchSong.mockRejectedValue(new ApiError(500, 'Song service is down', '/api/songs'));
	});

	it('states the failure instead of claiming the song does not exist', async () => {
		const target = openAddress();

		await vi.waitFor(() => expect(target.textContent).toContain('Song service is down'));
		expect(target.textContent).not.toContain('No such');
	});

	it('redirects after Try again once the failure is over', async () => {
		const target = openAddress();
		await vi.waitFor(() => expect(target.textContent).toContain('Song service is down'));
		api.fetchSong.mockResolvedValue(song());

		requireElement(target, 'button.address-action').click();

		await vi.waitFor(() =>
			expect(goto).toHaveBeenCalledWith(`/album/${ALBUM_SLUG}/${SONG_SLUG}`, {
				replaceState: true,
				noScroll: true,
				keepFocus: true
			})
		);
	});

	it('marks the workspace inert, and lifts that once Try again succeeds', async () => {
		const target = openAddress();
		await vi.waitFor(() => expect(target.textContent).toContain('Song service is down'));
		expect(workspaceWrapper(target).hasAttribute('inert')).toBe(true);

		api.fetchSong.mockResolvedValue(song());
		requireElement(target, 'button.address-action').click();

		await vi.waitFor(() => expect(goto).toHaveBeenCalled());
	});
});

describe('a legacy /?song=&gen= address whose take is gone', () => {
	it('drops the take, lands on the song address, and toasts the loss only after the redirect lands', async () => {
		coldTabAt(`?song=${SONG_ID}&gen=${GENERATION_ID}`);
		api.fetchSong.mockResolvedValue(song());
		let releaseGoto: (() => void) | undefined;
		vi.mocked(goto).mockImplementationOnce((url, options) => {
			if ((options as { replaceState?: boolean } | undefined)?.replaceState) {
				history.replaceState(null, '', url as string);
			}
			return new Promise<void>((res) => {
				releaseGoto = () => res(undefined);
			});
		});

		openAddress();

		await vi.waitFor(() =>
			expect(goto).toHaveBeenCalledWith(`/album/${ALBUM_SLUG}/${SONG_SLUG}`, {
				replaceState: true,
				noScroll: true,
				keepFocus: true
			})
		);
		// The redirect has landed (goto was called and the address already
		// changed) but its own promise is still pending -- the toast must not
		// have fired yet, or a person would read it while the bar still shows
		// the address they are leaving.
		expect(get(toasts)).toHaveLength(0);

		releaseGoto?.();

		await vi.waitFor(() => expect(get(toasts)).toHaveLength(1));
		expect(get(toasts)[0]).toMatchObject({
			type: 'error',
			message: LEGACY_TAKE_LINK_NOT_FOUND_TOAST
		});
	});

	it('does not toast when the requested take still exists', async () => {
		coldTabAt(`?song=${SONG_ID}&gen=${GENERATION_ID}`);
		api.fetchSong.mockResolvedValue(
			song({
				generation_count: 1,
				generations: [
					{
						id: GENERATION_ID,
						song_id: SONG_ID,
						version_id: 'v1',
						version_number: 1,
						generation_number: 1,
						mp3_path: '/audio/g.mp3',
						wav_path: null,
						seed: 1,
						status: 'completed',
						is_archived: false,
						is_picked: false,
						is_kept: false,
						is_shared: false,
						model_mode: 'turbo',
						whisper_text: null,
						whisper_cues: null,
						version_lyrics: null,
						scores: null,
						generation_params: null,
						audio_duration_sec: null,
						created_at: '2026-01-01T00:00:00+00:00'
					}
				]
			})
		);

		openAddress();

		await vi.waitFor(() => expect(goto).toHaveBeenCalled());
		expect(get(toasts)).toHaveLength(0);
	});
});
