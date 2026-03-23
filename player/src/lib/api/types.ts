/** API response types — match Python DB models. */

export interface GenerationInfo {
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

/** A version from the DB API — each generation attempt. */
export interface VersionItem {
	id: string;
	song_id: string;
	version_number: number;
	mp3_path: string;
	title: string;
	album_id: string;
	album_title: string;
	artist: string;
	track_number: number;
	seed: number | null;
	status: string;
	is_archived: boolean;
	whisper_text: string | null;
	scores: TrackScores | null;
	generation: GenerationInfo | null;
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

export interface PaginatedResponse {
	items: VersionItem[];
	total: number;
	offset: number;
	limit: number;
}

export interface Capabilities {
	claude_api: boolean;
	claude_cli: boolean;
	generation: boolean;
	scoring: boolean;
}

/** Internal UI types — used by store and components. */

export interface LyricsLine {
	time: number;
	text: string;
	section: boolean;
	confidence?: number;
}

export interface SrtLine {
	time: number;
	text: string;
}

export interface Track {
	file: string;
	title: string;
	number: string;
	lines: (SrtLine | LyricsLine)[];
	intended: LyricsLine[];
	has_sung: boolean;
	generation: GenerationInfo | null;
	scores: TrackScores | null;
}

export interface Album {
	id: string;
	title: string;
	artist: string;
	subtitle: string;
	year: string;
	colors: { primary: string; bg: string };
	tracks: Track[];
}
