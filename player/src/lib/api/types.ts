/** API response types — match Python DB models.
 *
 * Hierarchy: Song → Version (content) → Generation (MP3 output)
 */

export interface GenerationParams {
	seed?: number;
	acestep_model?: string;
	acestep_lm_model?: string;
	bpm?: number;
	duration?: number;
	key?: string;
	guidance_scale?: number;
	inference_steps?: number;
	shift?: number;
	think_mode?: boolean;
	lm_temperature?: number;
	infer_method?: string;
	songmaker_version?: string;
	generated_at?: string;
}

export interface TrackScores {
	lyrical_coherence?: number;
	lyrical_summary?: string;
	dynamics?: number;
	text_accuracy?: number;
	audiobox_enjoyment?: number;
	audiobox_understanding?: number;
	audiobox_complexity?: number;
	audiobox_quality?: number;
	silence_gaps?: number;
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
	whisper_text: string | null;
	scores: TrackScores | null;
	generation_params: GenerationParams | null;
	created_at: string | null;
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
	colors: { primary: string; bg: string };
	song_count: number;
}

export interface Capabilities {
	claude_api: boolean;
	claude_cli: boolean;
	generation: boolean;
	scoring: boolean;
}
