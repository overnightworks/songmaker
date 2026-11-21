import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { audioPlayer, STALL_RECOVERY_MS } from './audioPlayer.svelte';
import {
	callbacks,
	makeInfo,
	makeStreamManifest,
	stubPlayerGlobals,
	type FakeAudio
} from './audioPlayer-test-fixtures';

let fakeAudio: FakeAudio;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
	vi.useFakeTimers();
	({ fakeAudio, fetchMock } = stubPlayerGlobals());
	audioPlayer.destroy();
	audioPlayer.swapCallbacks(callbacks());
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

function startPlayingAt(seconds: number): void {
	fakeAudio.currentTime = seconds;
	fakeAudio.paused = false;
	fakeAudio.fire('play');
	fakeAudio.fire('playing');
	fakeAudio.fire('timeupdate');
}

describe('a queue stream, REQ-PLAYER-20 and REQ-PLAYER-24 to REQ-PLAYER-28', () => {
	// Spec: REQ-PLAYER-20 -- a stream loaded without saying whether to play starts playing.
	it('plays a stream that is loaded without saying whether to play', () => {
		audioPlayer.loadStream(makeStreamManifest());
		fakeAudio.fire('canplay');

		expect(fakeAudio.playMock).toHaveBeenCalled();
		expect(audioPlayer.status).toBe('loading');
	});

	// Spec: REQ-PLAYER-24 -- moving to a track plays it when asked to or, if not told, when the stream was playing.
	it.each([
		{ ask: 'to play', opts: { autoplay: true }, playing: false, paused: false },
		{ ask: 'to stay paused', opts: { autoplay: false }, playing: true, paused: false },
		{ ask: 'nothing while it plays', opts: {}, playing: true, paused: false },
		{ ask: 'nothing while it is paused', opts: {}, playing: false, paused: true }
	])('goes to a track and, asked $ask, ends paused: $paused', ({ opts, playing, paused }) => {
		audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });
		fakeAudio.fire('canplay');
		fakeAudio.paused = !playing;

		expect(audioPlayer.seekToStreamTrack(1, opts)).toBe(true);

		expect(audioPlayer.current?.songTitle).toBe('Second');
		expect(fakeAudio.currentTime).toBe(10);
		expect(fakeAudio.paused).toBe(paused);
	});

	// Spec: REQ-PLAYER-24 -- moving to a track plays it when asked to or, if not told, when the stream was playing.
	it.each([
		{ ask: 'to play', opts: { autoplay: true }, plays: true },
		{ ask: 'to stay paused', opts: { autoplay: false }, plays: false }
	])('goes back a track and, asked $ask, plays: $plays', ({ opts, plays }) => {
		audioPlayer.loadStream(makeStreamManifest(), 1, { autoplay: false });
		fakeAudio.fire('canplay');
		fakeAudio.paused = true;

		expect(audioPlayer.prevStreamTrack(opts)).toBe(true);

		expect(audioPlayer.current?.songTitle).toBe('First');
		expect(fakeAudio.paused).toBe(!plays);
	});

	// Spec: REQ-PLAYER-25 -- Previous on the first track of a windowed stream goes nowhere.
	it('stays on the first track of a windowed stream when asked for the track before it', () => {
		audioPlayer.loadStream({ ...makeStreamManifest(), windowed: true }, 0, { autoplay: false });

		expect(audioPlayer.prevStreamTrack()).toBe(false);

		expect(audioPlayer.current?.songTitle).toBe('First');
	});

	// Spec: REQ-PLAYER-26 -- a stream that was buffering shows playing again once its position moves.
	it('shows a buffering stream as playing once its position moves', () => {
		audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });
		startPlayingAt(1);
		fakeAudio.fire('stalled');
		expect(audioPlayer.status).toBe('buffering');

		fakeAudio.currentTime = 2;
		fakeAudio.fire('timeupdate');

		expect(audioPlayer.status).toBe('playing');
	});

	// Spec: REQ-PLAYER-27 -- while the network is announced gone, a stream that fails waits for it and asks nothing of the server.
	it('waits for the network instead of probing or reloading a stream that fails while it is gone', async () => {
		audioPlayer.swapCallbacks(callbacks({ networkFailureIsAnnounced: () => true }));
		audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });
		startPlayingAt(12);
		const sourceBefore = fakeAudio.src;

		fakeAudio.error = { code: MediaError.MEDIA_ERR_NETWORK } as MediaError;
		fakeAudio.fire('error');
		await vi.advanceTimersByTimeAsync(0);

		expect(audioPlayer.status).toBe('buffering');
		expect(fetchMock).not.toHaveBeenCalled();
		expect(fakeAudio.src).toBe(sourceBefore);
	});

	// Spec: REQ-PLAYER-28 -- the answer to a check of a stream the player has left changes nothing.
	it('ignores the answer of a stream check that comes after another take was loaded', async () => {
		let answerProbe: (answer: { ok: boolean; status: number }) => void = () => {};
		fetchMock.mockReturnValueOnce(new Promise((resolve) => (answerProbe = resolve)));
		audioPlayer.loadStream(makeStreamManifest(), 0, { autoplay: false });
		startPlayingAt(12);
		fakeAudio.fire('stalled');
		await vi.advanceTimersByTimeAsync(STALL_RECOVERY_MS);
		audioPlayer.load(makeInfo({ songTitle: 'Next take' }), { autoplay: false });
		const sourceBefore = fakeAudio.src;

		answerProbe({ ok: true, status: 200 });
		await vi.advanceTimersByTimeAsync(0);

		expect(fakeAudio.src).toBe(sourceBefore);
		expect(audioPlayer.current?.songTitle).toBe('Next take');
	});
});
