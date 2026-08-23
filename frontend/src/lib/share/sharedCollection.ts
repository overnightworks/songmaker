// Pure adapters from the four `/shared/*` payload shapes to one collection
// model the share surface renders. No stores, no fetch — see
// docs/architecture.md's share section for the surface this feeds.

import type { GenerationItem } from '$lib/api/types';
import type { PlaybackInfo } from '$lib/services/playbackTypes';

export type SharedCollectionKind = 'album' | 'playlist' | 'song' | 'take';

export interface SharedCover {
	card: string;
	detail: string;
}

export interface SharedTrack {
	key: string;
	title: string;
	subtitle: string | null;
	audioUrl: string | null;
}

export interface SharedCollectionView {
	kind: SharedCollectionKind;
	title: string;
	artist: string;
	albumTitle: string | null;
	year: string | null;
	takeNumber: number | null;
	seed: number | null;
	cover: SharedCover | null;
	tracks: SharedTrack[];
}

export interface SharedAlbumSongPayload {
	id: string;
	title: string;
	track_number: number;
	audio_url: string | null;
}

export interface SharedAlbumPayload {
	title: string;
	artist: string;
	subtitle: string;
	year: string;
	songs: SharedAlbumSongPayload[];
	cover?: SharedCover | null;
}

export interface SharedPlaylistEntryPayload {
	entry_id: string;
	song_title: string;
	artist: string;
	generation_number: number;
	audio_url: string | null;
}

export interface SharedPlaylistPayload {
	title: string;
	entries: SharedPlaylistEntryPayload[];
}

export interface SharedSongPayload {
	title: string;
	artist: string;
	album_title: string;
	audio_url: string | null;
	cover?: SharedCover | null;
}

export interface SharedGenerationPayload {
	title: string;
	artist: string;
	album_title: string;
	generation_number: number;
	seed: number | null;
	audio_url: string | null;
}

export function fromSharedAlbum(payload: SharedAlbumPayload): SharedCollectionView {
	return {
		kind: 'album',
		title: payload.title,
		artist: payload.artist,
		albumTitle: null,
		year: payload.year || null,
		takeNumber: null,
		seed: null,
		cover: payload.cover ?? null,
		tracks: payload.songs.map((song) => ({
			key: song.id,
			title: song.title,
			subtitle: null,
			audioUrl: song.audio_url
		}))
	};
}

export function fromSharedPlaylist(payload: SharedPlaylistPayload): SharedCollectionView {
	return {
		kind: 'playlist',
		title: payload.title,
		artist: '',
		albumTitle: null,
		year: null,
		takeNumber: null,
		seed: null,
		cover: null,
		tracks: payload.entries.map((entry) => ({
			key: entry.entry_id,
			title: entry.song_title,
			subtitle: entry.artist,
			audioUrl: entry.audio_url
		}))
	};
}

export function fromSharedSong(payload: SharedSongPayload): SharedCollectionView {
	return {
		kind: 'song',
		title: payload.title,
		artist: payload.artist,
		albumTitle: payload.album_title || null,
		year: null,
		takeNumber: null,
		seed: null,
		cover: payload.cover ?? null,
		tracks: [{ key: 'single', title: payload.title, subtitle: null, audioUrl: payload.audio_url }]
	};
}

export function fromSharedGeneration(payload: SharedGenerationPayload): SharedCollectionView {
	return {
		kind: 'take',
		title: payload.title,
		artist: payload.artist,
		albumTitle: payload.album_title || null,
		year: null,
		takeNumber: payload.generation_number,
		seed: payload.seed,
		cover: null,
		tracks: [{ key: 'single', title: payload.title, subtitle: null, audioUrl: payload.audio_url }]
	};
}

// Songs/entries without a pick carry `audio_url: null` (sharing_api.py keeps
// sending them so the payload stays complete) — the share surface hides them
// entirely rather than showing a disabled row (locked-in: a listener sees a
// finished album).
export function playableTracks(tracks: SharedTrack[]): SharedTrack[] {
	return tracks.filter(
		(track): track is SharedTrack & { audioUrl: string } => track.audioUrl !== null
	);
}

// The header's byline, one string per collection kind — pure so the
// collection surface never has to branch on `kind` itself. A public listener
// never sees the internal take number (issue #119): a shared take's byline
// reads the same as a shared song's.
export function collectionSubtitle(view: SharedCollectionView): string {
	if (view.kind === 'playlist') {
		const count = playableTracks(view.tracks).length;
		return `${count} track${count !== 1 ? 's' : ''}`;
	}
	if (view.kind === 'take' || view.kind === 'song') {
		return [view.artist, view.albumTitle].filter(Boolean).join(' · ');
	}
	return [view.artist, view.year].filter(Boolean).join(' · ');
}

const SHARE_GENERATION_NUMBER = 1;
const SHARE_MODEL_MODE = 'sft';

// A synthetic PlaybackInfo for classic (non-stream) share playback: audioPlayer
// only needs a stable identity (generation.id) and display fields, never a
// real generation row — see audioPlayer.loadUrl(), which takes the audio URL
// directly instead of resolving one from generation.mp3_path.
export function trackPlaybackInfo(
	collection: SharedCollectionView,
	track: SharedTrack
): PlaybackInfo {
	const albumTitle = collection.kind === 'album' ? collection.title : (collection.albumTitle ?? '');
	const artist = collection.kind === 'playlist' ? (track.subtitle ?? '') : collection.artist;
	const generation: GenerationItem = {
		id: track.key,
		song_id: track.key,
		version_id: null,
		version_number: null,
		generation_number: SHARE_GENERATION_NUMBER,
		mp3_path: '',
		wav_path: null,
		seed: null,
		status: 'completed',
		is_archived: false,
		is_picked: false,
		is_kept: true,
		is_shared: true,
		model_mode: SHARE_MODEL_MODE,
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: null,
		scores: null,
		generation_params: null,
		created_at: ''
	};
	return {
		generation,
		songId: track.key,
		songTitle: track.title,
		artist,
		albumTitle,
		lyrics: null
	};
}
