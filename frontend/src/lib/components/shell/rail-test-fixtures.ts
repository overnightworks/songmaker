import { mount, tick, unmount, type Component } from 'svelte';
import { onTestFinished, vi } from 'vitest';

import type { LibraryListenItem, LibrarySearchHit } from '#lib/api/library.ts';
import type {
	AlbumItem,
	GenerationItem,
	PaginatedResponse,
	PlaylistDetailItem,
	PlaylistEntryItem,
	PlaylistItem,
	SongItem,
	SongSummaryResponse
} from '#lib/api/types.ts';
import { REDUCED_MOTION_MEDIA } from '#lib/constants.ts';
import { makeSongSummary } from '#lib/test-utils/factories.ts';

// Shared across every Rail*.test.ts in this directory. Vitest only hoists
// vi.mock from the test file, so each test still registers the modules; the
// factories live here and the tests load them with a dynamic import so a
// hoisted factory does not read this module in TDZ.

export function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
}

export async function openCollectionMenu(target: HTMLElement): Promise<HTMLElement> {
	requireElement<HTMLButtonElement>(target, '.collection-menu [aria-haspopup="dialog"]').click();
	await tick();
	return requireElement<HTMLElement>(document.body, '.menu-panel');
}

export function requireButtonContainingText(root: ParentNode, text: string): HTMLButtonElement {
	const button = Array.from(root.querySelectorAll('button')).find((candidate) =>
		candidate.textContent?.includes(text)
	);
	if (!button) throw new Error(`Expected a button containing ${text} to be rendered`);
	return button;
}

export function findElementByRoleAndName(
	root: ParentNode,
	role: string,
	name: string
): HTMLElement | null {
	return (
		Array.from(root.querySelectorAll<HTMLElement>(`[role="${role}"]`)).find(
			(element) => element.getAttribute('aria-label') === name
		) ?? null
	);
}

interface RailReveal {
	title: string | null | undefined;
	options: ScrollIntoViewOptions | undefined;
}

interface RailRevealSetting {
	reducedMotion?: boolean;
	animatingUntil?: Promise<void>;
}

// jsdom lays nothing out, so it has no scrollIntoView, getAnimations or
// matchMedia. For one test these stand-ins record each row the rail scrolls
// into view, by its title, with the given motion preference and every element
// animating until `animatingUntil` settles -- nothing animating without it.
export function recordRailReveals({
	reducedMotion = false,
	animatingUntil
}: RailRevealSetting = {}): RailReveal[] {
	const reveals: RailReveal[] = [];
	const standIns: Record<string, unknown> = {
		scrollIntoView(this: HTMLElement, options?: ScrollIntoViewOptions) {
			reveals.push({ title: this.querySelector('.row-title')?.textContent, options });
		},
		getAnimations: () => (animatingUntil === undefined ? [] : [{ finished: animatingUntil }])
	};
	for (const [name, value] of Object.entries(standIns)) {
		Object.defineProperty(HTMLElement.prototype, name, { configurable: true, value });
	}
	Object.defineProperty(window, 'matchMedia', {
		configurable: true,
		value: (query: string) => ({ matches: reducedMotion && query === REDUCED_MOTION_MEDIA })
	});
	onTestFinished(() => {
		for (const name of Object.keys(standIns)) Reflect.deleteProperty(HTMLElement.prototype, name);
		Reflect.deleteProperty(window, 'matchMedia');
	});
	return reveals;
}

export function revealedTitles(reveals: readonly RailReveal[]): RailReveal['title'][] {
	return reveals.map(({ title }) => title);
}

// The reveal waits for the DOM update and for running animations, both
// microtasks; one macrotask later every requested reveal has happened.
export function railRevealsSettled(): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve));
}

export function buildAlbum(overrides: Partial<AlbumItem> = {}): AlbumItem {
	return {
		id: 'a1',
		title: 'Nachtstrom',
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 2,
		picked_count: 0,
		has_playable_take: true,
		is_shared: false,
		share_slug: null,
		created_at: '2026-01-01T00:00:00+00:00',
		is_archived: false,
		...overrides
	};
}

export function buildSong(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		slug: 'tide',
		title: 'Tide',
		album_id: 'a1',
		album_title: 'Nachtstrom',
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
		generation_count: 1,
		best_scores: null,
		best_rating: null,
		generations: [],
		created_at: '2026-01-01T00:00:00+00:00',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

export function buildGeneration(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
		mp3_path: 'g1.mp3',
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
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

export function buildPlaylist(overrides: Partial<PlaylistItem> = {}): PlaylistItem {
	return {
		id: 'p1',
		title: 'Night Drive',
		slug: 'night-drive',
		entry_count: 2,
		is_shared: false,
		share_slug: null,
		album_covers: [],
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

export function buildAlbumSearchHit(overrides: Partial<AlbumItem> = {}): LibrarySearchHit {
	return { type: 'album', album: buildAlbum(overrides) };
}

export function buildSongSearchHit(
	overrides: Partial<SongSummaryResponse> = {},
	albumTitle = 'Nachtstrom'
): LibrarySearchHit {
	const song = makeSongSummary({ album_title: albumTitle, ...overrides });
	return { type: 'song', song, album_id: song.album_id, album_title: albumTitle };
}

export function buildPlaylistEntry(overrides: Partial<PlaylistEntryItem> = {}): PlaylistEntryItem {
	return {
		id: 'pe1',
		position: 0,
		generation_id: 'g1',
		song_id: 's1',
		song_title: 'Tide',
		album_title: 'Nachtstrom',
		artist: 'Artist',
		generation_number: 1,
		version_number: 1,
		is_picked: false,
		audio_duration: 180,
		mp3_path: 'tide.mp3',
		seed: 1,
		model_mode: 'sft',
		lyrics: null,
		...overrides
	};
}

export function buildPlaylistDetail(
	overrides: Partial<PlaylistDetailItem> = {}
): PlaylistDetailItem {
	return {
		id: 'p1',
		title: 'Night Drive',
		slug: 'night-drive',
		entry_count: 1,
		is_shared: false,
		share_slug: null,
		album_covers: [],
		created_at: '2026-01-01T00:00:00+00:00',
		entries: [buildPlaylistEntry()],
		...overrides
	};
}

export function albumsPage(
	overrides: Partial<PaginatedResponse<AlbumItem>> = {}
): PaginatedResponse<AlbumItem> {
	return { items: [], total: 0, offset: 0, limit: 50, has_more: false, ...overrides };
}

export function songsPage(
	overrides: Partial<PaginatedResponse<SongItem>> = {}
): PaginatedResponse<SongItem> {
	return { items: [], total: 0, offset: 0, limit: 200, has_more: false, ...overrides };
}

export function railPathsMock() {
	// Like the real `resolve`, a route ID loses its route groups: `/(library)?song=s1` is `/?song=s1`.
	return {
		resolve: vi.fn((routeId: string) =>
			routeId.replace(/\/\([^/)]+\)/g, '').replace(/^(?=\?)/, '/')
		)
	};
}

export function railLibraryApiMock() {
	return {
		searchLibrary: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false }),
		fetchLibraryListen: vi.fn().mockResolvedValue({ items: [] })
	};
}

export function lastPlayedPage(type: LibraryListenItem['type'], idsByLastPlayed: string[]) {
	return {
		items: idsByLastPlayed.map((id) => ({
			type,
			id,
			title: id,
			album_covers: [],
			played_at: '2026-09-27T03:47:00Z'
		}))
	};
}

export function railAlbumsApiMock() {
	return {
		fetchAlbum: vi.fn(),
		fetchAlbums: vi.fn().mockResolvedValue(albumsPage())
	};
}

export function railSongsApiMock() {
	return {
		fetchSong: vi.fn(),
		fetchSongs: vi.fn().mockResolvedValue(songsPage())
	};
}

export function railClientApiMock(overrides: Record<string, (...args: unknown[]) => unknown> = {}) {
	return {
		fetchAlbums: vi.fn().mockResolvedValue(albumsPage()),
		fetchAlbum: vi.fn(),
		fetchSong: vi.fn(),
		fetchSongs: vi.fn().mockResolvedValue(songsPage()),
		fetchPlaylists: vi.fn().mockResolvedValue([]),
		fetchPlaylist: vi.fn(),
		fetchLastFailedGeneration: vi.fn().mockResolvedValue({ job: null }),
		fetchVersions: vi.fn().mockResolvedValue([]),
		...overrides
	};
}

export function createComponentMount<Props extends Record<string, unknown>>(
	component: Component<Props>,
	props: Props
): { render: () => Promise<HTMLElement>; cleanup: () => Promise<void> };
export function createComponentMount(component: Component<Record<string, never>>): {
	render: () => Promise<HTMLElement>;
	cleanup: () => Promise<void>;
};
export function createComponentMount(component: Component, props?: Record<string, unknown>) {
	let mounted: ReturnType<typeof mount> | undefined;

	async function render(): Promise<HTMLElement> {
		const target = document.createElement('div');
		document.body.append(target);
		mounted = mount(component, props === undefined ? { target } : { target, props });
		await tick();
		return target;
	}

	async function cleanup(): Promise<void> {
		if (mounted) await unmount(mounted);
		mounted = undefined;
		document.body.replaceChildren();
	}

	return { render, cleanup };
}
