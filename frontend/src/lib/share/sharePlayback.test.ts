import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { QueueStreamManifest } from '$lib/api/types';
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

function albumView(): SharedCollectionView {
	return fromSharedAlbum({
		title: 'Album',
		artist: 'Artist',
		subtitle: '',
		year: '',
		songs: [
			{ id: 's1', title: 'First', track_number: 1, audio_url: '/shared/slug/audio/s1.mp3' },
			{ id: 's2', title: 'Second', track_number: 2, audio_url: '/shared/slug/audio/s2.mp3' },
			{ id: 's3', title: 'Third (unpicked)', track_number: 3, audio_url: null }
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
				lyrics: 'verse one',
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
				lyrics: 'verse two',
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
		vi.fn(() => fakeAudio)
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

	it('exposes null lyrics in classic mode', () => {
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, null);

		playback.toggle(view.tracks[0]);

		expect(playback.lyrics).toBeNull();
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
		expect(playback.lyrics).toBe('verse two');
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
});

describe('shuffle', () => {
	it('switches playback to classic and reorders the queue, keeping the playing track first', () => {
		setQueuePlaybackMode('stream');
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, null);

		playback.toggle(view.tracks[0]);
		playback.setShuffle(true);

		expect(playback.shuffle).toBe(true);
		expect(playback.queueRows[0]?.key).toBe('s1');
		expect(audioPlayer.mode).toBe('classic');
		expect(playback.currentTrack?.key).toBe('s1');
		playback.stop();
	});

	it('restores the original order when disabled', () => {
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, null);

		playback.toggle(view.tracks[0]);
		playback.setShuffle(true);
		playback.setShuffle(false);

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
