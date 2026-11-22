import type {
	GenerationItem,
	PlaylistDetailItem,
	PlaylistEntryItem,
	SongItem
} from '#lib/api/types.ts';
import type { PlaybackInfo } from '#lib/services/playbackTypes.ts';
import { makeGeneration as makeGen } from '#lib/test-utils/factories.ts';
import type { queueContext } from '#lib/stores/queue.ts';

export const genDefaults = {
	mp3_path: 'a1/song_v1.mp3',
	wav_path: 'a1/song_v1.wav',
	seed: 42,
	model_mode: 'sft',
	created_at: ''
} satisfies Partial<GenerationItem>;

export const playlistEntryDefaults = {
	album_title: 'Album',
	mp3_path: 'a1/song_v1.mp3',
	seed: 42
} satisfies Partial<PlaylistEntryItem>;

export function queuedSongDefaults(): Partial<SongItem> {
	return { slug: 'song', title: 'Song', generations: [makeGen(genDefaults)], created_at: '' };
}

type QueueContext = Parameters<typeof queueContext.set>[0];

export const QUEUE_PLAYLIST: Pick<PlaylistDetailItem, 'id' | 'title'> = {
	id: 'p1',
	title: 'Night Drive'
};

export function playlistQueue(entries: PlaylistEntryItem[], index: number): QueueContext {
	return { type: 'playlist', playlist: QUEUE_PLAYLIST, entries, index };
}

export function makePlayback(gen: GenerationItem, song: SongItem): PlaybackInfo {
	return {
		generation: gen,
		songId: song.id,
		songTitle: song.title,
		artist: song.artist,
		albumTitle: song.album_title,
		lyrics: gen.version_lyrics
	};
}
