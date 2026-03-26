/**
 * Auto-generated from api_models.py and scoring/models.py.
 * Do NOT edit manually — run: python scripts/generate_types.py
 *
 * Hierarchy: Song → Version (content) → Generation (MP3 output)
 */

export interface GenerationParams {
	seed?: number | null;
	acestep_model?: string | null;
	bpm?: number | null;
	duration?: number | null;
	key?: string | null;
	guidance_scale?: number | null;
	inference_steps?: number | null;
	shift?: number | null;
	think_mode?: string | null;
	lm_temperature?: number | null;
	infer_method?: string | null;
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
	seed: number | null;
	status: string;
	is_archived: boolean;
	is_picked: boolean;
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
	bpm: number;
	duration: number;
	key: string;
	generation_params?: VersionGenerationParams | null;
	version_count: number;
	generation_count: number;
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
