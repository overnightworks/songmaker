/**
 * Auto-generated from the FastAPI API contract.
 * Do NOT edit manually — run: python scripts/generate_types.py
 *
 * Hierarchy: Song → Version (content) → Generation (MP3 output)
 */

export interface PaginatedResponse<T> {
	items: T[];
	total: number;
	offset: number;
	limit: number;
	has_more: boolean;
}

export type RepaintMode = 'conservative' | 'balanced' | 'aggressive';

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

export interface AddAlbumToPlaylistRequest {
	album_id: string;
}

export interface AddAlbumToPlaylistResult {
	added_count: number;
	skipped: PlaylistAlbumSkipItem[];
}

export interface AddGenerationToPlaylistRequest {
	generation_id: string;
}

export interface AddSongToPlaylistRequest {
	song_id: string;
}

export interface AdminUserLoraItem {
	id: string;
	name: string;
	owner_username: string;
	status: string;
}

export interface AlbumCoverUrls {
	card: string;
	detail: string;
}

export interface AlbumCreateRequest {
	title: string;
	artist: string;
}

export interface AlbumItem {
	id: string;
	title: string;
	artist: string;
	subtitle: string;
	year: string;
	colors: Record<string, string>;
	song_count: number;
	picked_count: number;
	has_playable_take: boolean;
	is_shared: boolean;
	share_slug?: string | null;
	cover?: AlbumCoverUrls | null;
	created_at: string;
	is_archived: boolean;
	archived_at?: string | null;
}

export interface AlbumUpdateRequest {
	title?: string | null;
	subtitle?: string | null;
	year?: number | null;
}

export interface AssistantTextEvent {
	type: 'assistant_text';
	text: string;
}

export interface AuthUser {
	id: string;
	username: string;
	role: 'admin' | 'user';
	account_console_url?: string | null;
}

export interface AvailableModel {
	id: string;
	is_active: boolean;
	capabilities?: ModelCapabilities | null;
}

export interface BackgroundLoopResponse {
	state: 'ok' | 'failing' | 'dead';
	consecutive_failures: number;
	last_error: string | null;
}

export interface BulkDeleteRequest {
	generation_ids: string[];
}

export interface BulkDeleteResponse {
	deleted: number;
}

export interface Capabilities {
	claude_api: boolean;
	claude_cli: boolean;
	generation: boolean;
	scoring: boolean;
	chat_model: string;
	scoring_model: string;
}

export interface ChatMessageItem {
	id: string;
	role: string;
	content: string;
	created_at: string;
}

export interface ChatTurnFailureFrame {
	type: 'error';
	status: number;
	message: string;
}

export interface ChatTurnFinalFrame {
	type: 'final';
	conversation_id: string;
	user_message: ChatMessageItem;
	assistant_message: ChatMessageItem;
}

export interface ChatTurnProblemFrame {
	type: 'error';
	status: number;
	problem: 'unavailable' | 'busy' | 'not_enabled' | 'sign_in_again';
	retry_after_seconds?: number | null;
}

export interface ChatTurnV2Request {
	message: string;
	current_song_id?: string | null;
	mentioned_song_ids: string[];
	mentioned_version_ids: string[];
	mentioned_album_id?: string | null;
	current_generation_id?: string | null;
}

export interface CleanupResult {
	status: string;
	deleted: number;
}

export interface ConversationItem {
	id: string;
	title: string | null;
	created_at: string;
	updated_at: string;
	archived_at: string | null;
	message_count: number;
	last_message_at: string | null;
}

export interface ConversationListResponse {
	conversations: ConversationItem[];
}

export interface ConversationMessagesResponse {
	conversation_id: string;
	title: string | null;
	archived_at: string | null;
	messages: ChatMessageItem[];
	turn_running: boolean;
}

export interface CoverRequest {
	src_generation_id: string;
	audio_cover_strength: number;
	cover_noise_strength?: number | null;
	lyrics?: string | null;
	prompt?: string | null;
	version_id?: string | null;
	count: number;
	model: string;
	seed?: number | null;
}

export interface CoverSettingsRequest {
	provider: string;
	route: string;
	model: string;
}

export interface CoverSettingsResponse {
	provider: string;
	route: 'cli' | 'api';
	model: string;
}

export interface CoverSuggestionResponse {
	id: string;
	url: string;
}

export interface CoverSuggestionSelectionRequest {
	suggestion_id: string;
}

export interface CoverSuggestionsResponse {
	job?: JobItem | null;
	suggestions: CoverSuggestionResponse[];
	used_today: number;
	daily_limit: number;
}

export interface CoverTaskParams {
	src_wav_path: string;
	src_generation_id: string;
	audio_cover_strength: number;
	lyrics: string;
	prompt: string;
	cover_noise_strength?: number | null;
}

export interface CowriterSettings {
	tail_token_budget: number;
	model: string;
}

export interface CowriterSettingsRequest {
	tail_token_budget: number;
}

export interface DefaultConfigRequest {
	config?: string | null;
}

export interface DefaultConfigResponse {
	config?: string | null;
}

export interface EvictModelOnWorkerRequest {
	mode: string;
}

export interface GenerateRequest {
	count: number;
	model: string;
	version_id?: string | null;
	seed?: number | null;
}

export interface GenerationCreatedResourceEvent {
	kind: 'generation.created';
	sequence: string;
	resource_type: 'song';
	resource_id: string;
	generation_id: string;
	created_at: string;
}

export interface GenerationDefaultsRequest {
	root: Record<string, VersionGenerationParams>;
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
	archived_at?: string | null;
	expires_at?: string | null;
	is_picked: boolean;
	is_kept: boolean;
	is_shared: boolean;
	share_slug?: string | null;
	model_mode: string;
	src_generation_id?: string | null;
	src_generation_number?: number | null;
	src_generation_version_number?: number | null;
	whisper_text: string | null;
	whisper_cues: WhisperCue[] | null;
	version_lyrics: string | null;
	scores: TrackScores | null;
	generation_params: GenerationParams | null;
	audio_duration_sec: number | null;
	created_at: string;
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
	infer_method?: 'ode' | 'sde' | null;
	batch_size?: number | null;
	reference_audio_path?: string | null;
	repaint_mode?: RepaintMode | null;
	repaint_strength?: number | null;
	lm_repetition_penalty?: number | null;
	use_cot_caption?: boolean | null;
	use_cot_language?: boolean | null;
	use_adg?: boolean | null;
	cfg_interval_start?: number | null;
	cfg_interval_end?: number | null;
	sampler_mode?: 'euler' | 'heun' | null;
	velocity_norm_threshold?: number | null;
	velocity_ema_factor?: number | null;
	latent_shift?: number | null;
	latent_rescale?: number | null;
	audio_cover_strength?: number | null;
	user_lora_id?: string | null;
	seed?: number | null;
	acestep_model?: string | null;
	bpm?: number | null;
	audio_duration?: number | null;
	key_scale?: string | null;
	task_type?: 'text2music' | 'repaint' | 'cover' | null;
	repainting_start?: number | null;
	repainting_end?: number | null;
	repaint_latent_crossfade_frames?: number | null;
	repaint_wav_crossfade_sec?: number | null;
	cover_noise_strength?: number | null;
	timesteps?: string | null;
	constrained_decoding?: boolean | null;
	cot_caption?: string | null;
	cot_lyrics?: string | null;
	delivered_batch_size?: number | null;
}

export interface GenerationRetentionReport {
	archived_ids: string[];
	deleted_ids: string[];
	archived_count: number;
	deleted_count: number;
	retention_days: number;
	hard_delete_days: number;
	scheduled_hour_utc: number;
	dry_run: boolean;
}

export interface GenerationUnavailableResponse {
	detail: string;
	error_type: string;
	job_id: string;
}

export interface HealthResponse {
	status: 'ok' | 'degraded';
	music_worker: 'running' | 'stopped';
	scoring_worker: 'running' | 'stopped';
	music_queue_depth: number;
	scoring_queue_depth: number;
	db: 'ok' | 'error';
	redis: 'ok' | 'error';
	acestep: 'healthy' | 'unknown' | 'unhealthy';
	acestep_workers_total: number;
	acestep_workers_online: number;
	queue_depth_cap_reached: boolean;
	uptime_seconds: number;
	claude_cli_tool_surface: 'ok' | 'drift' | 'unverified';
	codex_image_sandbox_runtime: 'ready' | 'not_set_up' | 'unverified';
	background_loops: Record<'cover_runner' | 'session_cleanup' | 'resource_event_cleanup' | 'score_backfill' | 'stale_job_reaper' | 'provider_status_refresh', BackgroundLoopResponse>;
}

export interface JobItem {
	id: string;
	type: string;
	status: string;
	progress: number;
	phase?: 'loading_model' | 'writing' | 'rendering' | 'saving_take' | null;
	take_index?: number | null;
	take_count?: number | null;
	current_epoch?: number | null;
	train_epochs?: number | null;
	remaining_time_estimate?: number | 'calculating' | null;
	error?: string | null;
	error_type?: string | null;
	queue_reason?: string | null;
	queue_position?: number | null;
	started_at?: string | null;
	completed_at?: string | null;
}

export interface JudgeSettings {
	provider: string;
	route: 'cli' | 'api';
	provider_routes_status: Record<string, Record<'cli' | 'api', ProviderRouteStatusResponse>>;
	model: string;
	allowed_providers: string[];
	allowed_models: string[];
	models_by_provider: Record<string, string[]>;
	models_errors: Record<string, string>;
	probed_at: Record<string, string | null>;
}

export interface JudgeSettingsRequest {
	provider: string;
	route?: 'cli' | 'api' | null;
	model: string;
}

export interface LastFailedGenerationResult {
	job?: JobItem | null;
}

export interface LibraryAlbumHit {
	type: 'album';
	album: AlbumItem;
}

export interface LibraryListenItem {
	type: 'album' | 'playlist';
	id: string;
	title: string;
	cover?: AlbumCoverUrls | null;
	album_covers: AlbumCoverUrls[];
	song_id?: string | null;
	song_title?: string | null;
	song_number?: number | null;
	entry_id?: string | null;
	played_at: string;
}

export interface LibraryListenResponse {
	items: LibraryListenItem[];
}

export interface LibraryPoolQueue {
	pool: 'mix' | 'picks' | 'keeps' | 'all';
	takes: LibraryPoolTakeItem[];
	skipped: QueueStreamSkipItem[];
	skipped_complete: boolean;
}

export interface LibraryPoolTakeItem {
	generation_id: string;
	song_id: string;
	song_title: string;
	artist: string;
	album_title: string;
	lyrics: string | null;
	generation_number: number;
	mp3_path: string;
	seed: number | null;
	model_mode: string;
	is_picked: boolean;
	is_kept: boolean;
}

export interface LibrarySearchResponse {
	items: (LibraryAlbumHit | LibrarySongHit)[];
	next_cursor: string | null;
	has_more: boolean;
}

export interface LibrarySongHit {
	type: 'song';
	song: SongSummaryResponse;
	album_id: string;
	album_title: string;
}

export interface LibraryWriteItem {
	song_id: string;
	song_title: string;
	album_id: string;
	album_title: string;
	cover?: AlbumCoverUrls | null;
	album_cover?: AlbumCoverUrls | null;
	work: 'created' | 'lyrics' | 'style' | 'renamed' | 'take' | 'cowriter' | 'edited';
	worked_at: string;
}

export interface LibraryWriteResponse {
	items: LibraryWriteItem[];
}

export interface LoadModelOnWorkerRequest {
	mode: string;
}

export interface LoadedModelDetailItem {
	mode: string;
	size_gb: number;
}

export interface LoraCapacityErrorResponse {
	detail: string;
	reason: 'voice_limit' | 'training_queue_full';
}

export interface MemoryBundle {
	user: MemoryScopeItem;
	song?: MemoryScopeItem | null;
	album?: MemoryScopeItem | null;
}

export interface MemoryScopeItem {
	scope: 'user' | 'song' | 'album';
	target_id: string;
	body: string;
	updated_at?: string | null;
}

export interface MemoryUpdateRequest {
	body: string;
}

export interface ModelCapabilities {
	defaults: Record<string, unknown>;
	max_inference_steps: number;
	hidden_params: string[];
}

export interface OwnPlayableTakeListResponse {
	takes: OwnPlayableTakeResponse[];
}

export interface OwnPlayableTakeResponse {
	generation_id: string;
	song_title: string;
	generation_number: number;
	audio_url: string;
	caption: string;
	lyrics: string;
}

export interface PinModelOnWorkerRequest {
	mode: string;
}

export interface PlaylistAlbumSkipItem {
	song_id: string;
	title: string;
	reason: string;
}

export interface PlaylistCreateRequest {
	title: string;
}

export interface PlaylistDetailItem {
	id: string;
	title: string;
	slug: string;
	entry_count: number;
	is_shared: boolean;
	share_slug?: string | null;
	cover?: AlbumCoverUrls | null;
	album_covers: AlbumCoverUrls[];
	created_at: string;
	entries: PlaylistEntryItem[];
}

export interface PlaylistEntryItem {
	id: string;
	position: number;
	generation_id: string;
	song_id: string;
	song_title: string;
	album_title: string;
	artist: string;
	generation_number: number;
	version_number: number | null;
	is_picked: boolean;
	audio_duration: number | null;
	mp3_path: string;
	seed: number | null;
	model_mode: string;
	lyrics: string | null;
}

export interface PlaylistItem {
	id: string;
	title: string;
	slug: string;
	entry_count: number;
	is_shared: boolean;
	share_slug?: string | null;
	cover?: AlbumCoverUrls | null;
	album_covers: AlbumCoverUrls[];
	created_at: string;
}

export interface PlaylistUpdateRequest {
	title: string;
}

export interface PresetCreateRequest {
	name: string;
	model_mode: string;
	params: VersionGenerationParams;
	is_default: boolean;
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

export interface PresetUpdateRequest {
	name?: string | null;
	params?: VersionGenerationParams | null;
	is_default?: boolean | null;
}

export interface ProviderRouteReadiness {
	state: 'ready' | 'not_configured' | 'disturbed' | 'unverified';
	capability: 'tools_available' | 'text_only';
	reason?: SafeRouteReason | null;
	probed_at?: string | null;
	setup_label: string;
}

export interface ProviderRouteStatusResponse {
	models: string[];
	catalogue_failure?: SafeRouteReason | null;
	catalog_source?: string | null;
	catalog_version?: string | null;
	readiness: ProviderRouteReadiness;
	retained_model_id?: string | null;
}

export interface ProviderStatus {
	provider: string;
	cowriter_routes: Record<'cli' | 'api', ProviderRouteStatusResponse>;
	cover_routes: Record<'cli' | 'api', ProviderRouteReadiness>;
}

export interface QueueStreamManifest {
	snapshot_id: string;
	stream_url: string;
	expires_at: string;
	total_duration: number;
	tracks: QueueStreamTrackItem[];
	windowed: boolean;
	skipped: QueueStreamSkipItem[];
	skipped_complete: boolean;
}

export interface QueueStreamSkipItem {
	song_id: string;
	generation_id: string;
	reason: 'missing_path' | 'missing_file' | 'unreadable_file';
}

export interface QueueStreamTrackItem {
	key: string;
	index: number;
	entry_id: string | null;
	generation_id: string;
	song_id: string;
	song_title: string;
	artist: string;
	album_title: string;
	lyrics: string | null;
	generation_number: number;
	mp3_path: string;
	audio_url: string;
	seed: number | null;
	model_mode: string;
	duration: number;
	start_offset: number;
	end_offset: number;
}

export interface RateLimitItem {
	setting_key: string;
	value: number;
	is_override: boolean;
}

export interface RateLimitUpdateRequest {
	settings: Record<string, number>;
}

export interface RateLimitsResponse {
	settings: RateLimitItem[];
}

export interface RateRequest {
	rating: number;
	notes: string;
}

export interface RateResult {
	status: string;
	generation_id?: string | null;
	generation?: string | null;
	rating: number;
}

export interface ReferenceAudioResponse {
	path: string;
	filename: string;
}

export interface RegistryModelItem {
	mode: string;
	availability: 'downloaded' | 'not_downloaded' | 'unknown_no_worker';
	loaded_on: string[];
	loading_on: string[];
}

export interface RegistryResponse {
	models: RegistryModelItem[];
}

export interface ReorderPlaylistEntryRequest {
	new_position: number;
}

export interface RepaintRequest {
	src_generation_id: string;
	repainting_start: number;
	repainting_end: number;
	lyrics?: string | null;
	prompt?: string | null;
	version_id?: string | null;
	count: number;
	model: string;
	seed?: number | null;
	repaint_mode?: string | null;
	repaint_strength?: number | null;
	repaint_latent_crossfade_frames?: number | null;
	repaint_wav_crossfade_sec?: number | null;
}

export interface RepaintTaskParams {
	src_wav_path: string;
	src_generation_id: string;
	repainting_start: number;
	repainting_end: number;
	lyrics: string;
	prompt: string;
	repaint_mode?: RepaintMode | null;
	repaint_strength?: number | null;
	repaint_latent_crossfade_frames?: number | null;
	repaint_wav_crossfade_sec?: number | null;
}

export interface ResourceHelloEvent {
	high_water_mark: string;
}

export interface ResourceResyncEvent {
	high_water_mark: string;
}

export interface SafeRouteReason {
	code: 'api_key_not_set' | 'cli_login_not_configured' | 'cli_auth_rejected' | 'cli_binary_unavailable' | 'cli_capacity_exhausted' | 'cli_protocol_error' | 'api_http_error' | 'api_protocol_error' | 'catalogue_http_error' | 'catalogue_protocol_error' | 'tool_execution_failed' | 'tool_protocol_error' | 'tool_limit_exceeded' | 'no_image_tool' | 'route_failed';
	message: string;
}

export interface ScoreRequest {
	scorers?: string[] | null;
}

export interface ScorerSchemaItem {
	name: string;
	output_keys: string[];
	needs_audio: boolean;
	device: string;
	host: string;
}

export interface ScoringSchemaResponse {
	scorers: ScorerSchemaItem[];
}

export interface ShareResult {
	status: string;
	share_url: string;
	share_slug: string;
	songs_without_playable_take: UnplayableSongSummary[];
}

export interface SharedAlbumPayload {
	title: string;
	artist: string;
	subtitle: string;
	year: string;
	songs: SharedAlbumSongPayload[];
	cover?: AlbumCoverUrls | null;
}

export interface SharedAlbumSongPayload {
	id: string;
	title: string;
	track_number: number;
	audio_url: string | null;
	generation_id: string | null;
	audio_duration: number | null;
	lyrics: string | null;
	whisper_cues: WhisperCue[] | null;
}

export interface SharedGenerationPayload {
	title: string;
	artist: string;
	album_title: string;
	generation_number: number;
	audio_url: string | null;
	generation_id: string | null;
	audio_duration: number | null;
	lyrics: string | null;
	whisper_cues: WhisperCue[] | null;
	album_cover?: AlbumCoverUrls | null;
}

export interface SharedPlaylistEntryPayload {
	entry_id: string;
	song_title: string;
	album_title: string;
	artist: string;
	generation_number: number;
	audio_url: string | null;
	generation_id: string | null;
	audio_duration: number | null;
	lyrics: string | null;
	whisper_cues: WhisperCue[] | null;
	album_cover?: AlbumCoverUrls | null;
}

export interface SharedPlaylistPayload {
	title: string;
	entries: SharedPlaylistEntryPayload[];
	cover?: AlbumCoverUrls | null;
	album_covers: AlbumCoverUrls[];
}

export interface SharedSongPayload {
	title: string;
	artist: string;
	album_title: string;
	audio_url: string | null;
	generation_id: string | null;
	audio_duration: number | null;
	lyrics: string | null;
	whisper_cues: WhisperCue[] | null;
	cover?: AlbumCoverUrls | null;
	album_cover?: AlbumCoverUrls | null;
}

export interface SongCreateRequest {
	title: string;
	album_id: string;
	lyrics: string;
	prompt: string;
	bpm: number;
	audio_duration: number;
	key_scale: string;
	vocal_language: string;
	generation_params?: VersionGenerationParams | null;
}

export interface SongItem {
	id: string;
	slug: string;
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
	key_scale?: string | null;
	generation_params?: VersionGenerationParams | null;
	version_count: number;
	generation_count: number;
	is_shared: boolean;
	share_slug?: string | null;
	best_scores?: TrackScores | null;
	best_rating?: number | null;
	cover?: AlbumCoverUrls | null;
	created_at: string;
	generations: GenerationItem[];
}

export interface SongListenRequest {
	playlist_id?: string | null;
}

export interface SongMoveRequest {
	album_id: string;
}

export interface SongSummaryResponse {
	id: string;
	slug: string;
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
	key_scale?: string | null;
	generation_params?: Record<string, unknown> | null;
	version_count: number;
	generation_count: number;
	is_shared: boolean;
	share_slug?: string | null;
	best_scores?: Record<string, unknown> | null;
	best_rating?: number | null;
	cover?: AlbumCoverUrls | null;
	created_at: string;
}

export interface SongUpdateRequest {
	lyrics?: string | null;
	prompt?: string | null;
	bpm?: number | null;
	audio_duration?: number | null;
	key_scale?: string | null;
	vocal_language?: string | null;
	generation_params?: VersionGenerationParams | null;
	new_version: boolean;
}

export interface StatusResponse {
	status: string;
}

export interface TitleUpdateRequest {
	title: string;
}

export interface ToolCallEvent {
	type: 'tool_call';
	tool_use_id: string;
	name: string;
	input: Record<string, unknown>;
}

export interface ToolResultEvent {
	type: 'tool_result';
	tool_use_id: string;
	content: string;
	is_error: boolean;
}

export interface UnpinModelOnWorkerRequest {
	mode: string;
}

export interface UnplayableSongSummary {
	id: string;
	title: string;
}

export interface UserLoraCreateRequest {
	name: string;
}

export interface UserLoraItem {
	id: string;
	user_id: string;
	name: string;
	slug: string;
	status: string;
	model_mode: string;
	storage_path?: string | null;
	tensor_path?: string | null;
	training_job_id?: string | null;
	error?: string | null;
	created_at: string;
	completed_at?: string | null;
	deleted_at?: string | null;
	samples: UserLoraSampleItem[];
}

export interface UserLoraListResponse {
	loras: UserLoraItem[];
}

export interface UserLoraSampleFromGenerationRequest {
	generation_id: string;
}

export interface UserLoraSampleItem {
	id: string;
	user_lora_id: string;
	audio_path: string;
	caption: string;
	lyrics: string;
	position: number;
	created_at: string;
	updated_at: string;
}

export interface UserLoraSamplePatchRequest {
	caption?: string | null;
	lyrics?: string | null;
	position?: number | null;
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
	infer_method?: 'ode' | 'sde' | null;
	batch_size?: number | null;
	reference_audio_path?: string | null;
	repaint_mode?: RepaintMode | null;
	repaint_strength?: number | null;
	lm_repetition_penalty?: number | null;
	use_cot_caption?: boolean | null;
	use_cot_language?: boolean | null;
	use_adg?: boolean | null;
	cfg_interval_start?: number | null;
	cfg_interval_end?: number | null;
	sampler_mode?: 'euler' | 'heun' | null;
	velocity_norm_threshold?: number | null;
	velocity_ema_factor?: number | null;
	latent_shift?: number | null;
	latent_rescale?: number | null;
	audio_cover_strength?: number | null;
	user_lora_id?: string | null;
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
	created_at: string;
}

export interface WhisperCue {
	start: number;
	end: number;
	text: string;
	words?: WhisperWordCue[] | null;
}

export interface WhisperWordCue {
	start: number;
	end: number;
	text: string;
}

export interface WorkerEphemeralStateItem {
	loaded: LoadedModelDetailItem[];
	target_loading?: string | null;
	loading_started_at?: string | null;
	loading_last_log_line?: string | null;
	last_error?: string | null;
	last_error_at?: string | null;
	queue_depth: number;
	training_hold_seconds?: number | null;
	vram_used_gb?: number | null;
	vram_total_gb?: number | null;
	vram_measured?: boolean | null;
	available_modes: string[];
	pinned: string[];
	last_heartbeat_at?: string | null;
	gpu_healthy?: boolean | null;
	gpu_health_detail?: string | null;
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

export interface WorkerInfoItem {
	identity: WorkerIdentityItem;
	state: WorkerEphemeralStateItem | null;
	status: 'online' | 'loading' | 'offline';
}

export interface WorkerPoolResponse {
	workers: WorkerInfoItem[];
}
