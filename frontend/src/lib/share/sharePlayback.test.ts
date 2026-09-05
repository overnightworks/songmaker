import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { QueueStreamManifest, SharedAlbumSongPayload, WhisperCue } from '$lib/api/types';
import { setQueuePlaybackMode } from '$lib/stores/playbackSettings';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { fromSharedAlbum, type SharedCollectionView } from './sharedCollection';
import { SharePlayback } from './sharePlayback.svelte';

class FakeAudio {
	src = '';
	currentTime = 0;
	duration = 100;
	paused = true;
	ended = false;
	error: MediaError | null = null;
	crossOrigin: string | null = null;
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

const CUES: WhisperCue[] = [{ start: 0, end: 3, text: 'verse one' }];

function albumSong(
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

function albumView(): SharedCollectionView {
	return fromSharedAlbum({
		title: 'Album',
		artist: 'Artist',
		subtitle: '',
		year: '',
		songs: [
			albumSong('s1', 'First', 1, '/shared/slug/audio/s1.mp3', 128),
			albumSong('s2', 'Second', 2, '/shared/slug/audio/s2.mp3', 96),
			albumSong('s3', 'Third (unpicked)', 3, null, null)
		]
	});
}

function streamManifest(windowed: boolean): QueueStreamManifest {
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

let fakeAudio: FakeAudio;

beforeEach(() => {
	fakeAudio = new FakeAudio();
	vi.stubGlobal(
		'Audio',
		vi.fn(function () {
			return fakeAudio;
		})
	);
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200 }));
	audioPlayer.destroy();
	audioPlayer.swapCallbacks({
		onEnded: null,
		onPlaybackStarted: null,
		onAuthLost: null,
		onStreamRebuild: null,
		onCurrentChange: null
	});
	setQueuePlaybackMode('classic');
});

afterEach(() => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe('start()', () => {
	it('exposes only playable tracks, dropping unpicked songs', () => {
		const playback = new SharePlayback();
		playback.start(albumView(), null);

		expect(playback.queueRows.map((r) => r.key)).toEqual(['s1', 's2']);
		playback.stop();
	});

	it('shows each row its payload duration without a stream manifest', () => {
		const playback = new SharePlayback();
		playback.start(albumView(), null);

		expect(playback.queueRows.map((r) => r.durationSec)).toEqual([128, 96]);
		playback.stop();
	});

	it('installs onAuthLost: null since a share owner never receives an auth-recovery callback', () => {
		const playback = new SharePlayback();
		playback.start(albumView(), null);

		expect(audioPlayer.currentCallbacks.onAuthLost).toBeNull();
		playback.stop();
	});
});

describe('toggle() and classic playback', () => {
	it('loads the clicked track via loadUrl when no stream fetcher is provided', () => {
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, null);

		playback.toggle(view.tracks[0]);

		expect(audioPlayer.current?.songId).toBe('s1');
		expect(fakeAudio.src).toBe('/shared/slug/audio/s1.mp3');
		expect(playback.currentTrack?.key).toBe('s1');
		playback.stop();
	});

	it('exposes the playing take cues so the shared Now Playing can follow the words', () => {
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, null);

		expect(playback.currentCues).toBeNull();
		playback.toggle(view.tracks[0]);

		expect(playback.currentCues).toEqual(CUES);
		playback.stop();
	});

	it('pauses instead of reloading when toggling the currently playing track', () => {
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, null);

		playback.toggle(view.tracks[0]);
		fakeAudio.fire('canplay');
		fakeAudio.fire('play');
		fakeAudio.playMock.mockClear();

		playback.toggle(view.tracks[0]);

		expect(fakeAudio.paused).toBe(true);
		expect(fakeAudio.playMock).not.toHaveBeenCalled();
		playback.stop();
	});

	it('jump(index) plays the track at that position in the current play order', () => {
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, null);

		playback.jump(1);

		expect(playback.currentTrack?.key).toBe('s2');
		playback.stop();
	});

	it('wraps next/prev in classic mode', () => {
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, null);

		playback.toggle(view.tracks[1]);
		playback.next();

		expect(playback.currentTrack?.key).toBe('s1');
		playback.stop();
	});
});

describe('stream playback', () => {
	it('plays via the stream manifest when stream mode is enabled and a fetcher is provided', async () => {
		setQueuePlaybackMode('stream');
		const fetchStream = vi.fn().mockResolvedValue(streamManifest(false));
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, fetchStream);

		playback.toggle(view.tracks[1]);
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));

		expect(fakeAudio.src).toBe('/shared-stream.mp3');
		expect(audioPlayer.current?.songTitle).toBe('Second');
		playback.stop();
	});

	it('flags windowEnded without wrapping when a windowed stream ends', async () => {
		setQueuePlaybackMode('stream');
		const fetchStream = vi.fn().mockResolvedValue(streamManifest(true));
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, fetchStream);

		playback.jump(1);
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));
		fakeAudio.fire('ended');

		expect(playback.windowEnded).toBe(true);
		expect(playback.currentTrack?.key).toBe('s2');
		playback.stop();
	});

	it('falls back to classic playback when the stream fetch fails', async () => {
		setQueuePlaybackMode('stream');
		const fetchStream = vi.fn().mockRejectedValue(new Error('network'));
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, fetchStream);

		playback.toggle(view.tracks[0]);
		await vi.waitFor(() => expect(audioPlayer.current?.songId).toBe('s1'));

		expect(audioPlayer.mode).toBe('classic');
		expect(fakeAudio.src).toBe('/shared/slug/audio/s1.mp3');
		playback.stop();
	});

	it('reuses a fresh manifest across two plays instead of refetching', async () => {
		setQueuePlaybackMode('stream');
		const fetchStream = vi.fn().mockResolvedValue(streamManifest(false));
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, fetchStream);

		playback.toggle(view.tracks[0]);
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));
		playback.jump(1);
		await vi.waitFor(() => expect(playback.currentTrack?.key).toBe('s2'));

		expect(fetchStream).toHaveBeenCalledTimes(1);
		playback.stop();
	});

	it('rebuilds a shared stream after its snapshot expires', async () => {
		setQueuePlaybackMode('stream');
		const freshManifest = { ...streamManifest(false), stream_url: '/shared-stream-fresh.mp3' };
		const fetchStream = vi
			.fn()
			.mockResolvedValueOnce(streamManifest(false))
			.mockResolvedValueOnce(freshManifest);
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, fetchStream);

		playback.toggle(view.tracks[0]);
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }));
		fakeAudio.currentTime = 4;
		fakeAudio.fire('timeupdate');
		fakeAudio.fire('error');

		await vi.waitFor(() => expect(fakeAudio.src).toBe('/shared-stream-fresh.mp3'));

		expect(fetchStream).toHaveBeenCalledTimes(2);
		expect(playback.currentTrack?.key).toBe('s1');
		playback.stop();
	});
});

describe('shuffle', () => {
	it('drops out of stream mode to classic per-track playback, keeping the playing track first', async () => {
		setQueuePlaybackMode('stream');
		const fetchStream = vi.fn().mockResolvedValue(streamManifest(false));
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, fetchStream);

		playback.toggle(view.tracks[0]);
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));

		playback.setShuffle(true);

		expect(playback.shuffle).toBe(true);
		expect(playback.queueRows[0]?.key).toBe('s1');
		expect(audioPlayer.mode).toBe('classic');
		expect(fakeAudio.src).toBe('/shared/slug/audio/s1.mp3');
		expect(playback.currentTrack?.key).toBe('s1');
		playback.stop();
	});

	it('returns to stream mode when disabled', async () => {
		setQueuePlaybackMode('stream');
		const fetchStream = vi.fn().mockResolvedValue(streamManifest(false));
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, fetchStream);

		playback.toggle(view.tracks[0]);
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));

		playback.setShuffle(true);
		expect(audioPlayer.mode).toBe('classic');

		playback.setShuffle(false);
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));

		expect(playback.queueRows.map((r) => r.key)).toEqual(['s1', 's2']);
		playback.stop();
	});
});

describe('stop()', () => {
	it('restores the previous callback set and unloads playback', () => {
		const previousOnEnded = vi.fn();
		audioPlayer.swapCallbacks({
			onEnded: previousOnEnded,
			onPlaybackStarted: null,
			onAuthLost: null,
			onStreamRebuild: null,
			onCurrentChange: null
		});
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, null);
		playback.toggle(view.tracks[0]);

		playback.stop();

		expect(audioPlayer.current).toBeNull();
		fakeAudio.fire('ended');
		expect(previousOnEnded).toHaveBeenCalled();
	});
});
