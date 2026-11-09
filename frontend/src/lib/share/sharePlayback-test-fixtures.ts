import { vi } from 'vitest';
import type { QueueStreamManifest, SharedAlbumSongPayload, WhisperCue } from '#lib/api/types.ts';
import type { AudioPlayerCallbacks } from '#lib/services/audioPlayer.svelte.ts';
import { fromSharedAlbum, fromSharedSong, type SharedCollectionView } from './sharedCollection';

export class FakeAudio {
	src = '';
	currentTime = 0;
	duration = 100;
	paused = true;
	ended = false;
	error: MediaError | null = null;
	crossOrigin: string | null = null;
	buffered = { length: 0, end: () => 0 };
	preload = '';
	private listeners = new Map<string, Set<EventListener>>();
	playMock = vi.fn(() => {
		this.paused = false;
		queueMicrotask(() => this.fire('play'));
		return Promise.resolve();
	});

	addEventListener(name: string, listener: EventListener): void {
		const set = this.listeners.get(name) ?? new Set();
		set.add(listener);
		this.listeners.set(name, set);
	}
	removeEventListener(name: string, listener: EventListener): void {
		this.listeners.get(name)?.delete(listener);
	}
	removeAttribute(): void {}
	pause(): void {
		this.paused = true;
		this.fire('pause');
	}
	play(): Promise<void> {
		return this.playMock();
	}
	load(): void {
		this.fire('loadstart');
	}
	fire(name: string, init?: Partial<Event>): void {
		const event = { type: name, ...init } as Event;
		const ls = this.listeners.get(name);
		if (!ls) return;
		for (const l of ls) l(event);
	}
}

// Installs the fake as the player's audio element and returns it.
export function installFakeAudio(): FakeAudio {
	const audio = new FakeAudio();
	vi.stubGlobal(
		'Audio',
		vi.fn(function () {
			return audio;
		})
	);
	return audio;
}

export const CUES: WhisperCue[] = [{ start: 0, end: 3, text: 'verse one' }];

export function albumSong(
	id: string,
	title: string,
	trackNumber: number,
	audioUrl: string | null,
	audioDuration: number | null
): SharedAlbumSongPayload {
	return {
		id,
		title,
		track_number: trackNumber,
		audio_url: audioUrl,
		generation_id: audioUrl ? `gen-${id}` : null,
		audio_duration: audioDuration,
		lyrics: audioUrl ? 'verse one' : null,
		whisper_cues: audioUrl ? CUES : null
	};
}

export function albumView(slug = 'slug'): SharedCollectionView {
	return fromSharedAlbum({
		title: 'Album',
		artist: 'Artist',
		subtitle: '',
		year: '',
		songs: [
			albumSong('s1', 'First', 1, `/shared/${slug}/audio/s1.mp3`, 128),
			albumSong('s2', 'Second', 2, `/shared/${slug}/audio/s2.mp3`, 96),
			albumSong('s3', 'Third (unpicked)', 3, null, null)
		]
	});
}

export function songView(): SharedCollectionView {
	return fromSharedSong({
		title: 'Solo',
		artist: 'Artist',
		album_title: 'Album',
		audio_url: '/shared/song/solo/audio/solo.mp3',
		generation_id: 'g-solo',
		audio_duration: 120,
		lyrics: null,
		whisper_cues: null,
		cover: null,
		album_cover: null
	});
}

export const NO_CALLBACKS: AudioPlayerCallbacks = {
	onEnded: null,
	onPlaybackStarted: null,
	onAuthLost: null,
	onStreamRebuild: null,
	onCurrentChange: null,
	networkFailureIsAnnounced: () => false
};

export function streamManifest(windowed: boolean): QueueStreamManifest {
	return {
		snapshot_id: 'snap',
		stream_url: '/shared-stream.mp3',
		expires_at: '2099-01-01T00:00:00Z',
		total_duration: 20,
		windowed,
		skipped: [],
		skipped_complete: true,
		tracks: [
			{
				key: 's1',
				index: 0,
				entry_id: null,
				generation_id: 'g1',
				song_id: 's1',
				song_title: 'First',
				artist: 'Artist',
				album_title: 'Album',
				// public_queue_stream_manifest() redacts lyrics on a share stream.
				lyrics: null,
				generation_number: 1,
				mp3_path: 's1.mp3',
				audio_url: '/shared/slug/audio/s1.mp3',
				seed: null,
				model_mode: 'sft',
				duration: 10,
				start_offset: 0,
				end_offset: 10
			},
			{
				key: 's2',
				index: 1,
				entry_id: null,
				generation_id: 'g2',
				song_id: 's2',
				song_title: 'Second',
				artist: 'Artist',
				album_title: 'Album',
				lyrics: null,
				generation_number: 1,
				mp3_path: 's2.mp3',
				audio_url: '/shared/slug/audio/s2.mp3',
				seed: null,
				model_mode: 'sft',
				duration: 10,
				start_offset: 10,
				end_offset: 20
			}
		]
	};
}
