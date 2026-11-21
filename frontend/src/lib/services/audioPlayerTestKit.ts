import { vi } from 'vitest';
import type { QueueStreamManifest } from '#lib/api/types.ts';
import type { AudioPlayerCallbacks, PlaybackInfo } from './audioPlayer.svelte';
import { makeGeneration as makeGen } from '#lib/test-utils/factories.ts';

// The doubles the player's tests share: a fake <audio> element, the continuous
// deck as the player sees it, and the builders for what the player plays.
export interface HeldTake {
	take: PlaybackInfo;
	start_offset: number;
	duration: number;
}

// 'next' replaces whatever the deck holds behind the playing take; 'end'
// appends behind its last take.
export interface AppendRequest {
	take: PlaybackInfo;
	url: string;
	placement: 'end' | 'next';
	fail: (error: Error) => void;
}

// The continuous deck as the player sees it: what it was asked to append, and
// a manifest of what it holds that each test lays out itself. The deck's own
// appending, eviction and failures are proven in continuousDeck.test.ts.
export interface DeckDouble {
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

export const continuousDecks = { supported: false, attached: [] as DeckDouble[] };

// The module `./continuousDeck` is replaced by in each test file that drives the player.
export function continuousDeckModule() {
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
}

export const NO_STRIP_SHOWN = (): boolean => false;

export function callbacks(overrides: Partial<AudioPlayerCallbacks> = {}): AudioPlayerCallbacks {
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

export function makeInfo(overrides: Partial<PlaybackInfo> = {}): PlaybackInfo {
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

export function takeInfo(id: string, mp3Path: string): PlaybackInfo {
	return makeInfo({ generation: makeGen({ id, mp3_path: mp3Path }) });
}

export function recoveryUrlOf(url: string): RegExp {
	const escaped = url.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	return new RegExp(`^${escaped}\\?recover=\\S+$`);
}

export function makeStreamManifest(): QueueStreamManifest {
	return {
		snapshot_id: 'snap',
		stream_url: '/shared/queue-streams/snap/audio',
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

export class FakeAudio {
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

export interface PlayerDoubles {
	fakeAudio: FakeAudio;
	createdAudios: FakeAudio[];
	fetchMock: ReturnType<typeof vi.fn>;
}

// The browser globals the player reaches for: the first <audio> it creates is
// `fakeAudio`, every later one (the second deck) lands in `createdAudios`.
export function stubPlayerGlobals(): PlayerDoubles {
	const doubles: PlayerDoubles = {
		fakeAudio: new FakeAudio(),
		createdAudios: [],
		fetchMock: vi.fn().mockResolvedValue({ ok: true, status: 200 })
	};
	vi.stubGlobal(
		'Audio',
		vi.fn(function () {
			const el = doubles.createdAudios.length === 0 ? doubles.fakeAudio : new FakeAudio();
			doubles.createdAudios.push(el);
			return el;
		})
	);
	vi.stubGlobal('MediaError', {
		MEDIA_ERR_ABORTED: 1,
		MEDIA_ERR_NETWORK: 2,
		MEDIA_ERR_DECODE: 3,
		MEDIA_ERR_SRC_NOT_SUPPORTED: 4
	});
	vi.stubGlobal('fetch', doubles.fetchMock);
	return doubles;
}

export function attachedDeck(): DeckDouble {
	const attached = continuousDecks.attached.at(-1);
	if (!attached) throw new Error('no deck was attached');
	return attached;
}

// What the newest deck holds, as [take, start offset, duration] in order.
export function holdTakes(...takes: [PlaybackInfo, number, number][]): void {
	attachedDeck().manifest = takes.map(([take, start_offset, duration]) => ({
		take,
		start_offset,
		duration
	}));
}
