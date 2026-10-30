import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from 'vitest';
import type { QueueStreamManifest, SharedAlbumSongPayload, WhisperCue } from '#lib/api/types.ts';
import {
	reportResourceStreamReachable,
	resetConnectivityForTests
} from '#lib/stores/connectivity.ts';
import { audioPlayer, type AudioPlayerCallbacks } from '#lib/services/audioPlayer.svelte.ts';
import type { PlaybackInfo } from '#lib/services/playbackTypes.ts';
import {
	fromSharedAlbum,
	fromSharedSong,
	trackPlaybackInfo,
	type SharedCollectionView
} from './sharedCollection';
import { SharePlayback } from './sharePlayback.svelte';

class FakeAudio {
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

function albumView(slug = 'slug'): SharedCollectionView {
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

function songView(): SharedCollectionView {
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

// A take of the listener's own library, playing in the signed-in app when
// they followed a share link.
function appTake(): PlaybackInfo {
	const view = albumView();
	const take = trackPlaybackInfo(view, view.tracks[0]);
	return {
		...take,
		songId: 'private-song',
		songTitle: 'Private Draft',
		generation: { ...take.generation, id: 'private-take', audio_duration_sec: 240 }
	};
}

const NO_CALLBACKS: AudioPlayerCallbacks = {
	onEnded: null,
	onPlaybackStarted: null,
	onAuthLost: null,
	onStreamRebuild: null,
	onCurrentChange: null,
	networkFailureIsAnnounced: () => false
};

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
	audioPlayer.swapCallbacks(NO_CALLBACKS);
});

afterEach(() => {
	resetConnectivityForTests();
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

	it("drops the take the app was playing, and the app's own callbacks hear it go", async () => {
		const appHeard = vi.fn();
		audioPlayer.swapCallbacks({ ...NO_CALLBACKS, onCurrentChange: appHeard });
		audioPlayer.loadUrl(appTake(), '/audio/private-take.mp3', { startAt: 75 });
		fakeAudio.fire('canplay');
		await vi.waitFor(() => expect(audioPlayer.status).toBe('playing'));

		const playback = new SharePlayback();
		playback.start(songView(), null);

		expect({
			current: audioPlayer.current,
			time: audioPlayer.currentTime,
			duration: audioPlayer.duration,
			sounding: !fakeAudio.paused,
			appHeard: appHeard.mock.lastCall
		}).toEqual({ current: null, time: 0, duration: 0, sounding: false, appHeard: [null] });
		playback.stop();
	});
});

describe('a seek before the first Play', () => {
	it('readies the track there, paused, and Play starts it there', () => {
		const playback = new SharePlayback();
		playback.start(songView(), null);

		playback.seek(60);
		const readied = {
			shown: audioPlayer.currentTime,
			sounding: fakeAudio.playMock.mock.calls.length
		};
		playback.play();
		fakeAudio.fire('loadedmetadata');
		fakeAudio.fire('canplay');

		expect({
			readied,
			startedAt: fakeAudio.currentTime,
			played: fakeAudio.playMock.mock.calls.length
		}).toEqual({
			readied: { shown: 60, sounding: 0 },
			startedAt: 60,
			played: 1
		});
		playback.stop();
	});

	it('readies a stream at that point of its first track, without a sound', async () => {
		const fetchStream = vi.fn().mockResolvedValue(streamManifest(false));
		const playback = new SharePlayback();
		playback.start(albumView(), fetchStream);

		playback.seek(4);
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));
		fakeAudio.fire('loadedmetadata');

		expect({ at: fakeAudio.currentTime, played: fakeAudio.playMock.mock.calls.length }).toEqual({
			at: 4,
			played: 0
		});
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

	it('#1374 rule 7: next and prev stop at the ends in classic mode instead of wrapping', () => {
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, null);

		playback.toggle(view.tracks[1]);
		fakeAudio.fire('canplay');
		const atLast = { canNext: playback.canNext, canPrev: playback.canPrev };
		playback.next();
		const afterNextAtLast = playback.currentTrack?.key;
		playback.prev();
		const afterPrev = playback.currentTrack?.key;
		const atFirst = { canNext: playback.canNext, canPrev: playback.canPrev };
		playback.prev();

		expect(atLast).toEqual({ canNext: false, canPrev: true });
		expect(afterNextAtLast).toBe('s2');
		expect(afterPrev).toBe('s1');
		expect(atFirst).toEqual({ canNext: true, canPrev: false });
		expect(playback.currentTrack?.key).toBe('s1');
		playback.stop();
	});
});

describe('the end of a share', () => {
	function playToTheEnd(view: SharedCollectionView, trackIndex = 0): SharePlayback {
		const playback = new SharePlayback();
		playback.start(view, null);
		playback.toggle(view.tracks[trackIndex]);
		fakeAudio.fire('canplay');
		fakeAudio.fire('playing');
		fakeAudio.fire('ended');
		return playback;
	}

	it.each([
		{ share: 'a single song', view: songView, ended: true, next: 'single' },
		{ share: 'an album track with one after it', view: albumView, ended: false, next: 's2' }
	])('$share: ended is $ended once its track runs out', ({ view, ended, next }) => {
		const playback = playToTheEnd(view());

		expect(playback.ended).toBe(ended);
		expect(playback.currentTrack?.key).toBe(next);
		playback.stop();
	});

	it('#1374 rule 7: an album ends at its last track in classic mode, even shuffled', () => {
		const view = albumView();
		const playback = new SharePlayback();
		playback.start(view, null);
		playback.toggle(view.tracks[0]);
		playback.setShuffle(true);
		const last = playback.queue.items.at(-1);
		playback.jump(playback.queue.items.length - 1);
		fakeAudio.fire('canplay');
		fakeAudio.fire('playing');
		fakeAudio.fire('ended');

		expect(playback.ended).toBe(true);
		expect(playback.currentTrack?.key).toBe(last?.key);
		expect(playback.canNext).toBe(false);
		playback.stop();
	});

	it('#1374 rule 7: nothing is up next at the last song, since the album does not wrap', () => {
		const view = albumView();
		const playback = new SharePlayback();
		playback.start(view, null);

		playback.toggle(view.tracks[0]);
		const upNextAtFirst = playback.queue.upNext?.key;
		playback.toggle(view.tracks[1]);

		expect(upNextAtFirst).toBe('s2');
		expect(playback.queue.upNext).toBeNull();
		playback.stop();
	});

	it('#1374 rule 7: Play again on an ended album starts its first song', () => {
		const view = albumView();
		const playback = playToTheEnd(view, 1);

		playback.play();

		expect(playback.ended).toBe(false);
		expect(playback.currentTrack?.key).toBe('s1');
		expect(audioPlayer.current?.songId).toBe('s1');
		playback.stop();
	});

	it('plays an ended share again from the start of its first track', () => {
		const playback = playToTheEnd(songView());

		playback.play();

		expect(playback.ended).toBe(false);
		expect(audioPlayer.currentTime).toBe(0);
		expect(audioPlayer.transport).toBe('loading');
		playback.stop();
	});

	it('leaves the end on a seek, so Play resumes where the listener put it', () => {
		const playback = playToTheEnd(songView());
		const reload = vi.spyOn(fakeAudio, 'load');

		playback.seek(30);
		playback.play();

		expect(playback.ended).toBe(false);
		expect(fakeAudio.currentTime).toBe(30);
		expect(reload).not.toHaveBeenCalled();
		expect(fakeAudio.playMock).toHaveBeenCalled();
		playback.stop();
	});
});

describe('a failed take offline', () => {
	it('still names the failure, because a share shows no offline strip to say it', async () => {
		vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, null);
		playback.toggle(view.tracks[0]);
		reportResourceStreamReachable(false);

		fakeAudio.fire('error');
		await new Promise((resolve) => setTimeout(resolve, 0));

		expect(audioPlayer.status).toBe('error');
		expect(audioPlayer.error).toBe('Playback failed. Press Retry.');
		playback.stop();
	});
});

describe('stream playback', () => {
	it('a share without shuffle uses its stream', async () => {
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

	it.each([false, true])(
		'#1374 rule 7: a stream served as windowed=%s ends at its last track instead of wrapping',
		async (windowed) => {
			const fetchStream = vi.fn().mockResolvedValue(streamManifest(windowed));
			const playback = new SharePlayback();
			const view = albumView();
			playback.start(view, fetchStream);

			playback.jump(1);
			await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));
			const canNextAtLast = playback.canNext;
			fakeAudio.fire('ended');

			expect(canNextAtLast).toBe(false);
			expect(playback.ended).toBe(true);
			expect(playback.currentTrack?.key).toBe('s2');
			playback.stop();
		}
	);

	it('#1374 rule 7: Play again after a stream album ended starts its first song', async () => {
		const fetchStream = vi.fn().mockResolvedValue(streamManifest(false));
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, fetchStream);
		playback.jump(1);
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));
		fakeAudio.fire('ended');

		playback.play();

		await vi.waitFor(() => expect(playback.currentTrack?.key).toBe('s1'));
		expect(playback.ended).toBe(false);
		playback.stop();
	});

	it('falls back to classic playback when the stream fetch fails', async () => {
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

describe('a track still waiting on its stream when the share gives the player back', () => {
	// The share's stream request, answered only once the test says so.
	function heldStream() {
		const settle = { answer: (_manifest: QueueStreamManifest) => {}, fail: (_err: Error) => {} };
		const fetchStream = vi.fn(
			() =>
				new Promise<QueueStreamManifest>((resolve, reject) => {
					settle.answer = resolve;
					settle.fail = reject;
				})
		);
		return { fetchStream, settle };
	}

	const settlings = [
		{
			stream: 'arrives',
			settle: (held: ReturnType<typeof heldStream>) => held.settle.answer(streamManifest(false))
		},
		{
			stream: 'fails',
			settle: (held: ReturnType<typeof heldStream>) => held.settle.fail(new Error('network'))
		}
	];

	it.each(settlings)('loads nothing over the app once that stream $stream', async ({ settle }) => {
		const app: AudioPlayerCallbacks = { ...NO_CALLBACKS };
		audioPlayer.swapCallbacks(app);
		const held = heldStream();
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, held.fetchStream);
		playback.toggle(view.tracks[0]);
		await vi.waitFor(() => expect(held.fetchStream).toHaveBeenCalled());

		playback.stop();
		audioPlayer.loadUrl(appTake(), '/audio/private-take.mp3', { autoplay: false });
		settle(held);
		await new Promise((resolve) => setTimeout(resolve, 0));

		expect({
			holds: audioPlayer.current?.songTitle,
			mode: audioPlayer.mode,
			src: fakeAudio.src
		}).toEqual({ holds: 'Private Draft', mode: 'classic', src: '/audio/private-take.mp3' });
	});

	// A page that opens another share keeps its SharePlayback and starts it
	// again, so the earlier share's request settles into the same instance:
	// share B, with a stream of its own, started right after share A stopped.
	function startShareB(playback: SharePlayback) {
		const fetchStreamB = vi
			.fn()
			.mockResolvedValue({ ...streamManifest(false), stream_url: '/share-b-stream.mp3' });
		playback.start(albumView('share-b'), fetchStreamB);
		return fetchStreamB;
	}

	// What B shows once A's request settled, and what B's own Play then plays.
	async function shareBOnceASettled(
		playback: SharePlayback,
		fetchStreamB: ReturnType<typeof startShareB>,
		settleA: () => void
	) {
		settleA();
		await new Promise((resolve) => setTimeout(resolve, 0));
		const onceAHasSettled = {
			holds: audioPlayer.current?.songTitle ?? null,
			src: fakeAudio.src,
			rowDurations: playback.queueRows.map((row) => row.durationSec)
		};
		playback.play();
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));
		return {
			onceAHasSettled,
			bPlays: { holds: audioPlayer.current?.songTitle, src: fakeAudio.src },
			bAskedForItsStream: fetchStreamB.mock.calls.length
		};
	}

	const SHARE_B_ALONE = {
		onceAHasSettled: { holds: null, src: '', rowDurations: [128, 96] },
		bPlays: { holds: 'First', src: '/share-b-stream.mp3' },
		bAskedForItsStream: 1
	};

	it.each(settlings)(
		'leaves the next share alone, in the player and in its stream, once that stream $stream',
		async ({ settle }) => {
			const held = heldStream();
			const playback = new SharePlayback();
			const shareA = albumView('share-a');
			playback.start(shareA, held.fetchStream);
			playback.toggle(shareA.tracks[0]);
			await vi.waitFor(() => expect(held.fetchStream).toHaveBeenCalled());
			playback.stop();
			const fetchStreamB = startShareB(playback);

			const seen = await shareBOnceASettled(playback, fetchStreamB, () => settle(held));

			expect(seen).toEqual(SHARE_B_ALONE);
			playback.stop();
		}
	);

	it('leaves the next share alone once a rebuild of the earlier stream arrives', async () => {
		const rebuild = heldStream();
		const fetchStreamA = vi
			.fn()
			.mockResolvedValueOnce(streamManifest(false))
			.mockImplementationOnce(rebuild.fetchStream);
		const playback = new SharePlayback();
		const shareA = albumView('share-a');
		playback.start(shareA, fetchStreamA);
		playback.toggle(shareA.tracks[0]);
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }));
		fakeAudio.currentTime = 4;
		fakeAudio.fire('timeupdate');
		fakeAudio.fire('error');
		await vi.waitFor(() => expect(rebuild.fetchStream).toHaveBeenCalled());
		playback.stop();
		const fetchStreamB = startShareB(playback);

		const seen = await shareBOnceASettled(playback, fetchStreamB, () =>
			rebuild.settle.answer({ ...streamManifest(false), stream_url: '/share-a-fresh.mp3' })
		);

		expect(seen).toEqual(SHARE_B_ALONE);
		playback.stop();
	});
});

describe('shuffle', () => {
	it('drops out of stream mode to classic per-track playback, keeping the playing track first', async () => {
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
		audioPlayer.swapCallbacks({ ...NO_CALLBACKS, onEnded: previousOnEnded });
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

describe('the lock screen', () => {
	function recordLockScreenTitles(): (string | null)[] {
		const titles: (string | null)[] = [];
		const mediaSession = {};
		Object.defineProperty(mediaSession, 'metadata', {
			set: (metadata: MediaMetadataInit | null) => titles.push(metadata?.title ?? null)
		});
		Object.defineProperty(navigator, 'mediaSession', { value: mediaSession, configurable: true });
		vi.stubGlobal(
			'MediaMetadata',
			vi.fn(function (init: MediaMetadataInit) {
				return init;
			})
		);
		onTestFinished(() => {
			Reflect.deleteProperty(navigator, 'mediaSession');
		});
		return titles;
	}

	it('defect:#1374 names the playing song, and goes blank when the share stops', () => {
		const titles = recordLockScreenTitles();
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, null);

		playback.toggle(view.tracks[1]);
		playback.stop();

		expect(titles.at(-2)).toBe('Second');
		expect(titles.at(-1)).toBeNull();
	});

	it('defect:#1374 names the playing song in stream mode too', async () => {
		const titles = recordLockScreenTitles();
		const playback = new SharePlayback();
		playback.start(albumView(), vi.fn().mockResolvedValue(streamManifest(false)));

		playback.jump(1);
		await vi.waitFor(() => expect(audioPlayer.mode).toBe('stream'));

		expect(titles).toContain('Second');
		playback.stop();
	});

	it('defect:#1374 leaves the lock screen to the app that took the player back', () => {
		const titles = recordLockScreenTitles();
		const playback = new SharePlayback();
		const view = albumView();
		playback.start(view, null);
		playback.toggle(view.tracks[0]);
		audioPlayer.swapCallbacks(NO_CALLBACKS);
		const written = titles.length;

		playback.stop();

		expect(titles).toHaveLength(written);
	});
});
