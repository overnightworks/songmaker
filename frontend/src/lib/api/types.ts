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
	thinking?: boolean | null;
	lm_temperature?: number | null;
	lm_top_k?: number | null;
	lm_top_p?: number | null;
	lm_cfg_scale?: number | null;
	lm_negative_prompt?: string | null;
	infer_method?: string | null;
	batch_size?: number | null;
	reference_audio_path?: string | null;
	repaint_mode?: string | null;
	repaint_strength?: number | null;
	lm_repetition_penalty?: number | null;
	use_cot_caption?: boolean | null;
	use_cot_language?: boolean | null;
	use_adg?: boolean | null;
	cfg_interval_start?: number | null;
	cfg_interval_end?: number | null;
	seed?: number | null;
	acestep_model?: string | null;
	bpm?: number | null;
	audio_duration?: number | null;
	key_scale?: string | null;
	task_type?: string | null;
	repainting_start?: number | null;
	repainting_end?: number | null;
	audio_cover_strength?: number | null;
	repaint_latent_crossfade_frames?: number | null;
	repaint_wav_crossfade_sec?: number | null;
	cover_noise_strength?: number | null;
	timesteps?: string | null;
	constrained_decoding?: boolean | null;
	cot_caption?: string | null;
	cot_lyrics?: string | null;
}

export interface VersionGenerationParams {
	inference_steps?: number | null;
	guidance_scale?: number | null;
	shift?: number | null;
	thinking?: boolean | null;
	lm_temperature?: number | null;
	lm_top_k?: number | null;
	lm_top_p?: number | null;
	lm_cfg_scale?: number | null;
	lm_negative_prompt?: string | null;
	infer_method?: string | null;
	batch_size?: number | null;
	reference_audio_path?: string | null;
	repaint_mode?: string | null;
	repaint_strength?: number | null;
	lm_repetition_penalty?: number | null;
	use_cot_caption?: boolean | null;
	use_cot_language?: boolean | null;
	use_adg?: boolean | null;
	cfg_interval_start?: number | null;
	cfg_interval_end?: number | null;
}

export interface TrackScores {
	text_accuracy?: number;
	detected_language?: string;
	lyrical_coherence?: number;
	lyrical_summary?: string;
	dynamics?: number;
	dynamics_pitch_cv?: number;
	dynamics_rms_contrast?: number;
	dynamics_onset_cv?: number;
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
	model_mode?: string | null;
	src_generation_id?: string | null;
	src_generation_number?: number | null;
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
	audio_duration: number;
	key_scale: string;
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
	vocal_language: string;
	lyrics: string;
	prompt: string;
	bpm?: number | null;
	audio_duration?: number | null;
	key_scale: string;
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
	queue_position?: number | null;
	started_at?: string | null;
	completed_at?: string | null;
}

export interface Capabilities {
	claude_api: boolean;
	claude_cli: boolean;
	generation: boolean;
	scoring: boolean;
	chat_model: string;
	scoring_model: string;
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

export interface ChatMessageItem {
	id: string;
	role: string;
	content: string;
	created_at: string;
}

export interface ChatTurnResult {
	user_message: ChatMessageItem;
	assistant_message: ChatMessageItem;
}

export interface ChatHistoryResult {
	messages: ChatMessageItem[];
}

export interface RecentChatItem {
	song_id: string;
	title: string;
	message_count: number;
	last_message_at: string | null;
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

export interface PlaylistItem {
	id: string;
	title: string;
	entry_count: number;
	is_shared: boolean;
	share_slug?: string | null;
	created_at?: string | null;
}

export interface PlaylistDetailItem {
	id: string;
	title: string;
	entry_count: number;
	is_shared: boolean;
	share_slug?: string | null;
	created_at?: string | null;
	entries: PlaylistEntryItem[];
}

export interface WorkerIdentityItem {
	id: string;
	host: string;
	port: number;
	gpu_id: number | null;
	vram_total_gb: number | null;
	registered_at: string;
	last_register_at: string;
}

export interface LoadedModelDetailItem {
	mode: string;
	size_gb: number;
}

export interface WorkerEphemeralStateItem {
	loaded: LoadedModelDetailItem[];
	target_loading?: string | null;
	loading_started_at?: string | null;
	queue_depth: number;
	vram_used_gb?: number | null;
	vram_total_gb?: number | null;
	available_modes: string[];
	pinned: string[];
	last_heartbeat_at?: string | null;
}

export interface WorkerInfoItem {
	identity: WorkerIdentityItem;
	state: WorkerEphemeralStateItem | null;
	status: 'online' | 'loading' | 'offline';
}

export interface WorkerPoolResponse {
	workers: WorkerInfoItem[];
}

export interface RegistryModelItem {
	mode: string;
	downloaded: boolean;
	loaded_on: string[];
	loading_on: string[];
}

export interface RegistryResponse {
	models: RegistryModelItem[];
}
