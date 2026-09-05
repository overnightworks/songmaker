// Pure adapters from the four `/shared/*` payload shapes to one collection
// model the share surface renders. No stores, no fetch — see
// docs/architecture.md's share section for the surface this feeds.
//
// The payload shapes themselves are generated from the Pydantic share models
// (scripts/generate_types.py), so a new field on a share response reaches the
// share surface without a second, hand-maintained copy of the contract here.

import type {
	AlbumCoverUrls,
	GenerationItem,
	SharedAlbumPayload,
	SharedGenerationPayload,
	SharedPlaylistPayload,
	SharedSongPayload,
	WhisperCue
} from '$lib/api/types';
import type { PlaybackInfo } from '$lib/services/playbackTypes';

export type {
	SharedAlbumPayload,
	SharedGenerationPayload,
	SharedPlaylistPayload,
	SharedSongPayload
};
export type { SharedAlbumSongPayload, SharedPlaylistEntryPayload } from '$lib/api/types';

export type SharedCollectionKind = 'album' | 'playlist' | 'song' | 'take';

export interface SharedTrack {
	key: string;
	title: string;
	subtitle: string | null;
	audioUrl: string | null;
	durationSec: number | null;
	lyrics: string | null;
	cues: WhisperCue[] | null;
}

export interface SharedCollectionView {
	kind: SharedCollectionKind;
	title: string;
	artist: string;
	albumTitle: string | null;
	year: string | null;
	cover: AlbumCoverUrls | null;
	playlistCovers?: AlbumCoverUrls[];
	tracks: SharedTrack[];
}

// The media half of every share payload — one take's duration, lyrics, and
// cues, named identically across all four responses.
type SharedTakeMedia = Pick<
	SharedSongPayload,
	'audio_url' | 'audio_duration' | 'lyrics' | 'whisper_cues'
>;

function sharedTrack(
	key: string,
	title: string,
	subtitle: string | null,
	media: SharedTakeMedia
): SharedTrack {
	return {
		key,
		title,
		subtitle,
		audioUrl: media.audio_url,
		durationSec: media.audio_duration,
		lyrics: media.lyrics,
		cues: media.whisper_cues
	};
}

export function fromSharedAlbum(payload: SharedAlbumPayload): SharedCollectionView {
	return {
		kind: 'album',
		title: payload.title,
		artist: payload.artist,
		albumTitle: null,
		year: payload.year || null,
		cover: payload.cover ?? null,
		playlistCovers: [],
		tracks: payload.songs.map((song) => sharedTrack(song.id, song.title, null, song))
	};
}

export function fromSharedPlaylist(payload: SharedPlaylistPayload): SharedCollectionView {
	return {
		kind: 'playlist',
		title: payload.title,
		artist: '',
		albumTitle: null,
		year: null,
		cover: payload.cover ?? null,
		playlistCovers: payload.album_covers,
		tracks: payload.entries.map((entry) =>
			sharedTrack(entry.entry_id, entry.song_title, entry.artist, entry)
		)
	};
}

const SINGLE_TRACK_KEY = 'single';

export function fromSharedSong(payload: SharedSongPayload): SharedCollectionView {
	return {
		kind: 'song',
		title: payload.title,
		artist: payload.artist,
		albumTitle: payload.album_title || null,
		year: null,
		cover: payload.album_cover ?? null,
		playlistCovers: [],
		tracks: [sharedTrack(SINGLE_TRACK_KEY, payload.title, null, payload)]
	};
}

export function fromSharedGeneration(payload: SharedGenerationPayload): SharedCollectionView {
	return {
		kind: 'take',
		title: payload.title,
		artist: payload.artist,
		albumTitle: payload.album_title || null,
		year: null,
		cover: payload.album_cover ?? null,
		playlistCovers: [],
		tracks: [sharedTrack(SINGLE_TRACK_KEY, payload.title, null, payload)]
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
// directly instead of resolving one from generation.mp3_path. The lyrics and
// cues are the shared take's own, so Now Playing follows the words on a share
// page exactly as it does in the app.
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
		audio_duration_sec: track.durationSec,
		is_archived: false,
		is_picked: false,
		is_kept: true,
		is_shared: true,
		model_mode: SHARE_MODEL_MODE,
		whisper_text: null,
		whisper_cues: track.cues,
		version_lyrics: track.lyrics,
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
		lyrics: track.lyrics
	};
}
