import { describe, expect, it } from 'vitest';
import type { QueueStreamManifest } from '$lib/api/types';
import { QueueStreamEngine, streamTrackToPlaybackInfo } from './queueStreamEngine';

function manifest(windowed: boolean): QueueStreamManifest {
	return {
		snapshot_id: 'snapshot',
		stream_url: '/stream.mp3',
		expires_at: '2099-01-01T00:00:00Z',
		total_duration: 20,
		windowed,
		skipped: [],
		skipped_complete: true,
		tracks: [
			{
				key: 'first',
				index: 0,
				entry_id: null,
				generation_id: 'g1',
				song_id: 's1',
				song_title: 'First',
				artist: 'Artist',
				album_title: 'Album',
				lyrics: 'old verse',
				generation_number: 1,
				mp3_path: 'first.mp3',
				audio_url: '/audio/first.mp3',
				seed: null,
				model_mode: 'sft',
				duration: 10,
				start_offset: 0,
				end_offset: 10
			},
			{
				key: 'second',
				index: 1,
				entry_id: null,
				generation_id: 'g2',
				song_id: 's2',
				song_title: 'Second',
				artist: 'Artist',
				album_title: 'Album',
				lyrics: null,
				generation_number: 1,
				mp3_path: 'second.mp3',
				audio_url: '/audio/second.mp3',
				seed: null,
				model_mode: 'sft',
				duration: 10,
				start_offset: 10,
				end_offset: 20
			}
		]
	};
}

describe('streamTrackToPlaybackInfo', () => {
	it('maps version lyrics and album title from the stream track', () => {
		const info = streamTrackToPlaybackInfo(manifest(false).tracks[0]);
		expect(info.lyrics).toBe('old verse');
		expect(info.albumTitle).toBe('Album');
		expect(info.generation.version_lyrics).toBe('old verse');
	});

	it('keeps missing version lyrics as null', () => {
		const info = streamTrackToPlaybackInfo(manifest(false).tracks[1]);
		expect(info.lyrics).toBeNull();
		expect(info.generation.version_lyrics).toBeNull();
	});
});

describe('QueueStreamEngine window boundaries', () => {
	it('does not wrap a windowed stream at either boundary', () => {
		const engine = new QueueStreamEngine();
		const audio = { currentTime: 0 } as HTMLAudioElement;

		engine.start(manifest(true), 0);
		expect(engine.canPrev).toBe(false);
		expect(engine.canNext).toBe(true);
		engine.nextTrack(audio);
		expect(engine.canNext).toBe(false);
		expect(engine.nextTrack(audio)).toBeNull();
		expect(engine.prevTrack(audio)?.index).toBe(0);
		expect(engine.prevTrack(audio)).toBeNull();
	});

	it('keeps modulo navigation for an ordinary stream', () => {
		const engine = new QueueStreamEngine();
		const audio = { currentTime: 0 } as HTMLAudioElement;

		engine.start(manifest(false), 1);
		expect(engine.canNext).toBe(true);
		expect(engine.nextTrack(audio)?.index).toBe(0);
		expect(engine.canPrev).toBe(true);
	});
});
