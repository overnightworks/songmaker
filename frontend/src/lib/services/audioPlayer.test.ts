import { makeGeneration as makeGen } from '$lib/test-utils/factories';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { QueueStreamManifest } from '$lib/api/types';
import { audioPlayer, type AudioPlayerCallbacks, type PlaybackInfo } from './audioPlayer.svelte';

const NO_STRIP_SHOWN = (): boolean => false;
const SECOND = 1000;
const RECOVERY_DEADLINE = 2 * 60 * SECOND;
const STALLED = 'Playback stalled. Press Retry.';

function callbacks(overrides: Partial<AudioPlayerCallbacks> = {}): AudioPlayerCallbacks {
	return {
		onEnded: null,
		onPlaybackStarted: null,
		onAuthLost: null,
		onStreamRebuild: null,
		onCurrentChange: null,
		networkFailureIsAnnounced: NO_STRIP_SHOWN,
		...overrides
	};
}

function makeInfo(overrides: Partial<PlaybackInfo> = {}): PlaybackInfo {
	return {
		generation: makeGen({
			mp3_path: 'a1/song_v1.mp3',
			wav_path: 'a1/song_v1.wav',
			seed: 42,
			model_mode: 'sft',
			created_at: '2026-01-01T00:00:00Z'
		}),
		songId: 's1',
		songTitle: 'Song',
		artist: 'Artist',
		albumTitle: 'Album',
		lyrics: null,
		...overrides
	};
}

function takeInfo(id: string, mp3Path: string): PlaybackInfo {
	return makeInfo({ generation: makeGen({ id, mp3_path: mp3Path }) });
}

// A standby deck the browser has buffered far enough to play on at once.
function preloadReady(
	info: PlaybackInfo,
	readyState: number = HTMLMediaElement.HAVE_FUTURE_DATA
): FakeAudio {
	audioPlayer.preload(info);
	const standby = createdAudios[createdAudios.length - 1];
	standby.readyState = readyState;
	return standby;
}

function recoveryUrlOf(url: string): RegExp {
	const escaped = url.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	return new RegExp(`^${escaped}\\?recover=\\S+$`);
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
	seeking = false;
	ended = false;
	error: MediaError | null = null;
	crossOrigin: string | null = null;
	preload = '';
	readyState = 0;
	bufferedUntil = 0;
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
	get buffered(): Pick<TimeRanges, 'length' | 'end'> {
		const end = this.bufferedUntil;
		return { length: end > 0 ? 1 : 0, end: () => end };
	}
	restartClockAsLoadDoes(): void {
		this.currentTime = 0;
		this.fire('timeupdate');
	}
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
let createdAudios: FakeAudio[];

function activeDeck(): FakeAudio {
	return audioPlayer.getElement() as unknown as FakeAudio;
}
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
	fakeAudio = new FakeAudio();
	createdAudios = [];
	vi.stubGlobal(
		'Audio',
		vi.fn(function () {
			const el = createdAudios.length === 0 ? fakeAudio : new FakeAudio();
			createdAudios.push(el);
			return el;
		})
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
		audioPlayer.load(
			makeInfo({
				generation: makeGen({
					mp3_path: 'a1/song_v1.mp3',
					wav_path: 'a1/song_v1.wav',
					seed: 42,
					model_mode: 'sft',
					created_at: '2026-01-01T00:00:00Z'
				})
			})
		);
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
		audioPlayer.load(
			makeInfo({
				generation: makeGen({
					wav_path: 'a1/song_v1.wav',
					seed: 42,
					model_mode: 'sft',
					created_at: '2026-01-01T00:00:00Z',
					id: 'g2',
					mp3_path: 'b.mp3'
				})
			})
		);
		expect(fakeAudio.src).toBe('/audio/b.mp3');
	});

	it('publishes replacement takes while loading', () => {
		const statuses: Array<[string, string]> = [];
		audioPlayer.swapCallbacks(
			callbacks({
				onCurrentChange: (current) => {
					if (current) statuses.push([current.generation.id, audioPlayer.status]);
				}
			})
		);
		audioPlayer.load(makeInfo(), { autoplay: false });
		fakeAudio.fire('play');
		statuses.length = 0;

		audioPlayer.load(
			makeInfo({
				generation: makeGen({
					wav_path: 'a1/song_v1.wav',
					seed: 42,
					model_mode: 'sft',
					created_at: '2026-01-01T00:00:00Z',
					id: 'g2',
					mp3_path: 'b.mp3'
				})
			}),
			{
				autoplay: false
			}
		);

		expect(statuses).toEqual([['g2', 'loading']]);

		fakeAudio.fire('play');
		statuses.length = 0;
		audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });

		expect(statuses).toEqual([['g1', 'loading']]);
	});

	it('clears prior error state on new load', () => {
		audioPlayer.load(makeInfo());
		fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;
		fakeAudio.fire('error');
		expect(audioPlayer.status).toBe('error');
		audioPlayer.load(
			makeInfo({
				generation: makeGen({
					wav_path: 'a1/song_v1.wav',
					seed: 42,
					model_mode: 'sft',
					created_at: '2026-01-01T00:00:00Z',
					id: 'g2',
					mp3_path: 'b.mp3'
				})
			})
		);
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

	it('notifies playback started only after media starts playing', () => {
		const onPlaybackStarted = vi.fn();
		audioPlayer.swapCallbacks(callbacks({ onPlaybackStarted }));

		fakeAudio.fire('play');
		fakeAudio.fire('error');
		fakeAudio.fire('playing');

		expect(onPlaybackStarted).not.toHaveBeenCalled();
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
		expect(fakeAudio.src).toMatch(recoveryUrlOf('/audio/a1/song_v1.mp3'));

		fakeAudio.fire('loadedmetadata');
		expect(fakeAudio.currentTime).toBe(39.25);

		fakeAudio.fire('canplay');
		expect(fakeAudio.playMock).toHaveBeenCalled();
	});

	it('shows the reached position while the reload restarts the element clock, then seeks there', () => {
		vi.useFakeTimers();
		fakeAudio.fire('play');
		fakeAudio.currentTime = 40;
		fakeAudio.fire('timeupdate');
		fakeAudio.fire('stalled');
		vi.advanceTimersByTime(5000);

		fakeAudio.restartClockAsLoadDoes();
		expect(audioPlayer.currentTime).toBe(39.25);

		fakeAudio.fire('loadedmetadata');
		expect(fakeAudio.currentTime).toBe(39.25);
	});

	it('keeps the buffer of a slow download that still grows instead of reloading it from the start', () => {
		vi.useFakeTimers();
		fakeAudio.fire('play');
		fakeAudio.currentTime = 1.9;
		fakeAudio.bufferedUntil = 2;
		fakeAudio.fire('timeupdate');
		fakeAudio.fire('waiting');

		for (let tick = 0; tick < 3; tick += 1) {
			fakeAudio.bufferedUntil += 0.25;
			vi.advanceTimersByTime(5000);
		}
		expect({ src: fakeAudio.src, status: audioPlayer.status }).toEqual({
			src: '/audio/a1/song_v1.mp3',
			status: 'buffering'
		});

		vi.advanceTimersByTime(5000);
		expect(fakeAudio.src).toMatch(recoveryUrlOf('/audio/a1/song_v1.mp3'));
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

describe('frozen-clock watchdog', () => {
	function startPlayingAt(seconds: number): void {
		fakeAudio.currentTime = seconds;
		fakeAudio.paused = false;
		fakeAudio.fire('play');
		fakeAudio.fire('playing');
	}

	function advanceSeconds(count: number, clockStep = 0): void {
		for (let second = 0; second < count; second += 1) {
			fakeAudio.currentTime += clockStep;
			vi.advanceTimersByTime(SECOND);
		}
	}

	beforeEach(() => {
		vi.useFakeTimers();
		audioPlayer.load(makeInfo(), { autoplay: false });
	});

	it('reloads a take that reports playing while its clock stands still, after a few seconds', () => {
		startPlayingAt(40);

		advanceSeconds(1);
		expect(fakeAudio.src).toBe('/audio/a1/song_v1.mp3');

		advanceSeconds(4);
		expect(audioPlayer.status).toBe('loading');
		expect(fakeAudio.src).toMatch(recoveryUrlOf('/audio/a1/song_v1.mp3'));
		fakeAudio.fire('loadedmetadata');
		expect(fakeAudio.currentTime).toBe(39.25);
	});

	const playbackModes = [
		{ mode: 'a single take', loadMode: () => {} },
		{
			mode: 'a queue stream',
			loadMode: () => audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false })
		}
	];

	async function freezeAgainAndAgain(playOnSeconds: number, forSeconds: number): Promise<void> {
		startPlayingAt(40);
		for (let elapsed = 0; elapsed < forSeconds; elapsed += 5 + playOnSeconds) {
			advanceSeconds(5);
			await vi.advanceTimersByTimeAsync(0);
			if (audioPlayer.status === 'error') return;
			startPlayingAt(fakeAudio.currentTime);
			advanceSeconds(playOnSeconds, 1);
		}
		advanceSeconds(5);
		await vi.advanceTimersByTimeAsync(0);
	}

	it.each(
		playbackModes.flatMap(({ mode, loadMode }) => [
			{
				name: `recovers ${mode} by itself for as long as it plays on steadily between freezes`,
				loadMode,
				playOnSeconds: 10,
				afterThreeMinutes: { status: 'loading', error: null }
			},
			{
				name: `offers Retry once ${mode} has frozen again and again for two minutes, playing only briefly in between`,
				loadMode,
				playOnSeconds: 2,
				afterThreeMinutes: { status: 'error', error: STALLED }
			}
		])
	)('$name', async ({ loadMode, playOnSeconds, afterThreeMinutes }) => {
		loadMode();

		await freezeAgainAndAgain(playOnSeconds, 3 * 60);

		expect({ status: audioPlayer.status, error: audioPlayer.error }).toEqual(afterThreeMinutes);
	});

	it('gives a freeze after the listener paused a fresh two minutes', async () => {
		startPlayingAt(40);
		advanceSeconds(5);
		startPlayingAt(fakeAudio.currentTime);
		advanceSeconds(1, 1);
		audioPlayer.pause();
		advanceSeconds(3 * 60);

		startPlayingAt(fakeAudio.currentTime);
		advanceSeconds(5);

		expect({ status: audioPlayer.status, error: audioPlayer.error }).toEqual({
			status: 'loading',
			error: null
		});
	});

	async function freezeUntilTheDeadlinePasses(): Promise<void> {
		startPlayingAt(40);
		await vi.advanceTimersByTimeAsync(RECOVERY_DEADLINE + 10 * SECOND);
	}

	it.each(playbackModes)(
		'pauses $mode when it gives up, so the sound agrees with the stalled message',
		async ({ loadMode }) => {
			loadMode();
			await freezeUntilTheDeadlinePasses();

			expect({ status: audioPlayer.status, paused: fakeAudio.paused }).toEqual({
				status: 'error',
				paused: true
			});
		}
	);

	it.each(playbackModes)(
		'clears the stalled state when $mode plays on by itself after giving up',
		async ({ loadMode }) => {
			loadMode();
			await freezeUntilTheDeadlinePasses();

			startPlayingAt(fakeAudio.currentTime);

			expect({ status: audioPlayer.status, error: audioPlayer.error }).toEqual({
				status: 'playing',
				error: null
			});
		}
	);

	it.each([
		{ action: 'Retry', leaveGivenUpState: () => audioPlayer.play() },
		{
			action: 'loading another take',
			leaveGivenUpState: () =>
				audioPlayer.load(
					makeInfo({ generation: makeGen({ id: 'g2', mp3_path: 'a1/other.mp3' }) }),
					{ autoplay: false }
				)
		}
	])('leaves the stalled state behind after $action', async ({ leaveGivenUpState }) => {
		await freezeUntilTheDeadlinePasses();

		leaveGivenUpState();
		const afterLeaving = { status: audioPlayer.status, error: audioPlayer.error };
		startPlayingAt(fakeAudio.currentTime);

		expect({
			afterLeaving,
			afterPlaying: { status: audioPlayer.status, error: audioPlayer.error }
		}).toEqual({
			afterLeaving: { status: 'loading', error: null },
			afterPlaying: { status: 'playing', error: null }
		});
	});

	it.each(playbackModes)(
		'keeps reloading $mode when no reload answers, then offers Retry once two minutes have passed',
		async ({ loadMode }) => {
			loadMode();
			startPlayingAt(40);
			advanceSeconds(5);
			await vi.advanceTimersByTimeAsync(0);
			const firstReloadUrl = fakeAudio.src;

			await vi.advanceTimersByTimeAsync(RECOVERY_DEADLINE - 10 * SECOND);
			const beforeTheDeadline = {
				status: audioPlayer.status,
				retried: fakeAudio.src !== firstReloadUrl
			};
			await vi.advanceTimersByTimeAsync(10 * SECOND);

			expect({
				beforeTheDeadline,
				afterTheDeadline: {
					status: audioPlayer.status,
					error: audioPlayer.error,
					paused: fakeAudio.paused
				}
			}).toEqual({
				beforeTheDeadline: { status: 'loading', retried: true },
				afterTheDeadline: { status: 'error', error: STALLED, paused: true }
			});
		}
	);

	it('keeps waiting on a reload whose data still arrives', () => {
		startPlayingAt(40);
		advanceSeconds(5);
		const reloadUrl = fakeAudio.src;

		for (let tick = 0; tick < 4; tick += 1) {
			fakeAudio.bufferedUntil += 0.25;
			advanceSeconds(5);
		}

		expect({ status: audioPlayer.status, src: fakeAudio.src }).toEqual({
			status: 'loading',
			src: reloadUrl
		});
	});

	it('keeps the reached position when a second reload starts before the first seek landed', () => {
		startPlayingAt(40);
		advanceSeconds(5);
		fakeAudio.restartClockAsLoadDoes();

		advanceSeconds(5);
		fakeAudio.fire('loadedmetadata');

		expect(fakeAudio.currentTime).toBe(39.25);
	});

	it('asks for a new URL when the same take recovers again in a later load', () => {
		startPlayingAt(40);
		advanceSeconds(5);
		const firstRecoveryUrl = fakeAudio.src;

		audioPlayer.load(makeInfo(), { autoplay: false, restart: true });
		startPlayingAt(40);
		advanceSeconds(5);

		expect(fakeAudio.src).toMatch(recoveryUrlOf('/audio/a1/song_v1.mp3'));
		expect(fakeAudio.src).not.toBe(firstRecoveryUrl);
	});

	it('recovers a frozen stream in place', async () => {
		audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });
		startPlayingAt(5);

		await vi.advanceTimersByTimeAsync(5 * SECOND);

		expect(audioPlayer.mode).toBe('stream');
		expect(fakeAudio.src).toMatch(recoveryUrlOf('/api/queue-streams/snap/audio'));
	});

	it.each([
		{
			name: 'a user pause, then play',
			pressPlay: () => {
				audioPlayer.pause();
				audioPlayer.play();
			}
		},
		{ name: 'play while it still reports playing', pressPlay: () => audioPlayer.play() },
		{ name: 'tapping the same take again', pressPlay: () => audioPlayer.load(makeInfo()) }
	])('reloads a take whose clock stood still on $name', ({ pressPlay }) => {
		startPlayingAt(40);
		advanceSeconds(1);

		pressPlay();

		expect(audioPlayer.status).toBe('loading');
		expect(fakeAudio.src).toMatch(recoveryUrlOf('/audio/a1/song_v1.mp3'));
	});

	it.each([
		{
			name: 'a take whose clock advances',
			drive: () => {
				startPlayingAt(40);
				advanceSeconds(8, 1);
			}
		},
		{
			name: 'normal buffering that resumes',
			drive: () => {
				startPlayingAt(40);
				fakeAudio.fire('waiting');
				advanceSeconds(4);
				fakeAudio.fire('playing');
				advanceSeconds(4, 1);
			}
		},
		{
			name: 'a slow seek',
			drive: () => {
				startPlayingAt(40);
				fakeAudio.seeking = true;
				advanceSeconds(8);
			}
		},
		{
			name: 'a user pause',
			drive: () => {
				startPlayingAt(40);
				advanceSeconds(1, 1);
				audioPlayer.pause();
				advanceSeconds(8);
			}
		},
		{
			name: 'play after a healthy user pause',
			drive: () => {
				startPlayingAt(40);
				advanceSeconds(1, 1);
				audioPlayer.pause();
				advanceSeconds(8);
				audioPlayer.play();
			}
		}
	])('leaves $name alone', ({ drive }) => {
		drive();

		expect(fakeAudio.src).toBe('/audio/a1/song_v1.mp3');
		expect(audioPlayer.status).not.toBe('loading');
	});

	it.each([
		{ source: 'app', pauseIt: () => audioPlayer.pause() },
		{ source: 'outside', pauseIt: () => fakeAudio.pause() },
		{
			source: 'ended',
			pauseIt: () => {
				fakeAudio.ended = true;
				fakeAudio.pause();
			}
		}
	])('records a pause that came from the $source', ({ source, pauseIt }) => {
		const debug = vi.spyOn(console, 'debug').mockImplementation(() => {});
		startPlayingAt(40);

		pauseIt();

		expect(debug).toHaveBeenCalledWith('Audio paused', expect.objectContaining({ source }));
	});

	it('records a later pause from outside after a take change swallowed the app pause event', () => {
		const debug = vi.spyOn(console, 'debug').mockImplementation(() => {});
		startPlayingAt(40);
		vi.spyOn(fakeAudio, 'pause').mockImplementationOnce(() => {
			fakeAudio.paused = true;
		});

		audioPlayer.load(makeInfo({ generation: makeGen({ id: 'g2', mp3_path: 'a1/other.mp3' }) }));
		startPlayingAt(40);
		fakeAudio.pause();

		expect(debug).toHaveBeenLastCalledWith(
			'Audio paused',
			expect.objectContaining({ source: 'outside' })
		);
	});
});

describe('patient recovery while the screen is off', () => {
	const PROBE_TIMEOUT = 10 * SECOND;

	// The platform's AbortSignal.timeout runs on a clock fake timers never move.
	function abortAfterOnTheFakeClock(milliseconds: number): AbortSignal {
		const controller = new AbortController();
		setTimeout(() => controller.abort(new DOMException('timed out', 'TimeoutError')), milliseconds);
		return controller.signal;
	}

	function hangUntilAborted(_url: string, init: RequestInit): Promise<Response> {
		return new Promise((_resolve, reject) => {
			init.signal?.addEventListener('abort', () => reject(init.signal?.reason));
		});
	}

	function startPlayingAt(seconds: number): void {
		fakeAudio.currentTime = seconds;
		fakeAudio.paused = false;
		fakeAudio.fire('play');
		fakeAudio.fire('playing');
		fakeAudio.fire('timeupdate');
	}

	beforeEach(() => {
		vi.useFakeTimers();
		vi.spyOn(AbortSignal, 'timeout').mockImplementation(abortAfterOnTheFakeClock);
		vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
	});

	it('a HEAD probe that never answers gives up after its timeout', async () => {
		fetchMock.mockImplementation(hangUntilAborted);
		audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });
		startPlayingAt(12);
		fakeAudio.fire('stalled');

		await vi.advanceTimersByTimeAsync(5 * SECOND);
		const whileProbing = { status: audioPlayer.status, src: fakeAudio.src };
		await vi.advanceTimersByTimeAsync(PROBE_TIMEOUT);

		expect({ whileProbing, afterTheTimeout: fakeAudio.src }).toEqual({
			whileProbing: { status: 'loading', src: '/api/queue-streams/snap/audio' },
			afterTheTimeout: expect.stringMatching(recoveryUrlOf('/api/queue-streams/snap/audio'))
		});
	});

	const outages = [
		{ strip: 'the offline strip says so', announced: true },
		{ strip: 'nothing says so', announced: false }
	];

	let networkGone: boolean;

	function loseTheNetworkWhilePlayingAt(seconds: number, announced: boolean): void {
		networkGone = false;
		audioPlayer.swapCallbacks(
			callbacks({ networkFailureIsAnnounced: () => announced && networkGone })
		);
		audioPlayer.load(makeInfo(), { autoplay: false });
		startPlayingAt(seconds);
		networkGone = true;
		fakeAudio.fire('waiting');
	}

	async function bringTheNetworkBack(announced: boolean): Promise<void> {
		networkGone = false;
		if (announced) audioPlayer.resumeAfterNetworkReturn();
		else await vi.advanceTimersByTimeAsync(5 * SECOND);
		fakeAudio.fire('loadedmetadata');
		fakeAudio.fire('canplay');
		await vi.advanceTimersByTimeAsync(0);
	}

	it.each(outages)(
		'a 60 s outage while hidden resumes without a tap, when $strip',
		async ({ announced }) => {
			loseTheNetworkWhilePlayingAt(40, announced);

			await vi.advanceTimersByTimeAsync(60 * SECOND);
			await bringTheNetworkBack(announced);

			expect({
				status: audioPlayer.status,
				error: audioPlayer.error,
				position: fakeAudio.currentTime,
				played: fakeAudio.playMock.mock.calls.length > 0
			}).toEqual({ status: 'playing', error: null, position: 39.25, played: true });
		}
	);

	it('spends no reload while the offline strip says the network is gone', async () => {
		loseTheNetworkWhilePlayingAt(40, true);

		await vi.advanceTimersByTimeAsync(60 * SECOND);

		expect({ status: audioPlayer.status, src: fakeAudio.src }).toEqual({
			status: 'buffering',
			src: '/audio/a1/song_v1.mp3'
		});
	});

	it.each(outages)(
		'a 3-minute outage lands in the given-up state, when $strip',
		async ({ announced }) => {
			loseTheNetworkWhilePlayingAt(40, announced);

			await vi.advanceTimersByTimeAsync(RECOVERY_DEADLINE - 10 * SECOND);
			const givenUpBeforeTheDeadline = audioPlayer.status === 'error';
			await vi.advanceTimersByTimeAsync(3 * 60 * SECOND - RECOVERY_DEADLINE + 10 * SECOND);

			expect({
				givenUpBeforeTheDeadline,
				status: audioPlayer.status,
				error: audioPlayer.error
			}).toEqual({ givenUpBeforeTheDeadline: false, status: 'error', error: STALLED });
		}
	);

	it.each(outages)(
		'the player never pauses itself while waiting, when $strip',
		async ({ announced }) => {
			loseTheNetworkWhilePlayingAt(40, announced);
			const pause = vi.spyOn(fakeAudio, 'pause');

			await vi.advanceTimersByTimeAsync(100 * SECOND);
			await bringTheNetworkBack(announced);

			expect(pause).not.toHaveBeenCalled();
		}
	);

	it('a first-byte hang reaches stalled after the deadline', async () => {
		audioPlayer.load(makeInfo());

		await vi.advanceTimersByTimeAsync(60 * SECOND);
		const aMinuteIn = { status: audioPlayer.status, error: audioPlayer.error };
		await vi.advanceTimersByTimeAsync(RECOVERY_DEADLINE);

		expect({
			aMinuteIn,
			afterTheDeadline: { status: audioPlayer.status, error: audioPlayer.error }
		}).toEqual({
			aMinuteIn: { status: 'loading', error: null },
			afterTheDeadline: { status: 'error', error: STALLED }
		});
	});

	it('a take playing again after a late answer gets the full wait at its next stall', async () => {
		audioPlayer.load(makeInfo());
		await vi.advanceTimersByTimeAsync(3 * 60 * SECOND);
		fakeAudio.fire('loadedmetadata');
		fakeAudio.fire('canplay');
		audioPlayer.play();
		startPlayingAt(12);
		fakeAudio.fire('waiting');

		await vi.advanceTimersByTimeAsync(60 * SECOND);

		expect({ status: audioPlayer.status, error: audioPlayer.error }).toEqual({
			status: 'loading',
			error: null
		});
	});

	it('a late answer clears stalled', async () => {
		audioPlayer.load(makeInfo());
		await vi.advanceTimersByTimeAsync(3 * 60 * SECOND);
		const beforeTheAnswer = audioPlayer.error;

		fakeAudio.fire('loadedmetadata');
		fakeAudio.fire('canplay');

		expect({
			beforeTheAnswer,
			afterIt: { status: audioPlayer.status, error: audioPlayer.error }
		}).toEqual({ beforeTheAnswer: STALLED, afterIt: { status: 'ready', error: null } });
	});
});

describe('stream playback', () => {
	it('leaves the current playback alone when an empty stream has no start track', () => {
		audioPlayer.load(makeInfo(), { autoplay: false });
		const current = audioPlayer.current;

		audioPlayer.loadStream({ ...makeStreamManifest(), tracks: [] }, 0, { autoplay: false });

		expect(audioPlayer.mode).toBe('classic');
		expect(audioPlayer.current).toBe(current);
	});

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

	it('keeps a stream paused when its caller disables autoplay', () => {
		audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });
		fakeAudio.fire('canplay');

		expect(fakeAudio.playMock).not.toHaveBeenCalled();
		expect(audioPlayer.status).toBe('ready');
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

	it('notifies the owner when a running stream crosses into another track', () => {
		const onCurrentChange = vi.fn();
		audioPlayer.swapCallbacks(callbacks({ onCurrentChange }));
		audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });
		fakeAudio.fire('play');
		onCurrentChange.mockClear();

		fakeAudio.currentTime = 12.5;
		fakeAudio.fire('timeupdate');

		expect(onCurrentChange).toHaveBeenCalledOnce();
		expect(onCurrentChange).toHaveBeenCalledWith(
			expect.objectContaining({ generation: expect.objectContaining({ id: 'g2' }) })
		);
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

	it.each([
		['before an audio element exists', () => audioPlayer.destroy()],
		['while classic playback is active', () => audioPlayer.load(makeInfo(), { autoplay: false })]
	])('rejects stream navigation %s', (_caseName, prepare) => {
		prepare();

		expect(audioPlayer.seekToStreamTrack(0)).toBe(false);
		expect(audioPlayer.nextStreamTrack()).toBe(false);
		expect(audioPlayer.prevStreamTrack()).toBe(false);
	});

	it('does not move to an invalid stream track', () => {
		audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });

		expect(audioPlayer.seekToStreamTrack(99)).toBe(false);
		expect(audioPlayer.current?.generation.id).toBe('g1');
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
		fakeAudio.fire('playing');
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
		activeDeck().fire('ended');

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
		expect(fakeAudio.src).toMatch(recoveryUrlOf('/api/queue-streams/snap/audio'));
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

	it('surfaces a missing-stream error when its snapshot cannot be rebuilt', async () => {
		vi.useFakeTimers();
		fetchMock.mockResolvedValue({ ok: false, status: 404 });
		const onStreamRebuild = vi.fn().mockResolvedValue(null);
		audioPlayer.swapCallbacks(callbacks({ onStreamRebuild }));
		audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });
		fakeAudio.fire('play');
		fakeAudio.currentTime = 12;
		fakeAudio.fire('timeupdate');

		fakeAudio.fire('stalled');
		await vi.advanceTimersByTimeAsync(5000);
		await Promise.resolve();

		expect(onStreamRebuild).toHaveBeenCalledOnce();
		expect(audioPlayer.mode).toBe('stream');
		expect(audioPlayer.status).toBe('error');
		expect(audioPlayer.error).toMatch(/not found/i);
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
		expect(fetchMock).toHaveBeenCalledWith(
			'/audio/a1/song_v1.mp3',
			expect.objectContaining({ method: 'HEAD', credentials: 'include' })
		);
	});

	function failPartWayThrough(): void {
		fakeAudio.fire('play');
		fakeAudio.currentTime = 40;
		fakeAudio.fire('timeupdate');
		fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;
		fakeAudio.fire('error');
	}

	it('reloads a take the server still serves after a mid-track media error', async () => {
		failPartWayThrough();
		await new Promise((r) => setTimeout(r, 0));

		expect(audioPlayer.status).toBe('loading');
		expect(fakeAudio.src).toMatch(recoveryUrlOf('/audio/a1/song_v1.mp3'));
		expect(fetchMock).toHaveBeenCalledWith(
			'/audio/a1/song_v1.mp3',
			expect.objectContaining({ method: 'HEAD', credentials: 'include' })
		);

		fakeAudio.fire('loadedmetadata');
		expect(fakeAudio.currentTime).toBe(39.25);
	});

	it.each([
		{
			interruption: 'the listener pauses',
			interrupt: () => audioPlayer.pause(),
			status: 'paused'
		},
		{
			interruption: 'a Play press fails',
			interrupt: () => {
				fakeAudio.playMock.mockImplementationOnce(() => Promise.reject('plain string'));
				audioPlayer.play();
			},
			status: 'error'
		}
	])(
		'keeps the take $status when $interruption while the mid-track probe is out',
		async ({ interrupt, status }) => {
			let answerProbe: (answer: { ok: boolean; status: number }) => void = () => {};
			fetchMock.mockReturnValueOnce(new Promise((resolve) => (answerProbe = resolve)));

			failPartWayThrough();
			interrupt();
			await new Promise((r) => setTimeout(r, 0));
			answerProbe({ ok: true, status: 200 });
			await new Promise((r) => setTimeout(r, 0));

			expect({ status: audioPlayer.status, src: fakeAudio.src }).toEqual({
				status,
				src: '/audio/a1/song_v1.mp3'
			});
		}
	);

	it.each([
		{ answer: 401, outcome: { signInAsked: true, error: 'Playback failed. Press Retry.' } },
		{ answer: 404, outcome: { signInAsked: false, error: 'Audio file not found.' } }
	])(
		'names a $answer answer to a mid-track media error at once instead of reloading',
		async ({ answer, outcome }) => {
			vi.useFakeTimers();
			fetchMock.mockResolvedValue({ ok: false, status: answer });
			const onAuthLost = vi.fn();
			audioPlayer.swapCallbacks(callbacks({ onAuthLost }));

			failPartWayThrough();
			await vi.advanceTimersByTimeAsync(5 * SECOND);

			expect({
				signInAsked: onAuthLost.mock.calls.length > 0,
				status: audioPlayer.status,
				error: audioPlayer.error,
				src: fakeAudio.src
			}).toEqual({ ...outcome, status: 'error', src: '/audio/a1/song_v1.mp3' });
		}
	);

	it('answers failed reloads one look at a time and gives up after two minutes', async () => {
		vi.useFakeTimers();
		fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;
		fakeAudio.fire('play');
		fakeAudio.currentTime = 41;
		fakeAudio.fire('timeupdate');
		fakeAudio.fire('error');
		await vi.advanceTimersByTimeAsync(0);
		const firstReloadUrl = fakeAudio.src;

		fakeAudio.fire('error');
		await vi.advanceTimersByTimeAsync(0);
		const afterItsOwnError = fakeAudio.src;
		for (let look = 0; look < 30; look += 1) {
			await vi.advanceTimersByTimeAsync(5 * SECOND);
			fakeAudio.fire('error');
		}
		await vi.advanceTimersByTimeAsync(0);

		expect({
			firstReloadUrl,
			afterItsOwnError,
			afterTwoAndAHalfMinutes: { status: audioPlayer.status, error: audioPlayer.error }
		}).toEqual({
			firstReloadUrl: expect.stringMatching(recoveryUrlOf('/audio/a1/song_v1.mp3')),
			afterItsOwnError: firstReloadUrl,
			afterTwoAndAHalfMinutes: { status: 'error', error: STALLED }
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

	it.each([
		{
			loss: 'the probe finding no network',
			arrange: () => fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))
		},
		{
			loss: 'the element reporting a network error',
			arrange: () => {
				fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;
			}
		}
	])(
		'adds no text of its own after $loss when the owner strip already says it',
		async ({ arrange }) => {
			audioPlayer.swapCallbacks(callbacks({ networkFailureIsAnnounced: () => true }));
			arrange();
			fakeAudio.fire('error');
			await new Promise((r) => setTimeout(r, 0));
			expect(audioPlayer.status).toBe('error');
			expect(audioPlayer.error).toBeNull();
		}
	);

	describe('once the network is back', () => {
		async function loseNetworkAtTheStart(announced: boolean): Promise<void> {
			audioPlayer.swapCallbacks(callbacks({ networkFailureIsAnnounced: () => announced }));
			fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;
			fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
			fakeAudio.fire('error');
			await new Promise((r) => setTimeout(r, 0));
		}

		it('plays a take whose start failed only because the network was gone', async () => {
			await loseNetworkAtTheStart(true);
			fakeAudio.error = null;
			fakeAudio.playMock.mockClear();

			audioPlayer.resumeAfterNetworkReturn();

			expect(audioPlayer.status).toBe('loading');
			expect(audioPlayer.error).toBeNull();
			expect(fakeAudio.src).toMatch(recoveryUrlOf('/audio/a1/song_v1.mp3'));
			fakeAudio.fire('loadedmetadata');
			fakeAudio.fire('canplay');
			expect(fakeAudio.playMock).toHaveBeenCalled();
		});

		it('keeps a real playback failure with its words and its Retry', async () => {
			await loseNetworkAtTheStart(false);
			audioPlayer.resumeAfterNetworkReturn();
			expect(audioPlayer.status).toBe('error');
			expect(audioPlayer.error).toBe('Playback failed. Press Retry.');
		});
	});

	it('names a failure no strip explains and offers the Retry', async () => {
		fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));
		fakeAudio.fire('error');
		await new Promise((r) => setTimeout(r, 0));
		expect(audioPlayer.status).toBe('error');
		expect(audioPlayer.error).toBe('Playback failed. Press Retry.');
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

	it('unknown media error code falls back to generic message', async () => {
		fakeAudio.error = { code: 99 } as MediaError;
		fakeAudio.fire('error');
		await new Promise((r) => setTimeout(r, 0));
		expect(audioPlayer.error).toBeTruthy();
	});

	it('handleMediaError without current returns early', async () => {
		audioPlayer.destroy();
		await new Promise((r) => setTimeout(r, 0));
		expect(audioPlayer.error).toBeNull();
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

		audioPlayer.load(
			makeInfo({
				generation: makeGen({
					wav_path: 'a1/song_v1.wav',
					seed: 42,
					model_mode: 'sft',
					created_at: '2026-01-01T00:00:00Z',
					id: 'g2',
					mp3_path: 'b.mp3'
				})
			})
		);
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

	it('toggle in error state fetches the take again past the browser cache', async () => {
		fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;
		fakeAudio.fire('error');
		await new Promise((r) => setTimeout(r, 0));
		expect(audioPlayer.status).toBe('error');
		fakeAudio.currentTime = 40;
		audioPlayer.toggle();
		expect(fakeAudio.src).toMatch(recoveryUrlOf('/audio/a1/song_v1.mp3'));
		expect(audioPlayer.status).toBe('loading');
		fakeAudio.fire('loadedmetadata');
		expect(fakeAudio.currentTime).toBe(39.25);
	});

	it('retries a failed stream in stream mode', async () => {
		audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });
		audioPlayer.status = 'error';

		audioPlayer.play();
		await vi.waitFor(() =>
			expect(fakeAudio.src).toMatch(recoveryUrlOf('/api/queue-streams/snap/audio'))
		);

		expect(audioPlayer.mode).toBe('stream');
		expect(audioPlayer.status).toBe('loading');
		expect(fakeAudio.src).toMatch(recoveryUrlOf('/api/queue-streams/snap/audio'));
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

	it.each([
		[
			'an error',
			() => {
				audioPlayer.status = 'error';
			}
		],
		[
			'an ended track',
			() => {
				audioPlayer.status = 'playing';
				fakeAudio.ended = true;
			}
		]
	])('keeps the status when pausing after %s', (_caseName, arrange) => {
		arrange();
		const status = audioPlayer.status;

		audioPlayer.pause();

		expect(audioPlayer.status).toBe(status);
	});

	it('NotAllowedError on autoplay pauses and asks for Play, on a phone too', async () => {
		fakeAudio.fire('canplay');
		fakeAudio.playMock.mockReset();
		fakeAudio.playMock.mockImplementation(() =>
			Promise.reject(Object.assign(new Error('autoplay blocked'), { name: 'NotAllowedError' }))
		);
		audioPlayer.play();
		await new Promise((r) => setTimeout(r, 0));
		expect(audioPlayer.status).toBe('paused');
		expect(audioPlayer.error).toBe('Autoplay blocked. Press Play to start.');
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
		expect(fakeAudio.currentTime).toBe(0);
	});

	it('seeks within the active stream track', () => {
		audioPlayer.loadStream(makeStreamManifest(), 1, { autoplay: false });

		audioPlayer.seek(5);

		expect(fakeAudio.currentTime).toBe(15);
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

describe('stale events during a media error', () => {
	it.each(['canplay', 'playing'])(
		'does not transition out of the error on a stale %s',
		async (event) => {
			audioPlayer.load(makeInfo(), { autoplay: false });
			fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;
			fakeAudio.fire('error');
			await new Promise((r) => setTimeout(r, 0));
			fakeAudio.fire(event);
			expect(audioPlayer.status).toBe('error');
		}
	);
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
		audioPlayer.loadUrl(
			makeInfo({
				generation: makeGen({
					mp3_path: 'a1/song_v1.mp3',
					wav_path: 'a1/song_v1.wav',
					seed: 42,
					model_mode: 'sft',
					created_at: '2026-01-01T00:00:00Z'
				})
			}),
			'/shared/slug/audio/first.mp3'
		);
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

		expect(fakeAudio.src).toMatch(recoveryUrlOf('/shared/slug/audio/first.mp3'));
	});

	it("probes the loadUrl URL on a media error and never calls a previous owner's onAuthLost after swapping in null", async () => {
		fetchMock.mockResolvedValueOnce({ ok: false, status: 401 });
		const appOnAuthLost = vi.fn();
		audioPlayer.swapCallbacks(callbacks({ onAuthLost: appOnAuthLost }));
		audioPlayer.swapCallbacks(callbacks({ onAuthLost: null }));

		audioPlayer.loadUrl(makeInfo(), '/shared/slug/audio/first.mp3', { autoplay: false });
		fakeAudio.fire('error');
		await new Promise((r) => setTimeout(r, 0));

		expect(fetchMock).toHaveBeenCalledWith(
			'/shared/slug/audio/first.mp3',
			expect.objectContaining({ method: 'HEAD', credentials: 'include' })
		);
		expect(audioPlayer.status).toBe('error');
		expect(appOnAuthLost).not.toHaveBeenCalled();
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

	it('ignores an error event that fires after unload clearing the src', () => {
		audioPlayer.load(makeInfo());
		fakeAudio.fire('canplay');
		fakeAudio.fire('play');

		audioPlayer.unload();
		fakeAudio.fire('error');

		expect(audioPlayer.status).toBe('idle');
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

describe('standby deck', () => {
	const first = takeInfo('g1', 'a1/first.mp3');
	const next = takeInfo('g2', 'a1/next.mp3');
	const other = takeInfo('g3', 'a1/other.mp3');

	function playFirst(): void {
		audioPlayer.load(first);
		fakeAudio.fire('canplay');
		fakeAudio.fire('play');
		fakeAudio.fire('playing');
	}

	it('a preloaded next take starts on load without loading its source again', async () => {
		playFirst();
		const standby = preloadReady(next);
		const loadSpy = vi.spyOn(standby, 'load');

		audioPlayer.load(next);
		await Promise.resolve();

		expect(audioPlayer.getElement()).toBe(standby);
		expect(loadSpy).not.toHaveBeenCalled();
		expect(standby.src).toBe('/audio/a1/next.mp3');
		expect(standby.playMock).toHaveBeenCalledOnce();
		expect(audioPlayer.current?.generation.id).toBe('g2');
		expect(audioPlayer.status).toBe('playing');
		expect(fakeAudio.paused).toBe(true);
		expect(fakeAudio.src).toBe('');
	});

	it('a promoted take starts at the asked position and stays paused when asked', () => {
		playFirst();
		const standby = preloadReady(next);

		audioPlayer.load(next, { autoplay: false, startAt: 30 });

		expect(standby.currentTime).toBe(30);
		expect(audioPlayer.currentTime).toBe(30);
		expect(standby.playMock).not.toHaveBeenCalled();
		expect(audioPlayer.status).toBe('ready');
	});

	it('a load whose URL differs from the preloaded one loads normally and drops the preload', () => {
		playFirst();
		const standby = preloadReady(next);

		audioPlayer.load(other);

		expect(audioPlayer.getElement()).toBe(fakeAudio);
		expect(fakeAudio.src).toBe('/audio/a1/other.mp3');
		expect(audioPlayer.status).toBe('loading');
		expect(standby.src).toBe('');

		audioPlayer.load(next);

		expect(audioPlayer.getElement()).toBe(fakeAudio);
		expect(fakeAudio.src).toBe('/audio/a1/next.mp3');
	});

	it('a preloaded take without future data loads normally on the active deck', () => {
		playFirst();
		const standby = preloadReady(next, HTMLMediaElement.HAVE_CURRENT_DATA);

		audioPlayer.load(next);

		expect(audioPlayer.getElement()).toBe(fakeAudio);
		expect(fakeAudio.src).toBe('/audio/a1/next.mp3');
		expect(audioPlayer.status).toBe('loading');
		expect(standby.src).toBe('');
	});

	it('preloading the take already standing by does not fetch it again', () => {
		const standby = preloadReady(next);
		const loadSpy = vi.spyOn(standby, 'load');

		audioPlayer.preload(next);

		expect(loadSpy).not.toHaveBeenCalled();
	});

	it('a newer preload replaces the older one and null drops it', () => {
		playFirst();
		const standby = preloadReady(next);

		audioPlayer.preload(other);
		expect(standby.src).toBe('/audio/a1/other.mp3');

		audioPlayer.preload(null);
		expect(standby.src).toBe('');
		audioPlayer.load(other);
		expect(audioPlayer.getElement()).toBe(fakeAudio);
	});

	it('events from the standby never change status, error or current', async () => {
		const onEnded = vi.fn();
		const onPlaybackStarted = vi.fn();
		audioPlayer.swapCallbacks(callbacks({ onEnded, onPlaybackStarted }));
		playFirst();
		onPlaybackStarted.mockClear();
		const standby = preloadReady(next);
		standby.error = { code: MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED } as MediaError;

		for (const event of [
			'loadstart',
			'loadedmetadata',
			'canplay',
			'timeupdate',
			'play',
			'playing',
			'pause',
			'waiting',
			'stalled',
			'ended',
			'error'
		]) {
			standby.fire(event);
		}
		await new Promise((r) => setTimeout(r, 0));

		expect(audioPlayer.status).toBe('playing');
		expect(audioPlayer.error).toBeNull();
		expect(audioPlayer.current?.generation.id).toBe('g1');
		expect(onEnded).not.toHaveBeenCalled();
		expect(onPlaybackStarted).not.toHaveBeenCalled();
		expect(fetchMock).not.toHaveBeenCalled();
	});

	it('a failed preload leaves the active take playing and the next load works normally', async () => {
		playFirst();
		audioPlayer.preload(next);
		const standby = createdAudios[1];
		standby.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;
		standby.fire('error');
		await new Promise((r) => setTimeout(r, 0));

		expect(audioPlayer.status).toBe('playing');
		expect(audioPlayer.error).toBeNull();

		audioPlayer.load(next);
		fakeAudio.fire('canplay');

		expect(audioPlayer.getElement()).toBe(fakeAudio);
		expect(fakeAudio.src).toBe('/audio/a1/next.mp3');
		expect(audioPlayer.current?.generation.id).toBe('g2');
		expect(fakeAudio.playMock).toHaveBeenCalledTimes(2);
	});

	it('events from the deck a promotion retired never reach the player', () => {
		playFirst();
		preloadReady(next);
		audioPlayer.load(next);

		fakeAudio.fire('error');
		fakeAudio.fire('loadstart');

		expect(audioPlayer.status).not.toBe('error');
		expect(audioPlayer.status).not.toBe('loading');
		expect(audioPlayer.current?.generation.id).toBe('g2');
	});

	it.each(['unload', 'destroy'] as const)('%s clears the standby', (teardown) => {
		playFirst();
		const standby = preloadReady(next);

		audioPlayer[teardown]();
		audioPlayer.load(next);

		expect(standby.src).toBe('');
		expect(audioPlayer.getElement()).not.toBe(standby);
		expect(audioPlayer.status).toBe('loading');
	});
});

// The <audio> element can be handed to createMediaElementSource exactly once,
// and closing the context that owns that source silences the element for good
// — so the graph has to belong to the player, not to a transport bar the app
// unmounts whenever the full Now Playing surface takes over (issue #140).
describe('audio graph', () => {
	function fakeAudioContext() {
		const analyser = {
			fftSize: 2048,
			smoothingTimeConstant: 0,
			frequencyBinCount: 1024,
			connect: vi.fn()
		};
		const context = {
			state: 'running',
			destination: {},
			createAnalyser: vi.fn(() => analyser),
			createMediaElementSource: vi.fn((_el: unknown) => ({ connect: vi.fn() })),
			resume: vi.fn(),
			close: vi.fn()
		};
		return {
			context,
			analyser,
			constructor: vi.fn(function () {
				return context;
			})
		};
	}

	it('hands out one analyser for the element, however often it is asked', () => {
		const fake = fakeAudioContext();
		vi.stubGlobal('AudioContext', fake.constructor);
		audioPlayer.load(makeInfo(), { autoplay: false });

		const first = audioPlayer.getAnalyser();
		const second = audioPlayer.getAnalyser();

		expect(first).toBe(second);
		expect(fake.constructor).toHaveBeenCalledOnce();
		expect(fake.context.createMediaElementSource).toHaveBeenCalledOnce();
	});

	it('keeps the graph alive across everything but destroy', () => {
		const fake = fakeAudioContext();
		vi.stubGlobal('AudioContext', fake.constructor);
		audioPlayer.load(makeInfo(), { autoplay: false });
		audioPlayer.getAnalyser();

		audioPlayer.load(
			makeInfo({
				generation: makeGen({
					mp3_path: 'a1/song_v1.mp3',
					wav_path: 'a1/song_v1.wav',
					seed: 42,
					model_mode: 'sft',
					created_at: '2026-01-01T00:00:00Z',
					id: 'g2'
				})
			}),
			{
				autoplay: false
			}
		);
		audioPlayer.pause();

		expect(fake.context.close).not.toHaveBeenCalled();

		audioPlayer.destroy();

		expect(fake.context.close).toHaveBeenCalledOnce();
	});

	it.each([
		{
			order: 'analyser before preload',
			arrange: () => {
				const analyser = audioPlayer.getAnalyser();
				preloadReady(takeInfo('g2', 'a1/next.mp3'));
				return analyser;
			}
		},
		{
			order: 'preload before analyser',
			arrange: () => {
				preloadReady(takeInfo('g2', 'a1/next.mp3'));
				return audioPlayer.getAnalyser();
			}
		}
	])("the analyser carries the promoted deck's sound ($order)", ({ arrange }) => {
		const fake = fakeAudioContext();
		vi.stubGlobal('AudioContext', fake.constructor);
		audioPlayer.load(takeInfo('g1', 'a1/first.mp3'));
		const analyser = arrange();

		audioPlayer.load(takeInfo('g2', 'a1/next.mp3'));

		const sourceOf = fake.context.createMediaElementSource;
		const promotedIndex = sourceOf.mock.calls.findIndex(([el]) => el === audioPlayer.getElement());
		expect(promotedIndex).toBeGreaterThan(-1);
		expect(sourceOf.mock.results[promotedIndex].value.connect).toHaveBeenCalledWith(analyser);
		expect(audioPlayer.getAnalyser()).toBe(analyser);
		expect(fake.constructor).toHaveBeenCalledOnce();
	});

	it('builds no graph where the browser offers no Web Audio', () => {
		vi.stubGlobal('AudioContext', undefined);
		audioPlayer.load(makeInfo(), { autoplay: false });

		expect(audioPlayer.getAnalyser()).toBeNull();
	});

	it('leaves no half-built graph behind when the browser refuses the source', () => {
		const fake = fakeAudioContext();
		fake.context.createMediaElementSource = vi.fn(() => {
			throw new Error('already connected');
		});
		vi.stubGlobal('AudioContext', fake.constructor);
		audioPlayer.load(makeInfo(), { autoplay: false });

		expect(() => audioPlayer.getAnalyser()).toThrow('already connected');
		expect(fake.context.close).toHaveBeenCalledOnce();
	});

	it('resumes a context suspended until the first gesture, since it carries the sound', () => {
		const fake = fakeAudioContext();
		fake.context.state = 'suspended';
		vi.stubGlobal('AudioContext', fake.constructor);
		audioPlayer.load(makeInfo(), { autoplay: false });
		audioPlayer.getAnalyser();

		audioPlayer.resumeAudioGraph();

		expect(fake.context.resume).toHaveBeenCalledOnce();
	});
});
