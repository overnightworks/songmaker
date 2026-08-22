import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { GenerationItem, QueueStreamManifest } from '$lib/api/types';
import { audioPlayer, type AudioPlayerCallbacks, type PlaybackInfo } from './audioPlayer.svelte';

function callbacks(overrides: Partial<AudioPlayerCallbacks> = {}): AudioPlayerCallbacks {
	return {
		onEnded: null,
		onPlaybackStarted: null,
		onAuthLost: null,
		onStreamRebuild: null,
		onCurrentChange: null,
		...overrides
	};
}

function makeGen(overrides: Partial<GenerationItem> = {}): GenerationItem {
	return {
		id: 'g1',
		song_id: 's1',
		version_id: 'v1',
		version_number: 1,
		generation_number: 1,
		mp3_path: 'a1/song_v1.mp3',
		wav_path: 'a1/song_v1.wav',
		seed: 42,
		status: 'completed',
		is_archived: false,
		is_picked: false,
		is_kept: false,
		model_mode: 'sft',
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: null,
		scores: null,
		generation_params: null,
		created_at: '2026-01-01T00:00:00Z',
		is_shared: false,
		share_slug: null,
		...overrides
	};
}

function makeInfo(overrides: Partial<PlaybackInfo> = {}): PlaybackInfo {
	return {
		generation: makeGen(),
		songId: 's1',
		songTitle: 'Song',
		artist: 'Artist',
		albumTitle: 'Album',
		lyrics: null,
		...overrides
	};
}

function makeStreamManifest(): QueueStreamManifest {
	return {
		snapshot_id: 'snap',
		stream_url: '/api/queue-streams/snap/audio',
		expires_at: '2026-01-01T00:00:00Z',
		total_duration: 30,
		tracks: [
			{
				key: 'one',
				index: 0,
				entry_id: 'one',
				generation_id: 'g1',
				song_id: 's1',
				song_title: 'First',
				artist: 'Artist',
				album_title: 'Album',
				lyrics: 'first verse',
				generation_number: 1,
				mp3_path: 'a1/first.mp3',
				audio_url: '/audio/a1/first.mp3',
				seed: 1,
				model_mode: 'sft',
				duration: 10,
				start_offset: 0,
				end_offset: 10
			},
			{
				key: 'two',
				index: 1,
				entry_id: 'two',
				generation_id: 'g2',
				song_id: 's2',
				song_title: 'Second',
				artist: 'Artist',
				album_title: 'Album',
				lyrics: 'second verse',
				generation_number: 1,
				mp3_path: 'a1/second.mp3',
				audio_url: '/audio/a1/second.mp3',
				seed: 2,
				model_mode: 'sft',
				duration: 20,
				start_offset: 10,
				end_offset: 30
			}
		],
		windowed: false,
		skipped: [],
		skipped_complete: true
	};
}

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
	removeAttribute(_name: string): void {}
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

let fakeAudio: FakeAudio;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
	fakeAudio = new FakeAudio();
	vi.stubGlobal(
		'Audio',
		vi.fn(() => fakeAudio)
	);
	vi.stubGlobal('MediaError', {
		MEDIA_ERR_ABORTED: 1,
		MEDIA_ERR_NETWORK: 2,
		MEDIA_ERR_DECODE: 3,
		MEDIA_ERR_SRC_NOT_SUPPORTED: 4
	});
	fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 });
	vi.stubGlobal('fetch', fetchMock);
	audioPlayer.destroy();
	audioPlayer.swapCallbacks(callbacks());
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe('initial state', () => {
	it('starts idle with no current track', () => {
		expect(audioPlayer.status).toBe('idle');
		expect(audioPlayer.current).toBeNull();
		expect(audioPlayer.currentTime).toBe(0);
		expect(audioPlayer.duration).toBe(0);
		expect(audioPlayer.error).toBeNull();
	});
});

describe('load()', () => {
	it('sets current and transitions to loading', () => {
		const info = makeInfo();
		audioPlayer.load(info);
		expect(audioPlayer.current?.songTitle).toBe('Song');
		expect(audioPlayer.current?.generation.id).toBe('g1');
		expect(audioPlayer.status).toBe('loading');
		expect(fakeAudio.src).toBe('/audio/a1/song_v1.mp3');
	});

	it('autoplays after canplay by default', () => {
		audioPlayer.load(makeInfo());
		fakeAudio.fire('canplay');
		expect(fakeAudio.playMock).toHaveBeenCalled();
	});

	it('does not autoplay when opts.autoplay is false', () => {
		audioPlayer.load(makeInfo(), { autoplay: false });
		fakeAudio.fire('canplay');
		expect(fakeAudio.playMock).not.toHaveBeenCalled();
		expect(audioPlayer.status).toBe('ready');
	});

	it('does not reload when same generation_id is loaded again', () => {
		const info = makeInfo();
		audioPlayer.load(info);
		fakeAudio.fire('canplay');
		fakeAudio.fire('play');
		const initialSrc = fakeAudio.src;
		audioPlayer.load(makeInfo({ generation: makeGen() }));
		expect(fakeAudio.src).toBe(initialSrc);
	});

	it('reloads the same generation when restart is requested', () => {
		const info = makeInfo();
		audioPlayer.load(info);
		fakeAudio.fire('canplay');
		fakeAudio.fire('play');
		fakeAudio.currentTime = 42;

		audioPlayer.load(info, { restart: true });

		expect(fakeAudio.src).toBe('/audio/a1/song_v1.mp3');
		expect(audioPlayer.currentTime).toBe(0);
		expect(audioPlayer.status).toBe('loading');
	});

	it('reloads when generation id differs', () => {
		audioPlayer.load(makeInfo());
		audioPlayer.load(makeInfo({ generation: makeGen({ id: 'g2', mp3_path: 'b.mp3' }) }));
		expect(fakeAudio.src).toBe('/audio/b.mp3');
	});

	it('clears prior error state on new load', () => {
		audioPlayer.load(makeInfo());
		fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;
		fakeAudio.fire('error');
		expect(audioPlayer.status).toBe('error');
		audioPlayer.load(makeInfo({ generation: makeGen({ id: 'g2', mp3_path: 'b.mp3' }) }));
		expect(audioPlayer.status).toBe('loading');
		expect(audioPlayer.error).toBeNull();
	});
});

describe('event handling', () => {
	beforeEach(() => {
		audioPlayer.load(makeInfo(), { autoplay: false });
	});

	it('loadedmetadata sets duration', () => {
		fakeAudio.duration = 245;
		fakeAudio.fire('loadedmetadata');
		expect(audioPlayer.duration).toBe(245);
	});

	it('canplay transitions to ready when paused', () => {
		fakeAudio.fire('canplay');
		expect(audioPlayer.status).toBe('ready');
	});

	it('timeupdate updates currentTime', () => {
		fakeAudio.currentTime = 12.5;
		fakeAudio.fire('timeupdate');
		expect(audioPlayer.currentTime).toBe(12.5);
	});

	it('play event sets status to playing', () => {
		fakeAudio.fire('play');
		expect(audioPlayer.status).toBe('playing');
	});

	it('pause event sets status to paused (when not error or ended)', () => {
		fakeAudio.fire('play');
		fakeAudio.paused = true;
		fakeAudio.fire('pause');
		expect(audioPlayer.status).toBe('paused');
	});

	it('pause event ignored when ended', () => {
		fakeAudio.fire('play');
		fakeAudio.ended = true;
		fakeAudio.fire('pause');
		expect(audioPlayer.status).toBe('playing');
	});

	it('waiting → buffering when playing', () => {
		fakeAudio.fire('play');
		fakeAudio.fire('waiting');
		expect(audioPlayer.status).toBe('buffering');
	});

	it('stalled → buffering when playing', () => {
		fakeAudio.fire('play');
		fakeAudio.fire('stalled');
		expect(audioPlayer.status).toBe('buffering');
	});

	it('playing event recovers from buffering', () => {
		fakeAudio.fire('play');
		fakeAudio.fire('waiting');
		fakeAudio.fire('playing');
		expect(audioPlayer.status).toBe('playing');
	});

	it('reloads and seeks back when playback remains stalled', () => {
		vi.useFakeTimers();
		audioPlayer.load(makeInfo(), { autoplay: false });
		fakeAudio.fire('play');
		fakeAudio.currentTime = 40;
		fakeAudio.fire('timeupdate');

		fakeAudio.fire('stalled');
		expect(audioPlayer.status).toBe('buffering');

		vi.advanceTimersByTime(5000);

		expect(audioPlayer.status).toBe('loading');
		expect(fakeAudio.src).toBe('/audio/a1/song_v1.mp3?recover=1');

		fakeAudio.fire('loadedmetadata');
		expect(fakeAudio.currentTime).toBe(39.25);

		fakeAudio.fire('canplay');
		expect(fakeAudio.playMock).toHaveBeenCalled();
	});

	it('cancels stalled recovery when playback progresses again', () => {
		vi.useFakeTimers();
		audioPlayer.load(makeInfo(), { autoplay: false });
		fakeAudio.fire('play');
		fakeAudio.currentTime = 40;
		fakeAudio.fire('timeupdate');
		fakeAudio.fire('waiting');

		fakeAudio.currentTime = 41;
		fakeAudio.fire('timeupdate');
		vi.advanceTimersByTime(5000);

		expect(fakeAudio.src).toBe('/audio/a1/song_v1.mp3');
		expect(audioPlayer.status).toBe('playing');
	});

	it('ended fires onEnded callback', () => {
		const onEnded = vi.fn();
		audioPlayer.swapCallbacks(callbacks({ onEnded }));
		fakeAudio.fire('ended');
		expect(onEnded).toHaveBeenCalled();
		expect(audioPlayer.status).toBe('idle');
		expect(audioPlayer.currentTime).toBe(0);
	});

	it('ended without onEnded does not throw', () => {
		audioPlayer.swapCallbacks(callbacks());
		expect(() => fakeAudio.fire('ended')).not.toThrow();
	});
});

describe('stream playback', () => {
	it('loads a queue stream at the requested track boundary', () => {
		const manifest = makeStreamManifest();
		audioPlayer.loadStream(manifest, 1, { autoplay: false });
		fakeAudio.fire('loadedmetadata');
		fakeAudio.fire('canplay');

		expect(audioPlayer.mode).toBe('stream');
		expect(fakeAudio.src).toBe('/api/queue-streams/snap/audio');
		expect(fakeAudio.currentTime).toBe(10);
		expect(audioPlayer.current?.songTitle).toBe('Second');
		expect(audioPlayer.duration).toBe(20);
	});

	it('maps absolute stream time to the active track time', () => {
		const manifest = makeStreamManifest();
		audioPlayer.loadStream(manifest, 0, { autoplay: false });

		fakeAudio.currentTime = 12.5;
		fakeAudio.fire('timeupdate');

		expect(audioPlayer.current?.songTitle).toBe('Second');
		expect(audioPlayer.currentTime).toBe(2.5);
		expect(audioPlayer.duration).toBe(20);
	});

	it('seeks next and previous tracks inside the stream', () => {
		audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });

		expect(audioPlayer.nextStreamTrack()).toBe(true);
		expect(fakeAudio.currentTime).toBe(10);
		expect(audioPlayer.current?.songTitle).toBe('Second');

		expect(audioPlayer.prevStreamTrack()).toBe(true);
		expect(fakeAudio.currentTime).toBe(0);
		expect(audioPlayer.current?.songTitle).toBe('First');
	});

	it('advances and resumes when the stream audio element ends', () => {
		audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });
		fakeAudio.fire('loadedmetadata');
		fakeAudio.fire('canplay');
		fakeAudio.fire('play');
		fakeAudio.playMock.mockClear();

		fakeAudio.fire('ended');

		expect(audioPlayer.current?.songTitle).toBe('Second');
		expect(fakeAudio.currentTime).toBe(10);
		expect(fakeAudio.playMock).toHaveBeenCalled();
	});

	it('ends a windowed stream once without wrapping the final track', () => {
		const onEnded = vi.fn();
		const onPlaybackStarted = vi.fn();
		audioPlayer.swapCallbacks(callbacks({ onEnded, onPlaybackStarted }));
		audioPlayer.loadStream({ ...makeStreamManifest(), windowed: true }, 1, { autoplay: false });

		fakeAudio.fire('ended');
		fakeAudio.fire('ended');

		expect(audioPlayer.current?.songTitle).toBe('Second');
		expect(audioPlayer.status).toBe('idle');
		expect(onEnded).toHaveBeenCalledTimes(1);
		expect(onEnded).toHaveBeenCalledWith('window-end');

		fakeAudio.fire('play');
		fakeAudio.fire('ended');
		expect(onPlaybackStarted).toHaveBeenCalledOnce();
		expect(onEnded).toHaveBeenCalledTimes(2);
	});

	it('keeps modulo navigation for a non-windowed stream', () => {
		audioPlayer.loadStream(makeStreamManifest(), 1, { autoplay: false });

		expect(audioPlayer.nextStreamTrack()).toBe(true);
		expect(audioPlayer.current?.songTitle).toBe('First');
	});

	it('resets the terminal end guard on destroy', () => {
		const onEnded = vi.fn();
		audioPlayer.swapCallbacks(callbacks({ onEnded }));
		audioPlayer.loadStream({ ...makeStreamManifest(), windowed: true }, 1, { autoplay: false });
		fakeAudio.fire('ended');

		audioPlayer.destroy();
		audioPlayer.loadStream({ ...makeStreamManifest(), windowed: true }, 1, { autoplay: false });
		fakeAudio.fire('ended');

		expect(onEnded).toHaveBeenCalledTimes(2);
	});

	it('starts at the clicked track once metadata arrives, not track one', () => {
		audioPlayer.loadStream(makeStreamManifest(), 1, { autoplay: false, restart: true });
		// Before metadata the element must NOT have consumed the start seek.
		fakeAudio.currentTime = 0;
		fakeAudio.fire('loadedmetadata');
		expect(fakeAudio.currentTime).toBe(10);
		expect(audioPlayer.current?.songTitle).toBe('Second');
	});

	it('recovers a stalled stream in place, never falling back to classic', async () => {
		vi.useFakeTimers();
		audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });
		fakeAudio.fire('play');
		fakeAudio.currentTime = 12;
		fakeAudio.fire('timeupdate');

		fakeAudio.fire('stalled');
		await vi.advanceTimersByTimeAsync(5000);
		await Promise.resolve();
		await Promise.resolve();

		expect(audioPlayer.mode).toBe('stream');
		expect(fakeAudio.src).toContain('recover=1');
		fakeAudio.fire('loadedmetadata');
		// Resumes just behind the stalled position (seek-back margin).
		expect(fakeAudio.currentTime).toBeCloseTo(12 - 0.75, 2);
	});

	it('rebuilds an expired stream snapshot and resumes at position', async () => {
		vi.useFakeTimers();
		fetchMock.mockResolvedValue({ ok: false, status: 404 });
		const fresh = makeStreamManifest();
		const onStreamRebuild = vi.fn().mockResolvedValue(fresh);
		audioPlayer.swapCallbacks(callbacks({ onStreamRebuild }));
		audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });
		fakeAudio.fire('play');
		fakeAudio.currentTime = 12;
		fakeAudio.fire('timeupdate');

		fakeAudio.fire('stalled');
		await vi.advanceTimersByTimeAsync(5000);
		await Promise.resolve();
		await Promise.resolve();
		await Promise.resolve();

		expect(onStreamRebuild).toHaveBeenCalledWith(
			expect.objectContaining({ trackIndex: 1, trackTime: 2 })
		);
		expect(audioPlayer.mode).toBe('stream');
		fakeAudio.fire('loadedmetadata');
		expect(fakeAudio.currentTime).toBe(12);
	});

	it('resumes the same generation after a rebuilt snapshot rotates order', async () => {
		vi.useFakeTimers();
		fetchMock.mockResolvedValue({ ok: false, status: 404 });
		const original = makeStreamManifest();
		const rotated: QueueStreamManifest = {
			...makeStreamManifest(),
			snapshot_id: 'snap-rotated',
			stream_url: '/api/queue-streams/snap-rotated/audio',
			tracks: [
				{
					...original.tracks[1],
					index: 0,
					start_offset: 0,
					end_offset: 20
				},
				{
					...original.tracks[0],
					index: 1,
					start_offset: 20,
					end_offset: 30
				}
			]
		};
		audioPlayer.swapCallbacks(callbacks({ onStreamRebuild: vi.fn().mockResolvedValue(rotated) }));
		audioPlayer.loadStream(original, 1, { autoplay: false });
		fakeAudio.fire('loadedmetadata');
		fakeAudio.fire('play');
		fakeAudio.currentTime = 12;
		fakeAudio.fire('timeupdate');

		fakeAudio.fire('stalled');
		await vi.advanceTimersByTimeAsync(5000);
		await Promise.resolve();
		await Promise.resolve();
		await Promise.resolve();

		expect(audioPlayer.current?.generation.id).toBe('g2');
		fakeAudio.fire('loadedmetadata');
		expect(fakeAudio.currentTime).toBe(2);
	});
});

describe('error handling', () => {
	beforeEach(() => {
		audioPlayer.load(makeInfo(), { autoplay: false });
	});

	it('error event transitions to error and probes URL', async () => {
		fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;
		fakeAudio.fire('error');
		await Promise.resolve();
		await Promise.resolve();
		expect(audioPlayer.status).toBe('error');
		expect(fetchMock).toHaveBeenCalledWith('/audio/a1/song_v1.mp3', {
			method: 'HEAD',
			credentials: 'include'
		});
	});

	it('recovers from a mid-track media error before probing URL', () => {
		audioPlayer.load(makeInfo(), { autoplay: false });
		fakeAudio.fire('play');
		fakeAudio.currentTime = 40;
		fakeAudio.fire('timeupdate');
		fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;

		fakeAudio.fire('error');

		expect(audioPlayer.status).toBe('loading');
		expect(fakeAudio.src).toBe('/audio/a1/song_v1.mp3?recover=1');
		expect(fetchMock).not.toHaveBeenCalled();

		fakeAudio.fire('loadedmetadata');
		expect(fakeAudio.currentTime).toBe(39.25);
	});

	it('falls back to normal error handling after recovery attempts are exhausted', async () => {
		audioPlayer.load(makeInfo(), { autoplay: false });
		fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;

		for (const attempt of [1, 2]) {
			fakeAudio.fire('play');
			fakeAudio.currentTime = 40 + attempt;
			fakeAudio.fire('timeupdate');
			fakeAudio.fire('error');
			expect(fakeAudio.src).toBe(`/audio/a1/song_v1.mp3?recover=${attempt}`);
			fakeAudio.fire('loadedmetadata');
		}

		fakeAudio.fire('play');
		fakeAudio.currentTime = 43;
		fakeAudio.fire('timeupdate');
		fakeAudio.fire('error');
		await new Promise((r) => setTimeout(r, 0));

		expect(audioPlayer.status).toBe('error');
		expect(fetchMock).toHaveBeenCalledWith('/audio/a1/song_v1.mp3', {
			method: 'HEAD',
			credentials: 'include'
		});
	});

	it('401 probe response triggers onAuthLost', async () => {
		fetchMock.mockResolvedValueOnce({ ok: false, status: 401 });
		const onAuthLost = vi.fn();
		audioPlayer.swapCallbacks(callbacks({ onAuthLost }));
		fakeAudio.fire('error');
		await new Promise((r) => setTimeout(r, 0));
		expect(onAuthLost).toHaveBeenCalled();
	});

	it('404 probe yields not-found error message', async () => {
		fetchMock.mockResolvedValueOnce({ ok: false, status: 404 });
		fakeAudio.fire('error');
		await new Promise((r) => setTimeout(r, 0));
		expect(audioPlayer.error).toMatch(/not found/i);
	});

	it('network failure (probe rejects) yields network error message', async () => {
		fetchMock.mockRejectedValueOnce(new Error('offline'));
		fakeAudio.fire('error');
		await new Promise((r) => setTimeout(r, 0));
		expect(audioPlayer.error).toMatch(/network/i);
	});

	it('decodes MEDIA_ERR_DECODE', async () => {
		fakeAudio.error = { code: MediaError.MEDIA_ERR_DECODE } as MediaError;
		fakeAudio.fire('error');
		await new Promise((r) => setTimeout(r, 0));
		expect(audioPlayer.error).toMatch(/corrupt/i);
	});

	it('decodes MEDIA_ERR_SRC_NOT_SUPPORTED', async () => {
		fakeAudio.error = { code: MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED } as MediaError;
		fakeAudio.fire('error');
		await new Promise((r) => setTimeout(r, 0));
		expect(audioPlayer.error).toMatch(/format/i);
	});

	it('decodes MEDIA_ERR_ABORTED', async () => {
		fakeAudio.error = { code: MediaError.MEDIA_ERR_ABORTED } as MediaError;
		fakeAudio.fire('error');
		await new Promise((r) => setTimeout(r, 0));
		expect(audioPlayer.error).toMatch(/aborted/i);
	});

	it('decodes MEDIA_ERR_NETWORK', async () => {
		fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;
		fakeAudio.fire('error');
		await new Promise((r) => setTimeout(r, 0));
		expect(audioPlayer.error).toMatch(/network/i);
	});

	it('unknown media error code falls back to generic message', async () => {
		fakeAudio.error = { code: 99 } as MediaError;
		fakeAudio.fire('error');
		await new Promise((r) => setTimeout(r, 0));
		expect(audioPlayer.error).toBeTruthy();
	});

	it('handleMediaError without current returns early', async () => {
		audioPlayer.destroy();
		await new Promise((r) => setTimeout(r, 0));
	});

	it('pause() leaves status at paused (no abort-as-error path)', () => {
		audioPlayer.pause();
		expect(audioPlayer.status).toBe('paused');
	});

	it('stale probe response does not overwrite state for newer load', async () => {
		let resolveProbe: ((value: Response) => void) | undefined;
		fetchMock.mockImplementationOnce(
			() =>
				new Promise<Response>((resolve) => {
					resolveProbe = resolve;
				})
		);
		fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;
		fakeAudio.fire('error');

		audioPlayer.load(makeInfo({ generation: makeGen({ id: 'g2', mp3_path: 'b.mp3' }) }));
		expect(audioPlayer.status).toBe('loading');

		resolveProbe?.({ ok: false, status: 404 } as Response);
		await new Promise((r) => setTimeout(r, 0));

		expect(audioPlayer.status).toBe('loading');
		expect(audioPlayer.error).toBeNull();
	});
});

describe('toggle / play / pause', () => {
	beforeEach(() => {
		audioPlayer.load(makeInfo(), { autoplay: false });
	});

	it('toggle from paused calls play', () => {
		fakeAudio.fire('canplay');
		fakeAudio.paused = true;
		audioPlayer.toggle();
		expect(fakeAudio.playMock).toHaveBeenCalled();
	});

	it('toggle from playing calls pause', () => {
		fakeAudio.fire('play');
		fakeAudio.paused = false;
		audioPlayer.toggle();
		expect(fakeAudio.paused).toBe(true);
	});

	it('toggle while loading queues play until canplay', () => {
		expect(audioPlayer.status).toBe('loading');
		audioPlayer.toggle();
		expect(fakeAudio.playMock).not.toHaveBeenCalled();
		fakeAudio.fire('canplay');
		expect(fakeAudio.playMock).toHaveBeenCalled();
	});

	it('second toggle while loading cancels queued play', () => {
		audioPlayer.toggle();
		audioPlayer.toggle();
		fakeAudio.fire('canplay');
		expect(fakeAudio.playMock).not.toHaveBeenCalled();
	});

	it('play while loading queues until canplay and does not throw', () => {
		expect(audioPlayer.status).toBe('loading');
		expect(() => audioPlayer.play()).not.toThrow();
		expect(fakeAudio.playMock).not.toHaveBeenCalled();
		fakeAudio.fire('canplay');
		expect(fakeAudio.playMock).toHaveBeenCalled();
	});

	it('play then pause while loading cancels queued play', () => {
		audioPlayer.play();
		audioPlayer.pause();
		fakeAudio.fire('canplay');
		expect(fakeAudio.playMock).not.toHaveBeenCalled();
	});

	it('repeated play while loading still queues', () => {
		audioPlayer.play();
		audioPlayer.play();
		fakeAudio.fire('canplay');
		expect(fakeAudio.playMock).toHaveBeenCalled();
	});

	it('play while buffering queues until canplay', () => {
		fakeAudio.fire('canplay');
		fakeAudio.fire('play');
		fakeAudio.playMock.mockClear();
		fakeAudio.fire('waiting');
		expect(audioPlayer.status).toBe('buffering');
		audioPlayer.play();
		expect(fakeAudio.playMock).not.toHaveBeenCalled();
		fakeAudio.fire('canplay');
		expect(fakeAudio.playMock).toHaveBeenCalled();
	});

	it('toggle in error state retries (via play→reload)', async () => {
		fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;
		fakeAudio.fire('error');
		await new Promise((r) => setTimeout(r, 0));
		const firstSrc = fakeAudio.src;
		audioPlayer.toggle();
		expect(fakeAudio.src).toBe(firstSrc);
		expect(audioPlayer.status).toBe('loading');
	});

	it('toggle with no current does nothing', () => {
		audioPlayer.destroy();
		expect(() => audioPlayer.toggle()).not.toThrow();
	});

	it('play with no current does nothing', () => {
		audioPlayer.destroy();
		expect(() => audioPlayer.play()).not.toThrow();
	});

	it('pause with no audio does nothing', () => {
		audioPlayer.destroy();
		expect(() => audioPlayer.pause()).not.toThrow();
	});

	it('NotAllowedError on autoplay sets paused with helpful error', async () => {
		fakeAudio.fire('canplay');
		fakeAudio.playMock.mockReset();
		fakeAudio.playMock.mockImplementation(() =>
			Promise.reject(Object.assign(new Error('autoplay blocked'), { name: 'NotAllowedError' }))
		);
		audioPlayer.play();
		await new Promise((r) => setTimeout(r, 0));
		expect(audioPlayer.status).toBe('paused');
		expect(audioPlayer.error).toMatch(/autoplay/i);
	});

	it('AbortError on play is silently ignored', async () => {
		fakeAudio.fire('canplay');
		fakeAudio.playMock.mockReset();
		fakeAudio.playMock.mockImplementation(() =>
			Promise.reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))
		);
		audioPlayer.play();
		await new Promise((r) => setTimeout(r, 0));
		expect(audioPlayer.status).not.toBe('error');
	});

	it('non-Error rejection on play falls through to media error path', async () => {
		fakeAudio.fire('canplay');
		fakeAudio.playMock.mockReset();
		fakeAudio.playMock.mockImplementation(() => Promise.reject('plain string'));
		audioPlayer.play();
		await new Promise((r) => setTimeout(r, 0));
		expect(audioPlayer.status).toBe('error');
	});
});

describe('seek()', () => {
	beforeEach(() => {
		audioPlayer.load(makeInfo(), { autoplay: false });
		fakeAudio.duration = 100;
		fakeAudio.fire('loadedmetadata');
	});

	it('seeks to clamped position', () => {
		audioPlayer.seek(50);
		expect(fakeAudio.currentTime).toBe(50);
	});

	it('clamps to 0 when negative', () => {
		audioPlayer.seek(-5);
		expect(fakeAudio.currentTime).toBe(0);
	});

	it('clamps to duration when over', () => {
		audioPlayer.seek(999);
		expect(fakeAudio.currentTime).toBe(100);
	});

	it('does nothing when duration is 0', () => {
		audioPlayer.destroy();
		audioPlayer.seek(10);
	});
});

describe('load() same gen with autoplay restarts play', () => {
	it('calls play() if same gen requested with autoplay while paused', () => {
		audioPlayer.load(makeInfo());
		fakeAudio.fire('canplay');
		fakeAudio.fire('play');
		fakeAudio.paused = true;
		fakeAudio.fire('pause');
		fakeAudio.playMock.mockClear();
		audioPlayer.load(makeInfo());
		expect(fakeAudio.playMock).toHaveBeenCalled();
	});

	it('skips play() if already playing', () => {
		audioPlayer.load(makeInfo());
		fakeAudio.fire('canplay');
		fakeAudio.fire('play');
		fakeAudio.paused = false;
		fakeAudio.playMock.mockClear();
		audioPlayer.load(makeInfo());
		expect(fakeAudio.playMock).not.toHaveBeenCalled();
	});
});

describe('canplay during error state', () => {
	it('does not transition out of error on stale canplay', async () => {
		audioPlayer.load(makeInfo(), { autoplay: false });
		fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;
		fakeAudio.fire('error');
		await new Promise((r) => setTimeout(r, 0));
		fakeAudio.fire('canplay');
		expect(audioPlayer.status).toBe('error');
	});
});

describe('destroy()', () => {
	it('resets state and detaches audio', () => {
		audioPlayer.load(makeInfo());
		audioPlayer.destroy();
		expect(audioPlayer.status).toBe('idle');
		expect(audioPlayer.current).toBeNull();
		expect(audioPlayer.getElement()).toBeNull();
	});

	it('is safe to call before any load', () => {
		expect(() => audioPlayer.destroy()).not.toThrow();
	});
});

describe('getElement()', () => {
	it('returns the underlying Audio element after load', () => {
		audioPlayer.load(makeInfo());
		expect(audioPlayer.getElement()).toBe(fakeAudio);
	});

	it('returns null before load', () => {
		expect(audioPlayer.getElement()).toBeNull();
	});
});

describe('loadUrl()', () => {
	it('loads the given URL directly instead of the /audio/ prefix', () => {
		const info = makeInfo();
		audioPlayer.loadUrl(info, '/shared/slug/audio/first.mp3');
		expect(audioPlayer.current?.songTitle).toBe('Song');
		expect(audioPlayer.status).toBe('loading');
		expect(fakeAudio.src).toBe('/shared/slug/audio/first.mp3');
	});

	it('does not reload when the same generation and URL are loaded again', () => {
		const info = makeInfo();
		audioPlayer.loadUrl(info, '/shared/slug/audio/first.mp3');
		fakeAudio.fire('canplay');
		fakeAudio.fire('play');
		const initialSrc = fakeAudio.src;
		audioPlayer.loadUrl(makeInfo({ generation: makeGen() }), '/shared/slug/audio/first.mp3');
		expect(fakeAudio.src).toBe(initialSrc);
	});

	it('reloads when the URL differs even for the same generation id', () => {
		audioPlayer.loadUrl(makeInfo(), '/shared/slug/audio/first.mp3');
		audioPlayer.loadUrl(makeInfo(), '/shared/other-slug/audio/first.mp3');
		expect(fakeAudio.src).toBe('/shared/other-slug/audio/first.mp3');
	});

	it('recovers a stalled classic load against the loadUrl URL, not /audio/', () => {
		vi.useFakeTimers();
		audioPlayer.loadUrl(makeInfo(), '/shared/slug/audio/first.mp3', { autoplay: false });
		fakeAudio.fire('play');
		fakeAudio.currentTime = 40;
		fakeAudio.fire('timeupdate');

		fakeAudio.fire('stalled');
		vi.advanceTimersByTime(5000);

		expect(fakeAudio.src).toBe('/shared/slug/audio/first.mp3?recover=1');
	});

	it('probes the loadUrl URL on a media error and never calls onAuthLost when none is installed', async () => {
		fetchMock.mockResolvedValueOnce({ ok: false, status: 401 });
		audioPlayer.loadUrl(makeInfo(), '/shared/slug/audio/first.mp3', { autoplay: false });
		fakeAudio.fire('error');
		await new Promise((r) => setTimeout(r, 0));

		expect(fetchMock).toHaveBeenCalledWith('/shared/slug/audio/first.mp3', {
			method: 'HEAD',
			credentials: 'include'
		});
		expect(audioPlayer.status).toBe('error');
	});
});

describe('unload()', () => {
	it('clears playback state but keeps the audio element for reuse', () => {
		audioPlayer.load(makeInfo());
		fakeAudio.fire('canplay');
		fakeAudio.fire('play');

		audioPlayer.unload();

		expect(audioPlayer.status).toBe('idle');
		expect(audioPlayer.current).toBeNull();
		expect(audioPlayer.currentTime).toBe(0);
		expect(audioPlayer.duration).toBe(0);
		expect(fakeAudio.src).toBe('');
		expect(audioPlayer.getElement()).toBe(fakeAudio);
	});

	it('is safe to call before any load', () => {
		expect(() => audioPlayer.unload()).not.toThrow();
	});

	it('a load after unload starts fresh rather than reusing stale sameGen state', () => {
		const info = makeInfo();
		audioPlayer.load(info);
		fakeAudio.fire('canplay');
		fakeAudio.fire('play');
		audioPlayer.unload();

		audioPlayer.load(info);

		expect(audioPlayer.status).toBe('loading');
		expect(fakeAudio.src).toBe('/audio/a1/song_v1.mp3');
	});
});

describe('swapCallbacks() / restoreCallbacks()', () => {
	beforeEach(() => {
		audioPlayer.load(makeInfo(), { autoplay: false });
	});

	it('returns the previous callback set and installs the new one', () => {
		const appOnEnded = vi.fn();
		const previous = audioPlayer.swapCallbacks(callbacks({ onEnded: appOnEnded }));
		expect(previous).toEqual(callbacks());

		const shareOnEnded = vi.fn();
		audioPlayer.swapCallbacks(callbacks({ onEnded: shareOnEnded }));
		fakeAudio.fire('ended');

		expect(shareOnEnded).toHaveBeenCalled();
		expect(appOnEnded).not.toHaveBeenCalled();
	});

	it('restoreCallbacks reinstates the exact previous set after a visiting owner is done', () => {
		const appOnEnded = vi.fn();
		audioPlayer.swapCallbacks(callbacks({ onEnded: appOnEnded }));

		const shareOnEnded = vi.fn();
		const appCallbacks = audioPlayer.swapCallbacks(callbacks({ onEnded: shareOnEnded }));
		audioPlayer.restoreCallbacks(appCallbacks);

		fakeAudio.fire('ended');

		expect(appOnEnded).toHaveBeenCalled();
		expect(shareOnEnded).not.toHaveBeenCalled();
	});
});
