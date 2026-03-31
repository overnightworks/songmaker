/**
 * Auto-generated from api_models.py and scoring/models.py.
 * Do NOT edit manually — run: python scripts/generate_types.py
 *
 * Hierarchy: Song → Version (content) → Generation (MP3 output)
 */

export interface PaginatedResponse<T> {
	items: T[];
	total: number;
	offset: number;
	limit: number;
}

export interface GenerationParams {
	inference_steps?: number | null;
	guidance_scale?: number | null;
	shift?: number | null;
	think_mode?: string | null;
	lm_temperature?: number | null;
	lm_top_k?: number | null;
	lm_top_p?: number | null;
	lm_cfg_scale?: number | null;
	lm_negative_prompt?: string | null;
	infer_method?: string | null;
	batch_size?: number | null;
	seed?: number | null;
	acestep_model?: string | null;
	bpm?: number | null;
	duration?: number | null;
	key?: string | null;
}

export interface VersionGenerationParams {
	inference_steps?: number | null;
	guidance_scale?: number | null;
	shift?: number | null;
	think_mode?: string | null;
	lm_temperature?: number | null;
	lm_top_k?: number | null;
	lm_top_p?: number | null;
	lm_cfg_scale?: number | null;
	lm_negative_prompt?: string | null;
	infer_method?: string | null;
	batch_size?: number | null;
}

export interface TrackScores {
	lyrical_coherence?: number;
	lyrical_summary?: string;
	dynamics?: number;
	dynamics_pitch_cv?: number;
	dynamics_rms_contrast?: number;
	dynamics_onset_cv?: number;
	text_accuracy?: number;
	audiobox_enjoyment?: number;
	audiobox_understanding?: number;
	audiobox_complexity?: number;
	audiobox_quality?: number;
	bpm_detected?: number;
	bpm_deviation?: number;
	silence_gaps?: number;
	silence_longest?: number;
	spectral_artifacts?: number;
	user_rating?: number;
	user_notes?: string;
}

export interface GenerationItem {
	id: string;
	song_id: string;
	version_id: string | null;
	version_number: number | null;
	generation_number: number;
	mp3_path: string;
	wav_path: string | null;
	seed: number | null;
	status: string;
	is_archived: boolean;
	is_picked: boolean;
	is_kept: boolean;
	is_shared: boolean;
	share_slug?: string | null;
	whisper_text: string | null;
	scores: TrackScores | null;
	generation_params: GenerationParams | null;
	created_at: string | null;
}

export interface VersionItem {
	id: string;
	version_number: number;
	lyrics: string;
	prompt: string;
	bpm: number;
	duration: number;
	key: string;
	generation_params: VersionGenerationParams | null;
	created_at: string | null;
}

export interface SongItem {
	id: string;
	title: string;
	album_id: string;
	album_title: string;
	artist: string;
	track_number: number;
	language: string;
	lyrics: string;
	prompt: string;
	bpm?: number | null;
	duration?: number | null;
	key: string;
	generation_params?: VersionGenerationParams | null;
	version_count: number;
	generation_count: number;
	is_shared: boolean;
	share_slug?: string | null;
	best_scores?: TrackScores | null;
	best_rating?: number | null;
	created_at?: string | null;
	generations: GenerationItem[];
}

export interface AlbumItem {
	id: string;
	title: string;
	artist: string;
	subtitle: string;
	year: string;
	colors: Record<string, string>;
	song_count: number;
	is_shared: boolean;
	share_slug?: string | null;
}

export interface JobItem {
	id: string;
	type: string;
	status: string;
	progress: number;
	error?: string | null;
	error_type?: string | null;
	started_at?: string | null;
	completed_at?: string | null;
}

export interface Capabilities {
	claude_api: boolean;
	claude_cli: boolean;
	generation: boolean;
	scoring: boolean;
	chat_model: string;
	chat_system_prompt: string;
}

export interface AuthUser {
	id: string;
	username: string;
	role: 'admin' | 'user';
}

export interface SetupRequired {
	required: boolean;
}

export interface UserItem {
	id: string;
	username: string;
	role: string;
	is_active: boolean;
	created_at?: string | null;
}

export interface SessionItem {
	id: string;
	user_id: string;
	username: string;
	created_at?: string | null;
	expires_at?: string | null;
	ip_address: string;
	user_agent: string;
}

export interface PresetItem {
	id: string;
	name: string;
	model_mode: string;
	params: VersionGenerationParams;
	is_default: boolean;
	is_shared: boolean;
	created_at: string;
	updated_at: string;
}

export interface LoginAttemptItem {
	id: string;
	ip_address: string;
	username: string;
	success: boolean;
	attempted_at?: string | null;
}

export interface AuditLogItem {
	id: string;
	user_id: string | null;
	action: string;
	resource_type: string;
	resource_id: string;
	detail: string;
	created_at?: string | null;
}

export interface RateLimitItem {
	setting_key: string;
	value: number;
	is_override: boolean;
}

export interface RateLimitsResponse {
	settings: RateLimitItem[];
}

export interface UserRateLimitsResponse {
	user_id: string;
	overrides: RateLimitItem[];
	effective: RateLimitItem[];
}

export interface ChatResult {
	response: string;
}

export interface RateResult {
	status: string;
	generation_id?: string | null;
	generation?: string | null;
	rating: number;
}

export interface CleanupResult {
	status: string;
	deleted: number;
}

export interface ShareResult {
	status: string;
	share_url: string;
	share_slug: string;
}

export interface PlaylistItem {
	id: string;
	title: string;
	entry_count: number;
	is_shared: boolean;
	share_slug?: string | null;
	created_at?: string | null;
}

export interface PlaylistEntryItem {
	id: string;
	position: number;
	generation_id: string;
	song_title: string;
	album_title: string;
	artist: string;
	generation_number: number;
	mp3_path: string;
	seed: number | null;
}

export interface PlaylistDetailItem extends PlaylistItem {
	entries: PlaylistEntryItem[];
}
