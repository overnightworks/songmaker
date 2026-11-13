import { vi } from 'vitest';
import { makeAlbum } from '#lib/test-utils/factories.ts';

/** The API calls a song page test steers and reads; the mocked modules call through these. */
export const songDetailApi = {
	fetchAlbum: vi.fn(),
	uploadSongCover: vi.fn(),
	deleteSongCover: vi.fn(),
	deleteAlbumCover: vi.fn(),
	generateSong: vi.fn(),
	listLoras: vi.fn()
};

export function albumsApiMock() {
	return {
		fetchAlbum: (...args: unknown[]) => songDetailApi.fetchAlbum(...args),
		fetchAlbums: vi.fn()
	};
}

export function lorasApiMock(actual: typeof import('#lib/api/loras.ts')) {
	return { ...actual, listLoras: (...args: unknown[]) => songDetailApi.listLoras(...args) };
}

export function clientApiMock(actual: typeof import('#lib/api/client.ts')) {
	return {
		...actual,
		fetchVersions: vi.fn().mockResolvedValue([]),
		fetchSong: vi.fn((id: string) =>
			Promise.resolve({
				id,
				title: 'Local Only',
				album_id: 'a-local',
				album_title: 'Local Album',
				artist: 'Artist',
				track_number: 1,
				vocal_language: 'en',
				lyrics: 'verse',
				prompt: 'dark folk',
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
				share_slug: null
			})
		),
		fetchSongs: vi.fn().mockResolvedValue({
			items: [],
			total: 0,
			offset: 0,
			limit: 200,
			has_more: false
		}),
		fetchConversations: vi.fn().mockResolvedValue([]),
		fetchMemory: vi.fn().mockResolvedValue(null),
		fetchGenerationDefaults: vi.fn().mockResolvedValue({}),
		fetchActiveModels: vi.fn().mockResolvedValue([]),
		fetchPresets: vi.fn().mockResolvedValue([]),
		fetchBuiltinDefaults: vi.fn().mockResolvedValue({}),
		bulkDeleteGenerations: vi.fn().mockResolvedValue({ deleted: 1 }),
		uploadSongCover: (...args: unknown[]) => songDetailApi.uploadSongCover(...args),
		deleteSongCover: (...args: unknown[]) => songDetailApi.deleteSongCover(...args),
		deleteAlbumCover: (...args: unknown[]) => songDetailApi.deleteAlbumCover(...args),
		generateSong: (...args: unknown[]) => songDetailApi.generateSong(...args),
		updateSong: vi.fn(),
		renameSong: vi.fn(),
		deleteSong: vi.fn(),
		deleteVersion: vi.fn(),
		deleteGeneration: vi.fn().mockResolvedValue(undefined),
		addGenerationToPlaylist: vi.fn().mockResolvedValue(undefined),
		fetchPlaylists: vi.fn().mockResolvedValue([])
	};
}

export function resetSongDetailApi(): void {
	songDetailApi.fetchAlbum.mockReset();
	songDetailApi.fetchAlbum.mockResolvedValue(
		makeAlbum({ id: 'a-local', title: 'Local Album', song_count: 3 })
	);
	songDetailApi.uploadSongCover.mockReset();
	songDetailApi.deleteSongCover.mockReset();
	songDetailApi.deleteAlbumCover.mockReset();
	songDetailApi.generateSong.mockReset();
	songDetailApi.listLoras.mockReset();
	songDetailApi.listLoras.mockResolvedValue([]);
}
