import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { audioPlayer, STALL_RECOVERY_MS } from './audioPlayer.svelte';
import {
	callbacks,
	makeInfo,
	recoveryUrlOf,
	stubPlayerGlobals,
	takeInfo,
	type FakeAudio
} from './audioPlayer-test-fixtures';

vi.mock('./continuousDeck', async () =>
	(await import('./audioPlayer-test-fixtures')).continuousDeckModule()
);

let fakeAudio: FakeAudio;

beforeEach(() => {
	vi.useFakeTimers();
	({ fakeAudio } = stubPlayerGlobals());
	audioPlayer.destroy();
	audioPlayer.swapCallbacks(callbacks());
});

afterEach(() => {
	vi.useRealTimers();
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe('one take on the element', () => {
	describe('before its data has loaded', () => {
		beforeEach(() => {
			audioPlayer.load(makeInfo(), { autoplay: false });
		});

		it('shows no length for a take whose length the browser cannot tell', () => {
			fakeAudio.duration = Number.NaN;

			fakeAudio.fire('loadedmetadata');

			expect(audioPlayer.duration).toBe(0);
		});

		it('keeps the length it showed when the browser cannot tell the length of a take that can play', () => {
			const shown = audioPlayer.duration;
			fakeAudio.duration = Number.NaN;

			fakeAudio.fire('canplay');

			expect(audioPlayer.duration).toBe(shown);
		});

		it('shows a paused take that can play as playing once its element runs', () => {
			fakeAudio.paused = false;

			fakeAudio.fire('canplay');

			expect(audioPlayer.status).toBe('playing');
		});
	});

	// Spec: REQ-PLAYER-29 -- a stalled take is fetched again only while it still waits for its data.
	it('leaves a ready take alone when its element reports a stall', () => {
		audioPlayer.load(makeInfo(), { autoplay: false });
		fakeAudio.fire('canplay');
		const source = fakeAudio.src;

		fakeAudio.fire('stalled');
		vi.advanceTimersByTime(2 * STALL_RECOVERY_MS);

		expect({ status: audioPlayer.status, source: fakeAudio.src }).toEqual({
			status: 'ready',
			source
		});
	});

	// Spec: REQ-PLAYER-29 -- a stalled take is fetched again only while it still waits for its data.
	it('does not reload a take that began playing before its stall check came', () => {
		audioPlayer.load(makeInfo());
		const source = fakeAudio.src;

		fakeAudio.fire('play');
		vi.advanceTimersByTime(2 * STALL_RECOVERY_MS);

		expect({ status: audioPlayer.status, source: fakeAudio.src }).toEqual({
			status: 'playing',
			source
		});
	});

	// Spec: REQ-PLAYER-29 -- the address a stalled take is fetched at keeps the query it carried.
	it('fetches a stalled take at a URL with a query again, keeping the query', () => {
		audioPlayer.loadUrl(makeInfo(), '/shared/s/audio?token=abc');
		fakeAudio.fire('play');
		fakeAudio.fire('waiting');

		vi.advanceTimersByTime(STALL_RECOVERY_MS);

		expect(fakeAudio.src).toMatch(/^\/shared\/s\/audio\?token=abc&recover=\S+$/);
	});

	it('fetches a stalled take at a URL without a query again with a query of its own', () => {
		audioPlayer.load(makeInfo());
		fakeAudio.fire('play');
		fakeAudio.fire('waiting');

		vi.advanceTimersByTime(STALL_RECOVERY_MS);

		expect(fakeAudio.src).toMatch(recoveryUrlOf('/audio/a1/song_v1.mp3'));
	});

	describe('a take the second deck stands ready with', () => {
		// Spec: REQ-PLAYER-20 -- a take loaded without saying whether to play starts playing.
		it('plays when it was preloaded before anything played', () => {
			const preloaded = takeInfo('g1', 'a1/first.mp3');
			audioPlayer.preload(preloaded);
			fakeAudio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;

			audioPlayer.load(preloaded);

			expect(audioPlayer.getElement()).toBe(fakeAudio);
			expect(audioPlayer.current).toBe(preloaded);
			expect(fakeAudio.playMock).toHaveBeenCalledOnce();
		});

		it('shows no length when its element cannot tell it', () => {
			const preloaded = takeInfo('g1', 'a1/first.mp3');
			audioPlayer.preload(preloaded);
			fakeAudio.readyState = HTMLMediaElement.HAVE_FUTURE_DATA;
			fakeAudio.duration = Number.NaN;

			audioPlayer.load(preloaded, { autoplay: false });

			expect(audioPlayer.duration).toBe(0);
		});
	});

	it('stays idle when a play request is refused after the take was unloaded', async () => {
		audioPlayer.load(makeInfo());
		fakeAudio.error = { code: MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED } as MediaError;
		fakeAudio.fire('canplay');

		audioPlayer.unload();
		await vi.advanceTimersByTimeAsync(0);

		expect({ status: audioPlayer.status, error: audioPlayer.error }).toEqual({
			status: 'idle',
			error: null
		});
	});
});
