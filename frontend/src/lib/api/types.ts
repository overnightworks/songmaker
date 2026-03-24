/** API response types — match Python DB models.
 *
 * Hierarchy: Song → Version (content) → Generation (MP3 output)
 */

export interface GenerationParams {
	seed?: number;
	acestep_model?: string;
	bpm?: number;
	duration?: number;
	key?: string;
	guidance_scale?: number;
	inference_steps?: number;
	shift?: number;
	think_mode?: boolean;
	lm_temperature?: number;
	infer_method?: string;
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

/** A generated MP3 from a version. */
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

/** ACE-Step generation settings stored per version (null = use global default). */
export interface VersionGenerationParams {
	inference_steps?: number;
	guidance_scale?: number;
	shift?: number;
	think_mode?: boolean;
	lm_temperature?: number;
	infer_method?: string;
}

/** A content snapshot — lyrics, prompt, params. */
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

/** A song with its versions and generations. */
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
	generation_params: VersionGenerationParams | null;
	version_count: number;
	generation_count: number;
	best_scores: TrackScores | null;
	best_rating: number | null;
	generations: GenerationItem[];
	created_at: string | null;
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

export interface Capabilities {
	claude_api: boolean;
	claude_cli: boolean;
	generation: boolean;
	scoring: boolean;
}
