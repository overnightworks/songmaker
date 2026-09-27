import { makeGeneration as makeGen } from '$lib/test-utils/factories';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { QueueStreamManifest } from '$lib/api/types';
import { reportResourceStreamReachable, resetConnectivityForTests } from '$lib/stores/connectivity';
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
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
	fakeAudio = new FakeAudio();
	vi.stubGlobal(
		'Audio',
		vi.fn(function () {
			return fakeAudio;
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
	resetConnectivityForTests();
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
	const SECOND = 1000;

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

	it.each(
		playbackModes.flatMap(({ mode, loadMode }) => [
			{
				name: `recovers a third freeze of ${mode} by itself when it played on in between`,
				loadMode,
				playOnSeconds: 10,
				afterThirdFreeze: { status: 'loading', error: null }
			},
			{
				name: `offers Retry on a third freeze of ${mode} when the recoveries fail back to back`,
				loadMode,
				playOnSeconds: 0,
				afterThirdFreeze: { status: 'error', error: 'Playback stalled. Press Retry.' }
			},
			{
				name: `offers Retry on a third freeze of ${mode} that only plays briefly in between`,
				loadMode,
				playOnSeconds: 2,
				afterThirdFreeze: { status: 'error', error: 'Playback stalled. Press Retry.' }
			}
		])
	)('$name', async ({ loadMode, playOnSeconds, afterThirdFreeze }) => {
		loadMode();
		startPlayingAt(40);
		for (let recovery = 1; recovery <= 2; recovery += 1) {
			advanceSeconds(5);
			expect(audioPlayer.status).toBe('loading');
			await vi.advanceTimersByTimeAsync(0);
			startPlayingAt(fakeAudio.currentTime);
			advanceSeconds(playOnSeconds, 1);
		}

		advanceSeconds(5);

		expect({ status: audioPlayer.status, error: audioPlayer.error }).toEqual(afterThirdFreeze);
	});

	async function freezeUntilTheRecoveryBudgetIsSpent(): Promise<void> {
		startPlayingAt(40);
		for (let recovery = 1; recovery <= 2; recovery += 1) {
			advanceSeconds(5);
			await vi.advanceTimersByTimeAsync(0);
			startPlayingAt(fakeAudio.currentTime);
		}
		advanceSeconds(5);
	}

	it.each(playbackModes)(
		'pauses $mode when it gives up, so the sound agrees with the stalled message',
		async ({ loadMode }) => {
			loadMode();
			await freezeUntilTheRecoveryBudgetIsSpent();

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
			await freezeUntilTheRecoveryBudgetIsSpent();

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
		await freezeUntilTheRecoveryBudgetIsSpent();

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
		'tries again when a reload of $mode never answers, then offers Retry once the budget is spent',
		async ({ loadMode }) => {
			loadMode();
			startPlayingAt(40);
			advanceSeconds(5);
			await vi.advanceTimersByTimeAsync(0);
			const firstReloadUrl = fakeAudio.src;

			advanceSeconds(5);
			await vi.advanceTimersByTimeAsync(0);
			expect({ status: audioPlayer.status, retried: fakeAudio.src !== firstReloadUrl }).toEqual({
				status: 'loading',
				retried: true
			});

			fakeAudio.paused = false;
			advanceSeconds(5);
			await vi.advanceTimersByTimeAsync(0);
			expect({
				status: audioPlayer.status,
				error: audioPlayer.error,
				paused: fakeAudio.paused
			}).toEqual({
				status: 'error',
				error: 'Playback stalled. Press Retry.',
				paused: true
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

	it.each([
		{
			name: 'a take change',
			reload: () =>
				audioPlayer.load(makeInfo({ generation: makeGen({ id: 'g2', mp3_path: 'a1/other.mp3' }) }))
		},
		{ name: 'a frozen-clock reload', reload: () => advanceSeconds(5) }
	])(
		'records a later pause from outside after $name swallowed the app pause event',
		({ reload }) => {
			const debug = vi.spyOn(console, 'debug').mockImplementation(() => {});
			startPlayingAt(40);
			vi.spyOn(fakeAudio, 'pause').mockImplementationOnce(() => {
				fakeAudio.paused = true;
			});

			reload();
			startPlayingAt(40);
			fakeAudio.pause();

			expect(debug).toHaveBeenLastCalledWith(
				'Audio paused',
				expect.objectContaining({ source: 'outside' })
			);
		}
	);
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
		expect(fakeAudio.src).toMatch(recoveryUrlOf('/audio/a1/song_v1.mp3'));
		expect(fetchMock).not.toHaveBeenCalled();

		fakeAudio.fire('loadedmetadata');
		expect(fakeAudio.currentTime).toBe(39.25);
	});

	it('falls back to normal error handling after recovery attempts are exhausted', async () => {
		audioPlayer.load(makeInfo(), { autoplay: false });
		fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;

		const recoveryUrls = new Set<string>();
		for (const attempt of [1, 2]) {
			fakeAudio.fire('play');
			fakeAudio.currentTime = 40 + attempt;
			fakeAudio.fire('timeupdate');
			fakeAudio.fire('error');
			expect(fakeAudio.src).toMatch(recoveryUrlOf('/audio/a1/song_v1.mp3'));
			recoveryUrls.add(fakeAudio.src);
			fakeAudio.fire('loadedmetadata');
		}
		expect(recoveryUrls.size).toBe(2);

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
	])('offline, adds no text of its own after $loss — the strip says it', async ({ arrange }) => {
		reportResourceStreamReachable(false);
		arrange();
		fakeAudio.fire('error');
		await new Promise((r) => setTimeout(r, 0));
		expect(audioPlayer.status).toBe('error');
		expect(audioPlayer.error).toBeNull();
	});

	it('online, names a failure no strip explains and offers the Retry', async () => {
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

		expect(fetchMock).toHaveBeenCalledWith('/shared/slug/audio/first.mp3', {
			method: 'HEAD',
			credentials: 'include'
		});
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
			createMediaElementSource: vi.fn(() => ({ connect: vi.fn() })),
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
