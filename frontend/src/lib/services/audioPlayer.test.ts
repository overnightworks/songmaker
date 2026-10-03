import { makeGeneration as makeGen } from '$lib/test-utils/factories';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { QueueStreamManifest } from '$lib/api/types';
import { audioPlayer, type AudioPlayerCallbacks, type PlaybackInfo } from './audioPlayer.svelte';
import { TakeNotAppended } from './continuousDeck';
import { readThePlayingTakeFrom, recordPlaybackEvent } from './playbackDiagnostics';

vi.mock('./playbackDiagnostics', () => ({
	recordPlaybackEvent: vi.fn(),
	readThePlayingTakeFrom: vi.fn()
}));

// What the page's own events (screen off, page hidden) record as playing.
const [playingTakeForPageEvents] = vi.mocked(readThePlayingTakeFrom).mock.calls[0];

interface HeldTake {
	take: PlaybackInfo;
	start_offset: number;
	duration: number;
}

// 'next' replaces whatever the deck holds behind the playing take; 'end'
// appends behind its last take.
interface AppendRequest {
	take: PlaybackInfo;
	url: string;
	placement: 'end' | 'next';
	fail: (error: Error) => void;
}

// The continuous deck as the player sees it: what it was asked to append, and
// a manifest of what it holds that each test lays out itself. The deck's own
// appending, eviction and failures are proven in continuousDeck.test.ts.
interface DeckDouble {
	requests: AppendRequest[];
	manifest: HeldTake[];
	playableFrom: number;
	appending: boolean;
	ended: boolean;
	closed: boolean;
	retries: number;
	seeks: number[];
	scrubs: number[];
}

const continuousDecks = vi.hoisted(() => ({ supported: false, attached: [] as DeckDouble[] }));

vi.mock('./continuousDeck', () => {
	class TakeNotAppended extends Error {
		constructor(
			readonly take: unknown,
			readonly reason: string,
			message: string
		) {
			super(message);
		}
	}
	class ContinuousDeckDouble implements DeckDouble {
		requests: AppendRequest[] = [];
		manifest: HeldTake[] = [];
		playableFrom = 0;
		appending = false;
		ended = false;
		closed = false;
		retries = 0;
		seeks: number[] = [];
		scrubs: number[] = [];

		private constructor(private readonly element: HTMLMediaElement) {}

		static isSupported(): boolean {
			return continuousDecks.supported;
		}

		static attach({ element }: { element: HTMLMediaElement }): ContinuousDeckDouble {
			const deck = new ContinuousDeckDouble(element);
			continuousDecks.attached.push(deck);
			return deck;
		}

		seekTo(seconds: number): void {
			this.seeks.push(seconds);
			this.element.currentTime = seconds;
		}

		scrubTo(seconds: number): void {
			this.scrubs.push(seconds);
			this.element.currentTime = seconds;
		}

		entryAt(seconds: number): HeldTake | undefined {
			return this.manifest.findLast((entry) => entry.start_offset <= seconds);
		}

		isPlayableFromStart(entry: HeldTake): boolean {
			return entry.start_offset >= this.playableFrom;
		}

		appendTake(take: PlaybackInfo, url: string): Promise<void> {
			return this.request(take, url, 'end');
		}

		appendNext(take: PlaybackInfo, url: string): Promise<void> {
			return this.request(take, url, 'next');
		}

		private request(take: PlaybackInfo, url: string, placement: 'end' | 'next'): Promise<void> {
			if (this.ended)
				return Promise.reject(new TakeNotAppended(take, 'stream-ended', `${url} came late`));
			return new Promise((_resolve, reject) =>
				this.requests.push({ take, url, placement, fail: reject })
			);
		}

		endStream(): Promise<void> {
			this.ended = true;
			return Promise.resolve();
		}

		close(): void {
			this.closed = true;
		}

		retryDownload(): void {
			this.retries += 1;
		}
	}
	return { ContinuousDeck: ContinuousDeckDouble, TakeNotAppended };
});

const NO_STRIP_SHOWN = (): boolean => false;
const SECOND = 1000;
const RECOVERY_DEADLINE = 2 * 60 * SECOND;
const STALLED = 'Playback stalled. Press Retry.';
const WAITING_FOR_NETWORK = 'Waiting for the network.';

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

function recordedNotes(): Parameters<typeof recordPlaybackEvent>[0][] {
	return vi.mocked(recordPlaybackEvent).mock.calls.map(([note]) => note);
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
		if (this.error?.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED)
			return Promise.reject(new DOMException('no supported source', 'NotSupportedError'));
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
		this.error = null;
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
	vi.mocked(recordPlaybackEvent).mockClear();
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
		'never pauses $mode when it gives up, so a late answer plays on',
		async ({ loadMode }) => {
			loadMode();
			await freezeUntilTheDeadlinePasses();

			expect({
				status: audioPlayer.status,
				transport: audioPlayer.transport,
				paused: fakeAudio.paused
			}).toEqual({ status: 'error', transport: 'failed', paused: false });
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

	it.each(playbackModes)(
		'keeps $mode paused by an outside pause after it played on by itself after giving up',
		async ({ loadMode }) => {
			loadMode();
			await freezeUntilTheDeadlinePasses();
			startPlayingAt(fakeAudio.currentTime);

			fakeAudio.pause();
			fakeAudio.fire('canplay');

			expect({ status: audioPlayer.status, paused: fakeAudio.paused }).toEqual({
				status: 'ready',
				paused: true
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
				afterTheDeadline: { status: audioPlayer.status, error: audioPlayer.error }
			}).toEqual({
				beforeTheDeadline: { status: 'loading', retried: true },
				afterTheDeadline: { status: 'error', error: STALLED }
			});
		}
	);

	it.each(playbackModes)(
		'keeps $mode given up when the late error of its last reload arrives',
		async ({ loadMode }) => {
			loadMode();
			await freezeUntilTheDeadlinePasses();
			const srcWhenGivenUp = fakeAudio.src;
			fetchMock.mockClear();

			fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;
			fakeAudio.fire('error');
			await vi.advanceTimersByTimeAsync(5 * SECOND);

			expect({
				status: audioPlayer.status,
				error: audioPlayer.error,
				probed: fetchMock.mock.calls.length > 0,
				reloaded: fakeAudio.src !== srcWhenGivenUp
			}).toEqual({ status: 'error', error: STALLED, probed: false, reloaded: false });
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
		startPlayingAt(40);

		pauseIt();

		expect(recordedNotes().at(-1)).toMatchObject({
			kind: 'pause',
			detail: expect.stringContaining(`source=${source}`)
		});
	});

	it('records a later pause from outside after a take change swallowed the app pause event', () => {
		startPlayingAt(40);
		vi.spyOn(fakeAudio, 'pause').mockImplementationOnce(() => {
			fakeAudio.paused = true;
		});

		audioPlayer.load(makeInfo({ generation: makeGen({ id: 'g2', mp3_path: 'a1/other.mp3' }) }));
		startPlayingAt(40);
		fakeAudio.pause();

		expect(recordedNotes().at(-1)).toMatchObject({
			kind: 'pause',
			detail: expect.stringContaining('source=outside')
		});
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
		{ strip: 'the offline strip says so', announced: true, givenUpWords: WAITING_FOR_NETWORK },
		{ strip: 'nothing says so', announced: false, givenUpWords: STALLED }
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
		async ({ announced, givenUpWords }) => {
			loseTheNetworkWhilePlayingAt(40, announced);

			await vi.advanceTimersByTimeAsync(RECOVERY_DEADLINE - 10 * SECOND);
			const givenUpBeforeTheDeadline = audioPlayer.status === 'error';
			await vi.advanceTimersByTimeAsync(3 * 60 * SECOND - RECOVERY_DEADLINE + 10 * SECOND);

			expect({
				givenUpBeforeTheDeadline,
				status: audioPlayer.status,
				error: audioPlayer.error
			}).toEqual({ givenUpBeforeTheDeadline: false, status: 'error', error: givenUpWords });
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

	async function giveUpOnAThreeMinuteOutage(): Promise<void> {
		loseTheNetworkWhilePlayingAt(40, true);
		await vi.advanceTimersByTimeAsync(3 * 60 * SECOND);
	}

	it('the return of a network it gave up waiting for retries the take once by itself', async () => {
		await giveUpOnAThreeMinuteOutage();
		const load = vi.spyOn(fakeAudio, 'load');

		networkGone = false;
		audioPlayer.resumeAfterNetworkReturn();
		const reloads = load.mock.calls.length;
		fakeAudio.fire('loadedmetadata');
		fakeAudio.fire('canplay');
		await vi.advanceTimersByTimeAsync(0);

		expect({
			reloads,
			src: fakeAudio.src,
			status: audioPlayer.status,
			error: audioPlayer.error,
			position: fakeAudio.currentTime
		}).toEqual({
			reloads: 1,
			src: expect.stringMatching(recoveryUrlOf('/audio/a1/song_v1.mp3')),
			status: 'playing',
			error: null,
			position: 39.25
		});
	});

	it('a listener who paused while it waited for the network keeps silence when the network returns', async () => {
		await giveUpOnAThreeMinuteOutage();
		audioPlayer.pause();
		const load = vi.spyOn(fakeAudio, 'load');

		networkGone = false;
		audioPlayer.resumeAfterNetworkReturn();
		await vi.advanceTimersByTimeAsync(0);

		expect({
			reloads: load.mock.calls.length,
			status: audioPlayer.status,
			error: audioPlayer.error
		}).toEqual({ reloads: 0, status: 'error', error: STALLED });
	});

	const givenUpTakes = [
		{
			take: 'a take whose first byte never came',
			giveUp: async () => {
				audioPlayer.load(makeInfo());
				await vi.advanceTimersByTimeAsync(3 * 60 * SECOND);
			}
		},
		{ take: 'a take that waited for the network', giveUp: giveUpOnAThreeMinuteOutage }
	];

	async function answerLate(): Promise<void> {
		fakeAudio.fire('loadedmetadata');
		fakeAudio.fire('canplay');
		await vi.advanceTimersByTimeAsync(0);
	}

	it.each(givenUpTakes)(
		'a late answer plays on $take when the listener never paused',
		async ({ giveUp }) => {
			await giveUp();
			const beforeTheAnswer = audioPlayer.status;

			await answerLate();

			expect({
				beforeTheAnswer,
				afterIt: { status: audioPlayer.status, error: audioPlayer.error, paused: fakeAudio.paused }
			}).toEqual({
				beforeTheAnswer: 'error',
				afterIt: { status: 'playing', error: null, paused: false }
			});
		}
	);

	it.each(givenUpTakes)(
		'a late answer leaves $take paused when the listener paused it',
		async ({ giveUp }) => {
			await giveUp();
			audioPlayer.pause();

			await answerLate();

			expect({
				status: audioPlayer.status,
				error: audioPlayer.error,
				paused: fakeAudio.paused
			}).toEqual({ status: 'ready', error: null, paused: true });
		}
	);

	describe('what the transport offers (#1234)', () => {
		it.each([
			{ moment: 'while it buffers', wait: 0 },
			{ moment: 'while a recovery reload runs', wait: 5 * SECOND }
		])('a stalled take offers Pause $moment', async ({ wait }) => {
			loseTheNetworkWhilePlayingAt(40, false);
			await vi.advanceTimersByTimeAsync(wait);

			expect(audioPlayer.transport).toBe('recovering');
		});

		it('Pause on a stalled take stops its recovery and leaves it paused', async () => {
			loseTheNetworkWhilePlayingAt(40, false);
			await vi.advanceTimersByTimeAsync(5 * SECOND);
			const load = vi.spyOn(fakeAudio, 'load');

			audioPlayer.toggle();
			await vi.advanceTimersByTimeAsync(60 * SECOND);

			expect({
				transport: audioPlayer.transport,
				status: audioPlayer.status,
				reloads: load.mock.calls.length
			}).toEqual({ transport: 'paused', status: 'paused', reloads: 0 });
		});

		it.each([
			{ answer: 'the stream still serves', probe: { ok: true, status: 200 } },
			{ answer: 'its snapshot expired', probe: { ok: false, status: 404 } }
		])(
			'Pause while a stalled stream is probed has the last word when $answer',
			async ({ probe }) => {
				let answerProbe: (answer: { ok: boolean; status: number }) => void = () => {};
				fetchMock.mockReturnValueOnce(new Promise((resolve) => (answerProbe = resolve)));
				audioPlayer.swapCallbacks(
					callbacks({ onStreamRebuild: vi.fn().mockResolvedValue(makeStreamManifest()) })
				);
				audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });
				startPlayingAt(12);
				fakeAudio.fire('stalled');
				await vi.advanceTimersByTimeAsync(5 * SECOND);
				const whileProbing = audioPlayer.transport;
				const load = vi.spyOn(fakeAudio, 'load');

				audioPlayer.toggle();
				answerProbe(probe);
				await vi.advanceTimersByTimeAsync(60 * SECOND);

				expect({
					whileProbing,
					transport: audioPlayer.transport,
					reloads: load.mock.calls.length
				}).toEqual({ whileProbing: 'recovering', transport: 'paused', reloads: 0 });
			}
		);

		it.each([
			{
				interruption: 'Pause is pressed',
				interrupt: () => audioPlayer.toggle(),
				afterwards: { song: 'Second', transport: 'paused' }
			},
			{
				interruption: 'another take loads',
				interrupt: () =>
					audioPlayer.load(makeInfo({ songTitle: 'Next take' }), { autoplay: false }),
				afterwards: { song: 'Next take', transport: 'loading' }
			}
		])(
			'a snapshot rebuild that answers after $interruption leaves the player alone',
			async ({ interrupt, afterwards }) => {
				let answerRebuild: (fresh: QueueStreamManifest) => void = () => {};
				fetchMock.mockResolvedValueOnce({ ok: false, status: 404 });
				audioPlayer.swapCallbacks(
					callbacks({
						onStreamRebuild: () => new Promise((resolve) => (answerRebuild = resolve))
					})
				);
				audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });
				startPlayingAt(12);
				fakeAudio.fire('stalled');
				await vi.advanceTimersByTimeAsync(5 * SECOND);

				interrupt();
				answerRebuild(makeStreamManifest());
				await vi.advanceTimersByTimeAsync(0);

				expect({
					song: audioPlayer.current?.songTitle,
					transport: audioPlayer.transport
				}).toEqual(afterwards);
			}
		);

		it.each([
			{ strip: 'the offline strip says so', announced: true, givenUp: 'waiting-for-network' },
			{ strip: 'nothing says so', announced: false, givenUp: 'failed' }
		])('a take given up when $strip shows $givenUp', async ({ announced, givenUp }) => {
			loseTheNetworkWhilePlayingAt(40, announced);
			await vi.advanceTimersByTimeAsync(3 * 60 * SECOND);

			expect(audioPlayer.transport).toBe(givenUp);
		});

		it('Play after pausing a Retry that failed offline fetches the take again once the network is back', async () => {
			await giveUpOnAThreeMinuteOutage();
			audioPlayer.play();
			fakeAudio.error = { code: MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED } as MediaError;
			fakeAudio.fire('error');
			await vi.advanceTimersByTimeAsync(0);
			audioPlayer.toggle();
			const paused = audioPlayer.transport;
			networkGone = false;
			audioPlayer.resumeAfterNetworkReturn();

			audioPlayer.toggle();
			await answerLate();

			expect({
				paused,
				transport: audioPlayer.transport,
				error: audioPlayer.error,
				src: fakeAudio.src
			}).toEqual({
				paused: 'paused',
				transport: 'playing',
				error: null,
				src: expect.stringMatching(recoveryUrlOf('/audio/a1/song_v1.mp3'))
			});
		});

		it.each([
			{ how: 'from the lock screen', pause: () => audioPlayer.pause() },
			{ how: 'with the transport button', pause: () => audioPlayer.toggle() },
			{ how: 'by the system pausing the element', pause: () => fakeAudio.pause() }
		])('a take waiting for the network is paused at once $how', async ({ pause }) => {
			await giveUpOnAThreeMinuteOutage();
			const load = vi.spyOn(fakeAudio, 'load');

			pause();

			expect({ transport: audioPlayer.transport, reloads: load.mock.calls.length }).toEqual({
				transport: 'paused',
				reloads: 0
			});
		});
	});

	it.each([
		{ moment: 'before its first byte', startAt: null },
		{ moment: 'in its first second', startAt: 0.5 },
		{ moment: 'forty seconds in', startAt: 40 }
	])('a take stalling $moment waits like any other', async ({ startAt }) => {
		fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
		audioPlayer.load(makeInfo());
		if (startAt !== null) startPlayingAt(startAt);
		fakeAudio.fire('waiting');
		await vi.advanceTimersByTimeAsync(5 * SECOND);

		fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;
		fakeAudio.fire('error');
		await vi.advanceTimersByTimeAsync(0);
		const afterTheReloadFailed = { status: audioPlayer.status, error: audioPlayer.error };
		await vi.advanceTimersByTimeAsync(60 * SECOND);

		expect({
			afterTheReloadFailed,
			aMinuteLater: { status: audioPlayer.status, error: audioPlayer.error }
		}).toEqual({
			afterTheReloadFailed: { status: 'loading', error: null },
			aMinuteLater: { status: 'loading', error: null }
		});
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

	it('asks a stalled stream one HEAD probe at a time, whatever else asks for recovery meanwhile', async () => {
		vi.useFakeTimers();
		let answerProbe: (answer: { ok: boolean; status: number }) => void = () => {};
		fetchMock.mockReturnValueOnce(new Promise((resolve) => (answerProbe = resolve)));
		audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });
		fakeAudio.fire('play');
		fakeAudio.currentTime = 12;
		fakeAudio.fire('timeupdate');
		fakeAudio.fire('stalled');
		await vi.advanceTimersByTimeAsync(5 * SECOND);
		const load = vi.spyOn(fakeAudio, 'load');

		fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;
		fakeAudio.fire('error');
		audioPlayer.resumeAfterNetworkReturn();
		await vi.advanceTimersByTimeAsync(SECOND);
		answerProbe({ ok: true, status: 200 });
		await vi.advanceTimersByTimeAsync(0);

		expect({ probes: fetchMock.mock.calls.length, reloads: load.mock.calls.length }).toEqual({
			probes: 1,
			reloads: 1
		});
	});

	it('names a lost session on a stalled stream and asks for sign-in', async () => {
		vi.useFakeTimers();
		fetchMock.mockResolvedValue({ ok: false, status: 401 });
		const onAuthLost = vi.fn();
		audioPlayer.swapCallbacks(callbacks({ onAuthLost }));
		audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });
		fakeAudio.fire('play');
		fakeAudio.currentTime = 12;
		fakeAudio.fire('timeupdate');

		fakeAudio.fire('stalled');
		await vi.advanceTimersByTimeAsync(5 * SECOND);

		expect({
			signInAsked: onAuthLost.mock.calls.length > 0,
			status: audioPlayer.status,
			error: audioPlayer.error,
			src: fakeAudio.src
		}).toEqual({
			signInAsked: true,
			status: 'error',
			error: 'Playback failed. Press Retry.',
			src: '/api/queue-streams/snap/audio'
		});
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

	it.each([
		{ decision: 'promote', readyState: 3, asked: next, matched: true },
		{ decision: 'fresh_load', readyState: 2, asked: next, matched: true },
		{ decision: 'fresh_load', readyState: 3, asked: other, matched: false }
	])(
		'records a $decision for a standby at readyState $readyState whose URL matched: $matched',
		({ decision, readyState, asked, matched }) => {
			playFirst();
			preloadReady(next, readyState);
			vi.mocked(recordPlaybackEvent).mockClear();

			audioPlayer.load(asked);

			expect(recordedNotes()).toContainEqual({
				kind: decision,
				detail: `standby_ready_state=${readyState} url_matched=${matched}`,
				take: expect.objectContaining({ takeId: asked.generation.id, deck: 'active' })
			});
		}
	);

	it.each([
		{ deck: 'standby', takeId: null, fire: (standby: FakeAudio) => standby.fire('canplay') },
		{ deck: 'active', takeId: 'g1', fire: () => fakeAudio.fire('canplay') }
	])("records a media event on the $deck deck with that deck's state", ({ deck, takeId, fire }) => {
		playFirst();
		const standby = preloadReady(next);
		const firing = deck === 'standby' ? standby : fakeAudio;
		firing.currentTime = 7;
		firing.bufferedUntil = 42;
		vi.mocked(recordPlaybackEvent).mockClear();

		fire(standby);

		expect(recordedNotes()).toEqual([
			{
				kind: 'media_event',
				detail: expect.stringMatching(/^canplay .*buffered=42\.0/),
				take: { takeId, position: 7, readyState: firing.readyState, deck }
			}
		]);
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

describe('what the player writes down for diagnostics (#1250)', () => {
	it('records a refused play by the error name', async () => {
		audioPlayer.load(makeInfo(), { autoplay: false });
		fakeAudio.fire('canplay');
		fakeAudio.playMock.mockImplementation(() =>
			Promise.reject(Object.assign(new Error('autoplay blocked'), { name: 'NotAllowedError' }))
		);

		audioPlayer.play();
		await new Promise((resolve) => setTimeout(resolve, 0));

		expect(recordedNotes()).toContainEqual(
			expect.objectContaining({ kind: 'play_rejected', detail: 'NotAllowedError' })
		);
	});

	it('tells page events the playing take, its position and readiness', () => {
		audioPlayer.load(makeInfo(), { autoplay: false });
		fakeAudio.readyState = 4;
		fakeAudio.currentTime = 37;

		expect(playingTakeForPageEvents()).toEqual({
			takeId: 'g1',
			position: 37,
			readyState: 4,
			deck: 'active'
		});
	});

	it('records each reload with its reason and then the give-up', async () => {
		vi.useFakeTimers();
		audioPlayer.load(makeInfo(), { autoplay: false });
		fakeAudio.fire('canplay');
		fakeAudio.paused = false;
		fakeAudio.fire('play');
		fakeAudio.fire('playing');
		fakeAudio.currentTime = 41;
		fakeAudio.fire('timeupdate');
		fakeAudio.fire('stalled');

		await vi.advanceTimersByTimeAsync(RECOVERY_DEADLINE + 10 * SECOND);

		const recovery = recordedNotes().filter(
			(note) => note.kind === 'retry' || note.kind === 'give_up'
		);
		expect(recovery[0]).toMatchObject({
			kind: 'retry',
			detail: expect.stringContaining('reason=stall-timeout')
		});
		expect(recovery.at(-1)).toMatchObject({ kind: 'give_up', detail: 'stalled' });
	});
});

describe('continuous deck (#1187 M2)', () => {
	const first = makeInfo({
		generation: makeGen({ id: 'g1', mp3_path: 'a1/first.mp3', audio_duration_sec: 10 }),
		songTitle: 'First'
	});
	const second = makeInfo({
		generation: makeGen({ id: 'g2', mp3_path: 'a1/second.mp3', audio_duration_sec: 20 }),
		songTitle: 'Second'
	});
	const third = takeInfo('g3', 'a1/third.mp3');
	let onCurrentChange: ReturnType<typeof vi.fn<(current: PlaybackInfo | null) => void>>;
	let onEnded: ReturnType<typeof vi.fn<(reason: 'normal' | 'window-end') => void>>;

	beforeEach(() => {
		continuousDecks.supported = true;
		continuousDecks.attached = [];
		vi.stubGlobal('MediaSource', vi.fn());
		onCurrentChange = vi.fn();
		onEnded = vi.fn();
		audioPlayer.swapCallbacks(callbacks({ onCurrentChange, onEnded }));
	});

	afterEach(() => {
		continuousDecks.supported = false;
	});

	function deck(): DeckDouble {
		const attached = continuousDecks.attached.at(-1);
		if (!attached) throw new Error('no deck was attached');
		return attached;
	}

	function holds(...takes: [PlaybackInfo, number, number][]): void {
		deck().manifest = takes.map(([take, start_offset, duration]) => ({
			take,
			start_offset,
			duration
		}));
	}

	function playFirstWithSecondAppended(next: PlaybackInfo = second): void {
		audioPlayer.load(first);
		audioPlayer.preload(next);
		holds([first, 0, 10], [next, 10, 20]);
		fakeAudio.fire('canplay');
		fakeAudio.fire('play');
		fakeAudio.fire('playing');
	}

	function playTo(seconds: number): void {
		fakeAudio.currentTime = seconds;
		fakeAudio.fire('timeupdate');
	}

	function heardEvents(): string[] {
		const heard: string[] = [];
		for (const name of ['pause', 'ended', 'emptied'])
			fakeAudio.addEventListener(name, () => heard.push(name));
		return heard;
	}

	it('starts a queue take on one deck that is asked for that take at once', () => {
		audioPlayer.load(first);

		expect(continuousDecks.attached).toHaveLength(1);
		expect(deck().requests.map((request) => request.url)).toEqual(['/audio/a1/first.mp3']);
		expect(audioPlayer.getElement()).toBe(fakeAudio);
		expect(audioPlayer.current?.generation.id).toBe('g1');
		expect(audioPlayer.status).toBe('loading');
	});

	it('appends the preloaded next take behind the current one, once', () => {
		audioPlayer.load(first);

		audioPlayer.preload(second);
		audioPlayer.preload(second);

		expect(deck().requests.map((request) => request.take)).toEqual([first, second]);
		expect(createdAudios).toHaveLength(1);
	});

	it('puts a repicked or reshuffled next take in place of the one the deck holds ahead', () => {
		const repicked = takeInfo('g2b', 'a1/second-repicked.mp3');
		playFirstWithSecondAppended();
		playTo(4);

		audioPlayer.preload(repicked);
		audioPlayer.preload(repicked);

		expect(deck().requests.map(({ take, placement }) => [take.generation.id, placement])).toEqual([
			['g1', 'end'],
			['g2', 'next'],
			['g2b', 'next']
		]);
	});

	it('keeps what the deck holds when nothing is known to follow yet', () => {
		audioPlayer.load(first);

		audioPlayer.preload(null);

		expect(deck().ended).toBe(false);
		expect(deck().requests).toHaveLength(1);
	});

	it('changes current when the playhead crosses into the next take, with no ended or pause', () => {
		playFirstWithSecondAppended();
		const heard = heardEvents();
		const pauseSpy = vi.spyOn(fakeAudio, 'pause');

		playTo(9.9);
		playTo(10.5);

		expect(audioPlayer.current?.generation.id).toBe('g2');
		expect(onCurrentChange).toHaveBeenLastCalledWith(second);
		expect(audioPlayer.currentTime).toBeCloseTo(0.5);
		expect(audioPlayer.duration).toBe(20);
		expect(audioPlayer.status).toBe('playing');
		expect(pauseSpy).not.toHaveBeenCalled();
		expect(heard).toEqual([]);
		expect(onEnded).not.toHaveBeenCalled();
	});

	describe('when the queue holds one take in two places', () => {
		const firstAgain = { ...first };

		it('appends the take for each place and crosses into both, then the take after them', () => {
			playFirstWithSecondAppended(firstAgain);

			playTo(10.5);
			audioPlayer.preload(third);
			holds([first, 0, 10], [firstAgain, 10, 20], [third, 30, 5]);
			playTo(30.5);

			expect(deck().requests.map((request) => request.take)).toEqual([first, firstAgain, third]);
			expect(onCurrentChange.mock.calls.map(([take]) => take)).toEqual([first, firstAgain, third]);
			expect(audioPlayer.current).toBe(third);
		});

		it('follows a dropped take between the two places with the second place, then the take after it', async () => {
			const takeAfter = (take: PlaybackInfo): PlaybackInfo | null =>
				take === second ? firstAgain : null;
			audioPlayer.swapCallbacks(callbacks({ onCurrentChange, onEnded, takeAfter }));
			playFirstWithSecondAppended();

			deck().requests[1].fail(
				new TakeNotAppended(second, 'refused', '/audio/a1/second.mp3 answered 404')
			);
			await Promise.resolve();
			holds([first, 0, 10], [firstAgain, 10, 20]);
			playTo(10.5);
			audioPlayer.preload(third);

			expect(deck().requests.map((request) => request.take)).toEqual([
				first,
				second,
				firstAgain,
				third
			]);
			expect(audioPlayer.current).toBe(firstAgain);
			expect(onCurrentChange.mock.lastCall?.[0]).toBe(firstAgain);
		});

		it('Next and Previous between the two places move the audio with the place', () => {
			playFirstWithSecondAppended(firstAgain);
			playTo(4);

			audioPlayer.load(firstAgain);

			expect(fakeAudio.currentTime).toBe(10);
			expect(audioPlayer.current).toBe(firstAgain);
			expect(continuousDecks.attached).toHaveLength(1);

			playTo(10.5);
			audioPlayer.load(first);

			expect(continuousDecks.attached).toHaveLength(2);
			expect(deck().requests.map((request) => request.take)).toEqual([first]);
			expect(audioPlayer.current).toBe(first);
		});
	});

	it('plays on through a load of the playing take built outside the queue, keeping the take it holds', () => {
		playFirstWithSecondAppended();
		playTo(4);
		const seekSpy = vi.spyOn(deck(), 'seekTo');

		audioPlayer.load({ ...first });

		expect(seekSpy).not.toHaveBeenCalled();
		expect(fakeAudio.currentTime).toBe(4);
		expect(continuousDecks.attached).toHaveLength(1);
		expect(audioPlayer.current).toBe(first);
	});

	it('reads the position within the take from the element clock at once', () => {
		playFirstWithSecondAppended();
		playTo(12);

		fakeAudio.currentTime = 12.4;

		expect(audioPlayer.currentTimeNow).toBeCloseTo(2.4);
	});

	it('restores a take at its saved position through the deck, before the deck holds that far', () => {
		audioPlayer.load(second, { autoplay: false, startAt: 14.5 });
		holds([second, 0, 4]);

		fakeAudio.fire('loadedmetadata');

		expect(deck().seeks).toEqual([14.5]);
		expect(fakeAudio.currentTime).toBe(14.5);
		expect(audioPlayer.currentTime).toBe(14.5);
	});

	it('a scrub while the restore waits for its place goes only as far as the deck has audio', () => {
		audioPlayer.load(second, { autoplay: false, startAt: 14.5 });
		holds([second, 0, 4]);
		fakeAudio.fire('loadedmetadata');

		audioPlayer.seek(18);

		expect(deck().seeks).toEqual([14.5]);
		expect(deck().scrubs).toEqual([18]);
	});

	it('a seek within the current take lands at that take in the element timeline', () => {
		playFirstWithSecondAppended();
		playTo(12);

		audioPlayer.seek(5);

		expect(fakeAudio.currentTime).toBe(15);
	});

	it('a seek clamps to the part of the take the deck holds', () => {
		playFirstWithSecondAppended();
		holds([first, 0, 10], [second, 10, 12]);
		playTo(12);

		audioPlayer.seek(17);

		expect(fakeAudio.currentTime).toBe(22);
	});

	it.each([
		{ load: 'Next onto the take handed last', at: 4, take: second, opts: {}, landsAt: 10 },
		{
			load: 'a restart of the playing take',
			at: 12,
			take: second,
			opts: { restart: true },
			landsAt: 10
		},
		{
			load: 'a rebuild of the playing take at a position',
			at: 12,
			take: second,
			opts: { restart: true, startAt: 1.5 },
			landsAt: 11.5
		},
		{
			load: 'a rebuilt queue handing the playing take anew at a position',
			at: 12,
			take: { ...second },
			opts: { restart: true, startAt: 1.5 },
			landsAt: 11.5
		}
	])('plays on from its one source for $load', ({ at, take, opts, landsAt }) => {
		playFirstWithSecondAppended();
		playTo(at);
		const loadSpy = vi.spyOn(fakeAudio, 'load');

		audioPlayer.load(take, opts);

		expect(fakeAudio.currentTime).toBe(landsAt);
		expect(loadSpy).not.toHaveBeenCalled();
		expect(continuousDecks.attached).toHaveLength(1);
		expect(audioPlayer.current?.generation.id).toBe(take.generation.id);
		expect(audioPlayer.currentTime).toBe(opts.startAt ?? 0);
		expect(audioPlayer.duration).toBe(20);
	});

	function playThreeHeldWithThirdHandedLast(): void {
		playFirstWithSecondAppended();
		audioPlayer.preload(third);
		holds([first, 0, 10], [second, 10, 20], [third, 30, 5]);
	}

	it.each([
		{
			load: 'Prev to the take before the playhead',
			setup: playFirstWithSecondAppended,
			at: 12,
			take: first,
			playableFrom: 0
		},
		{
			load: 'a jump to the take handed last past the next one',
			setup: playThreeHeldWithThirdHandedLast,
			at: 4,
			take: third,
			playableFrom: 0
		},
		{
			load: 'a tap on a held take that is not the one handed last',
			setup: playThreeHeldWithThirdHandedLast,
			at: 4,
			take: second,
			playableFrom: 0
		},
		{
			load: 'a restart of the playing take whose start was removed',
			setup: playFirstWithSecondAppended,
			at: 12,
			take: second,
			playableFrom: 11
		}
	])('starts a fresh deck at the take for $load', ({ setup, at, take, playableFrom }) => {
		setup();
		playTo(at);
		const left = deck();
		left.playableFrom = playableFrom;

		audioPlayer.load(take, { restart: true });

		expect(continuousDecks.attached).toHaveLength(2);
		expect(left.closed).toBe(true);
		expect(deck().requests.map((request) => request.take)).toEqual([take]);
		expect(audioPlayer.current?.generation.id).toBe(take.generation.id);
	});

	it('Prev continues on the fresh deck into the take after it', () => {
		playFirstWithSecondAppended();
		playTo(12);

		audioPlayer.load(first, { restart: true });
		audioPlayer.preload(second);

		expect(continuousDecks.attached).toHaveLength(2);
		expect(deck().requests.map((request) => request.take)).toEqual([first, second]);
	});

	it('ends the stream only when the playhead runs out of takes with nothing on its way', async () => {
		playFirstWithSecondAppended();
		playTo(29.9);
		fakeAudio.bufferedUntil = 30;
		deck().appending = true;
		fakeAudio.fire('waiting');
		expect(deck().ended).toBe(false);

		deck().appending = false;
		fakeAudio.currentTime = 30;
		fakeAudio.fire('waiting');
		expect(deck().ended).toBe(true);

		fakeAudio.fire('ended');
		expect(onEnded).toHaveBeenCalledOnce();
	});

	it.each([
		{
			name: 'does not end while the queue names a next take',
			next: third,
			after: { ended: false, transport: 'recovering' }
		},
		{
			name: 'ends when the queue names none',
			next: null,
			after: { ended: true, transport: 'playing' }
		}
	])('at the end of what it holds, the deck $name', ({ next, after }) => {
		const takeAfter = (take: PlaybackInfo): PlaybackInfo | null => (take === second ? next : null);
		audioPlayer.swapCallbacks(callbacks({ onCurrentChange, onEnded, takeAfter }));
		playFirstWithSecondAppended();
		playTo(29.9);
		fakeAudio.bufferedUntil = 30;

		fakeAudio.fire('waiting');

		expect({ ended: deck().ended, transport: audioPlayer.transport }).toEqual(after);
		expect(onEnded).not.toHaveBeenCalled();
	});

	it('drops a take ahead the server refused, names it and crosses on into the take after it', async () => {
		const takeAfter = (take: PlaybackInfo): PlaybackInfo | null => (take === second ? third : null);
		const skipped: PlaybackInfo[] = [];
		const onTakeSkipped = (take: PlaybackInfo) => skipped.push(take);
		audioPlayer.swapCallbacks(callbacks({ onCurrentChange, onEnded, takeAfter, onTakeSkipped }));
		playFirstWithSecondAppended();
		const heard = heardEvents();

		deck().requests[1].fail(
			new TakeNotAppended(second, 'refused', '/audio/a1/second.mp3 answered 404')
		);
		await Promise.resolve();

		expect(skipped).toEqual([second]);
		expect(deck().requests.map((request) => request.take)).toEqual([first, second, third]);
		expect(audioPlayer.current?.generation.id).toBe('g1');
		expect(audioPlayer.status).toBe('playing');
		expect(recordedNotes().map((note) => note.detail)).toContain(
			'deck_dropped take=g2 refused /audio/a1/second.mp3 answered 404'
		);

		holds([first, 0, 10], [third, 10, 5]);
		fakeAudio.bufferedUntil = 15;
		playTo(10);
		fakeAudio.fire('waiting');
		playTo(10.5);

		expect(audioPlayer.current?.generation.id).toBe('g3');
		expect(deck().ended).toBe(false);
		expect(heard).toEqual([]);
		expect(onEnded).not.toHaveBeenCalled();
	});

	it('asks for no further take when one comes after the end of the stream', async () => {
		const takeAfter = vi.fn((): PlaybackInfo | null => first);
		audioPlayer.swapCallbacks(callbacks({ onCurrentChange, onEnded, takeAfter }));
		playFirstWithSecondAppended();
		deck().ended = true;

		audioPlayer.preload(third);
		await Promise.resolve();

		expect(takeAfter).not.toHaveBeenCalled();
		expect(audioPlayer.current?.generation.id).toBe('g1');
	});

	it.each([
		{ failure: 'the server refuses the current take', refused: true },
		{ failure: 'the buffer refuses the audio', refused: false }
	])(
		'falls back to the two decks at the same take and position when $failure',
		async ({ refused }) => {
			playFirstWithSecondAppended();
			playTo(6);
			fakeAudio.paused = false;

			deck().requests[0].fail(
				refused
					? new TakeNotAppended(first, 'refused', '/audio/a1/first.mp3 answered 404')
					: new Error('The source buffer refused the appended audio')
			);
			await Promise.resolve();

			expect(fakeAudio.src).toBe('/audio/a1/first.mp3');
			expect(audioPlayer.current?.generation.id).toBe('g1');
			expect(audioPlayer.status).toBe('loading');
			fakeAudio.fire('loadedmetadata');
			expect(fakeAudio.currentTime).toBe(6);

			audioPlayer.preload(second);
			expect(createdAudios.at(-1)?.src).toBe('/audio/a1/second.mp3');
			expect(deck().requests).toHaveLength(2);
		}
	);

	it('falls back to the two decks when the element reports a media error', () => {
		playFirstWithSecondAppended();
		playTo(3);

		fakeAudio.error = { code: 3 } as MediaError;
		fakeAudio.fire('error');

		expect(fakeAudio.src).toBe('/audio/a1/first.mp3');
		expect(audioPlayer.status).toBe('loading');
	});

	it.each([
		{ leaving: 'for a new queue', leave: () => audioPlayer.load(takeInfo('g9', 'b2/other.mp3')) },
		{ leaving: 'on unload', leave: () => audioPlayer.unload() },
		{ leaving: 'on destroy', leave: () => audioPlayer.destroy() },
		{
			leaving: 'for the two decks',
			leave: async () => {
				deck().requests[1].fail(new Error('The source buffer refused the appended audio'));
				await Promise.resolve();
			}
		}
	])('closes the deck it leaves $leaving', async ({ leave }) => {
		playFirstWithSecondAppended();
		playTo(4);
		const left = deck();

		await leave();

		expect(left.closed).toBe(true);
	});

	function recordedDetails(): string[] {
		return recordedNotes().map((note) => `${note.kind} ${note.detail}`);
	}

	it('keeps the deck on a stall and resumes its download on the same element with no seek back', () => {
		vi.useFakeTimers();
		playFirstWithSecondAppended();
		playTo(6);
		const source = fakeAudio.src;
		const loadSpy = vi.spyOn(fakeAudio, 'load');

		fakeAudio.fire('stalled');
		vi.advanceTimersByTime(5 * SECOND);

		expect(deck().retries).toBe(1);
		expect(deck().closed).toBe(false);
		expect(continuousDecks.attached).toHaveLength(1);
		expect(fakeAudio.src).toBe(source);
		expect(loadSpy).not.toHaveBeenCalled();
		expect(fakeAudio.currentTime).toBe(6);
		expect(audioPlayer.currentTime).toBe(6);
		expect(audioPlayer.transport).toBe('recovering');
		expect(recordedDetails()).toContain('retry deck_resume reason=stall-timeout');

		vi.advanceTimersByTime(5 * SECOND);
		expect(deck().retries).toBe(2);
	});

	it.each([
		{ when: 'while a stall is watched', stalled: true },
		{ when: 'while the take plays on and only a take ahead waits', stalled: false }
	])("the network's return resumes a parked deck at once $when", ({ stalled }) => {
		vi.useFakeTimers();
		playFirstWithSecondAppended();
		playTo(4);
		if (stalled) fakeAudio.fire('stalled');

		audioPlayer.resumeAfterNetworkReturn();

		expect(deck().retries).toBe(1);
		expect(deck().closed).toBe(false);
		expect(recordedDetails()).toContain('retry deck_resume reason=network-return');
	});

	it('a take ahead that fails on the network is neither skipped nor named, and plays once its bytes arrive', () => {
		vi.useFakeTimers();
		const takeAfter = (take: PlaybackInfo): PlaybackInfo | null => (take === first ? second : null);
		const onTakeSkipped = vi.fn();
		audioPlayer.swapCallbacks(callbacks({ onCurrentChange, onEnded, takeAfter, onTakeSkipped }));
		playFirstWithSecondAppended();
		holds([first, 0, 10]);
		deck().appending = true;
		fakeAudio.bufferedUntil = 10;
		playTo(10);
		fakeAudio.fire('waiting');

		vi.advanceTimersByTime(5 * SECOND);

		expect(deck().retries).toBe(1);
		expect(deck().ended).toBe(false);
		expect(onTakeSkipped).not.toHaveBeenCalled();
		expect(recordedDetails().some((detail) => detail.includes('deck_dropped'))).toBe(false);
		expect(audioPlayer.error).toBeNull();

		holds([first, 0, 10], [second, 10, 20]);
		fakeAudio.bufferedUntil = 30;
		playTo(10.5);
		fakeAudio.fire('playing');

		expect(audioPlayer.current?.generation.id).toBe('g2');
		expect(audioPlayer.status).toBe('playing');
		expect(continuousDecks.attached).toHaveLength(1);
	});

	// The player never pauses itself on a give-up, so the element still plays.
	async function giveUpOnTheDeckAt(seconds: number): Promise<void> {
		vi.useFakeTimers();
		playFirstWithSecondAppended();
		playTo(seconds);
		fakeAudio.paused = false;
		await vi.advanceTimersByTimeAsync(0);

		fakeAudio.fire('stalled');
		await vi.advanceTimersByTimeAsync(RECOVERY_DEADLINE + 10 * SECOND);
	}

	it('gives up after the deadline while the deck stays attached', async () => {
		await giveUpOnTheDeckAt(6);

		expect(audioPlayer.error).toBe(STALLED);
		expect(deck().retries).toBeGreaterThan(1);
		expect(deck().closed).toBe(false);
		expect(continuousDecks.attached).toHaveLength(1);
		expect(recordedNotes().at(-1)).toMatchObject({ kind: 'give_up', detail: 'stalled' });
	});

	it.each([
		{
			name: 'a clock that moves on while the element plays ends it',
			paused: false,
			move: () => playTo(7),
			after: { status: 'playing', error: null },
			frozenClockAfterwardsNudged: true
		},
		{
			name: 'a seek while the element is paused leaves it',
			paused: true,
			move: () => {
				audioPlayer.seek(3);
				fakeAudio.fire('timeupdate');
			},
			after: { status: 'error', error: STALLED },
			frozenClockAfterwardsNudged: false
		}
	])(
		'given up on the deck, $name',
		async ({ paused, move, after, frozenClockAfterwardsNudged }) => {
			await giveUpOnTheDeckAt(6);
			fakeAudio.paused = paused;

			move();
			fakeAudio.bufferedUntil = 20;
			const seeks = recordSeeks(fakeAudio);
			await vi.advanceTimersByTimeAsync(5 * SECOND);

			expect({ status: audioPlayer.status, error: audioPlayer.error }).toEqual(after);
			expect(seeks.length > 0).toBe(frozenClockAfterwardsNudged);
		}
	);

	it.each([
		{ action: 'Retry', networkAnnouncedGone: false, retry: () => audioPlayer.play() },
		{
			action: "the network's return",
			networkAnnouncedGone: true,
			retry: () => audioPlayer.resumeAfterNetworkReturn()
		}
	])(
		'$action after giving up resumes the deck download and plays on from the element position',
		async ({ networkAnnouncedGone, retry }) => {
			let networkGone = networkAnnouncedGone;
			audioPlayer.swapCallbacks(
				callbacks({ onCurrentChange, onEnded, networkFailureIsAnnounced: () => networkGone })
			);
			await giveUpOnTheDeckAt(6);
			const retriesWhenGivenUp = deck().retries;
			const loadSpy = vi.spyOn(fakeAudio, 'load');
			networkGone = false;

			retry();
			await vi.advanceTimersByTimeAsync(0);

			expect(deck().retries).toBe(retriesWhenGivenUp + 1);
			expect(deck().closed).toBe(false);
			expect(continuousDecks.attached).toHaveLength(1);
			expect(loadSpy).not.toHaveBeenCalled();
			expect(fakeAudio.src).not.toMatch(/recover=/);
			expect(fakeAudio.currentTime).toBe(6);
			expect(audioPlayer.error).toBeNull();

			playTo(6.5);
			fakeAudio.fire('playing');
			expect(audioPlayer.status).toBe('playing');
			expect(audioPlayer.currentTime).toBe(6.5);
		}
	);

	it.each([
		{ moment: 'before its first byte', arrange: () => audioPlayer.load(first) },
		{
			moment: 'while a stall waits for its next look',
			arrange: () => {
				playFirstWithSecondAppended();
				playTo(4);
				fakeAudio.fire('stalled');
			}
		},
		{
			moment: 'after the listener paused it while it waited for its bytes',
			arrange: () => {
				playFirstWithSecondAppended();
				playTo(4);
				fakeAudio.bufferedUntil = 4;
				deck().appending = true;
				fakeAudio.fire('stalled');
				audioPlayer.pause();
			}
		}
	])('Play on a parked take resumes its download at once $moment', ({ arrange }) => {
		vi.useFakeTimers();
		arrange();

		audioPlayer.play();

		expect(deck().retries).toBe(1);
		expect(deck().closed).toBe(false);
		expect(recordedDetails()).toContain('retry deck_resume reason=play');
	});

	it('Play on a paused take with audio ahead of the playhead leaves its download alone', () => {
		vi.useFakeTimers();
		playFirstWithSecondAppended();
		playTo(4);
		fakeAudio.bufferedUntil = 12;
		deck().appending = true;
		audioPlayer.pause();

		audioPlayer.play();

		expect(deck().retries).toBe(0);
	});

	function freezeTheClockOverBufferedAudioAt(seconds: number): void {
		vi.useFakeTimers();
		playFirstWithSecondAppended();
		playTo(seconds);
		fakeAudio.paused = false;
		fakeAudio.bufferedUntil = 20;
	}

	function recordSeeks(el: FakeAudio): number[] {
		const seeks: number[] = [];
		let position = el.currentTime;
		Object.defineProperty(el, 'currentTime', {
			configurable: true,
			get: () => position,
			set: (seconds: number) => {
				seeks.push(seconds);
				position = seconds;
			}
		});
		return seeks;
	}

	it.each([
		{ noticedBy: 'the watchdog', notice: () => vi.advanceTimersByTime(5 * SECOND) },
		{
			noticedBy: 'a Play tap after one still look',
			notice: () => {
				vi.advanceTimersByTime(2 * SECOND);
				audioPlayer.play();
			}
		}
	])(
		'nudges a clock frozen over buffered audio in place when $noticedBy notices it',
		({ notice }) => {
			freezeTheClockOverBufferedAudioAt(6);
			const seeks = recordSeeks(fakeAudio);
			fakeAudio.playMock.mockClear();
			const loadSpy = vi.spyOn(fakeAudio, 'load');

			notice();

			expect(seeks).toEqual([6]);
			expect(fakeAudio.playMock).toHaveBeenCalledOnce();
			expect(continuousDecks.attached).toHaveLength(1);
			expect(deck().closed).toBe(false);
			expect(loadSpy).not.toHaveBeenCalled();
			expect(audioPlayer.status).toBe('playing');
		}
	);

	it('a Play tap on a clock frozen with no audio ahead resumes the download under that cause and plays on', () => {
		freezeTheClockOverBufferedAudioAt(6);
		fakeAudio.bufferedUntil = 6;
		vi.advanceTimersByTime(2 * SECOND);
		fakeAudio.playMock.mockClear();

		audioPlayer.play();

		expect(recordedDetails()).toContain('retry deck_resume reason=frozen-clock');
		expect(deck().retries).toBe(1);
		expect(fakeAudio.playMock).toHaveBeenCalledOnce();
		expect(continuousDecks.attached).toHaveLength(1);
	});

	it('opens a fresh deck at the take and position on the same element when the clock is still frozen at the next look', () => {
		audioPlayer.swapCallbacks(
			callbacks({
				onEnded,
				onCurrentChange: (current) => {
					if (current?.generation.id === first.generation.id) audioPlayer.preload(second);
				}
			})
		);
		freezeTheClockOverBufferedAudioAt(6);
		vi.advanceTimersByTime(5 * SECOND);
		const frozen = deck();

		vi.advanceTimersByTime(5 * SECOND);

		expect(frozen.closed).toBe(true);
		expect(continuousDecks.attached).toHaveLength(2);
		expect(deck().requests.map((request) => request.take)).toEqual([first, second]);
		expect(audioPlayer.getElement()).toBe(fakeAudio);
		expect(fakeAudio.src).not.toMatch(/recover=/);
		expect(audioPlayer.current?.generation.id).toBe('g1');
		expect(audioPlayer.transport).toBe('recovering');
		fakeAudio.fire('loadedmetadata');
		expect(fakeAudio.currentTime).toBe(6);
	});

	it('a browser without MSE MP3 keeps the two decks', () => {
		continuousDecks.supported = false;

		audioPlayer.load(first);
		audioPlayer.preload(second);

		expect(continuousDecks.attached).toEqual([]);
		expect(fakeAudio.src).toBe('/audio/a1/first.mp3');
		expect(createdAudios.at(-1)?.src).toBe('/audio/a1/second.mp3');
	});

	it('writes down the deck opening, each append, the crossing, a resume and a fallback', async () => {
		vi.useFakeTimers();
		playFirstWithSecondAppended();
		playTo(10.5);
		fakeAudio.fire('stalled');
		vi.advanceTimersByTime(5 * SECOND);
		deck().requests[1].fail(new Error('The source buffer refused the appended audio'));
		await Promise.resolve();

		expect(recordedDetails()).toEqual(
			expect.arrayContaining([
				'fresh_load deck=continuous',
				'media_event deck_append take=g1',
				'media_event deck_append take=g2',
				'media_event deck_crossing',
				'retry deck_resume reason=stall-timeout',
				expect.stringMatching(/^retry deck_fallback The source buffer refused/)
			])
		);
		const crossing = recordedNotes().find((note) => note.detail === 'deck_crossing');
		expect(crossing?.take).toEqual(expect.objectContaining({ takeId: 'g2', position: 0.5 }));
	});
});
