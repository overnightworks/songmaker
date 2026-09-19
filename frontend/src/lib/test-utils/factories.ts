import type {
	SongItem,
	HealthResponse,
	GenerationItem,
	AlbumItem,
	PlaylistItem,
	PlaylistDetailItem,
	PlaylistEntryItem,
	SongSummaryResponse,
	VersionItem
} from '$lib/api/types';

export function makeSong(overrides: Partial<SongItem> = {}): SongItem {
	return {
		id: 's1',
		slug: 'local-only',
		title: 'Local Only',
		album_id: 'a1',
		album_title: 'Album',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: '',
		prompt: '',
		version_count: 1,
		generation_count: 1,
		is_shared: false,
		created_at: '2026-01-01T00:00:00+00:00',
		generations: [],
		bpm: 120,
		audio_duration: 180,
		key_scale: 'Am',
		generation_params: null,
		best_scores: null,
		best_rating: null,
		share_slug: null,
		...overrides
	};
}

export function makeGeneration(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
		mp3_path: 'g1.mp3',
		wav_path: null,
		seed: 7,
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
		share_slug: null,
		...overrides
	};
}

export function makeAlbum(overrides: Partial<AlbumItem> = {}): AlbumItem {
	return {
		id: 'a1',
		title: 'Nachtstrom',
		artist: 'Artist',
		subtitle: '',
		year: '',
		colors: {},
		song_count: 1,
		picked_count: 0,
		is_shared: false,
		created_at: '2026-01-01T00:00:00+00:00',
		is_archived: false,
		share_slug: null,
		cover: null,
		...overrides
	};
}

export function makePlaylist(overrides: Partial<PlaylistItem> = {}): PlaylistItem {
	return {
		id: 'p1',
		title: 'Night Drive',
		slug: 'night-drive',
		entry_count: 0,
		is_shared: false,
		album_covers: [],
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

export function makePlaylistDetail(
	overrides: Partial<PlaylistDetailItem> = {}
): PlaylistDetailItem {
	return {
		...makePlaylist(),
		entry_count: 1,
		entries: [],
		...overrides
	};
}

export function makePlaylistEntry(overrides: Partial<PlaylistEntryItem> = {}): PlaylistEntryItem {
	return {
		id: 'pe1',
		position: 0,
		generation_id: 'g1',
		song_id: 's1',
		song_title: 'Playlist Song',
		album_title: 'Anfield',
		artist: 'Artist',
		generation_number: 1,
		version_number: 1,
		is_picked: false,
		audio_duration: 180,
		mp3_path: 's1/g1.mp3',
		seed: 1,
		model_mode: 'sft',
		lyrics: null,
		...overrides
	};
}

export function makeSongSummary(overrides: Partial<SongSummaryResponse> = {}): SongSummaryResponse {
	return {
		id: 's1',
		slug: 'stadion',
		title: 'Stadion',
		album_id: 'a1',
		album_title: 'Anfield',
		artist: 'Artist',
		track_number: 1,
		vocal_language: 'en',
		lyrics: '',
		prompt: '',
		version_count: 1,
		generation_count: 1,
		is_shared: false,
		created_at: '2026-01-01T00:00:00+00:00',
		...overrides
	};
}

export function makeVersion(overrides: Partial<VersionItem> = {}): VersionItem {
	return {
		id: 'v1',
		version_number: 1,
		lyrics: 'verse one',
		prompt: 'rock style',
		bpm: 120,
		audio_duration: 180,
		key_scale: 'Am',
		generation_params: null,
		created_at: '',
		...overrides
	};
}

export function makeHealthResponse(overrides: Partial<HealthResponse> = {}): HealthResponse {
	return {
		status: 'ok',
		music_worker: 'running',
		scoring_worker: 'running',
		db: 'ok',
		redis: 'ok',
		redis_session_cache_failures: 0,
		acestep: 'healthy',
		uptime_seconds: 60,
		claude_cli_tool_surface: 'ok',
		codex_image_sandbox_runtime: 'ready',
		background_loops: {
			cover_runner: { state: 'ok', consecutive_failures: 0, last_error: null },
			session_sync: { state: 'ok', consecutive_failures: 0, last_error: null },
			resource_event_cleanup: { state: 'ok', consecutive_failures: 0, last_error: null },
			score_backfill: { state: 'ok', consecutive_failures: 0, last_error: null },
			stale_job_reaper: { state: 'ok', consecutive_failures: 0, last_error: null },
			provider_status_refresh: { state: 'ok', consecutive_failures: 0, last_error: null }
		},
		queue_depth_cap_reached: false,
		music_queue_depth: 0,
		scoring_queue_depth: 0,
		acestep_workers_online: 1,
		acestep_workers_total: 1,
		...overrides
	};
}
