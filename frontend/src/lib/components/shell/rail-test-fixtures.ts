import type {
	AlbumItem,
	GenerationItem,
	PaginatedResponse,
	PlaylistDetailItem,
	PlaylistEntryItem,
	PlaylistItem,
	SongItem
} from '$lib/api/types';

// Shared across every Rail*.test.ts in this directory (Rail, RailLibraryGroup,
// RailPlaylistsGroup, RailSettings, RailGroup) so a shell test does not carry
// its own copy of the same lookup helper, domain builders, and page shapes.
//
// vi.mock(...) factories are hoisted above this file's own imports, so a
// factory that reads a plain re-exported binding by value can hit a TDZ;
// each *.test.ts's own vi.mock(...) bodies stay inline for that reason
// (see https://vitest.dev/api/vi.html#vi-mock).

export function requireElement<T extends Element>(root: ParentNode, selector: string): T {
	const element = root.querySelector<T>(selector);
	if (!element) throw new Error(`Expected ${selector} to be rendered`);
	return element;
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
