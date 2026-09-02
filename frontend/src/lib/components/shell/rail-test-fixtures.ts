import { mount, tick, unmount, type Component } from 'svelte';
import { vi } from 'vitest';

import type {
	AlbumItem,
	GenerationItem,
	PaginatedResponse,
	PlaylistDetailItem,
	PlaylistEntryItem,
	PlaylistItem,
	SongItem
} from '$lib/api/types';

// Shared across every Rail*.test.ts in this directory. Vitest only hoists
// vi.mock from the test file, so each test still registers the modules; the
// factories live here and the tests load them with a dynamic import so a
// hoisted factory does not read this module in TDZ.

export function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
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
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
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

export function railNavigationMock() {
	return {
		goto: vi.fn().mockResolvedValue(undefined),
		afterNavigate: vi.fn()
	};
}

export function railPathsMock() {
	return { resolve: vi.fn((path: string) => path) };
}

export function railLibraryApiMock() {
	return {
		searchLibrary: vi.fn().mockResolvedValue({ items: [], next_cursor: null, has_more: false })
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
