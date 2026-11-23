import { makeGeneration as makeGen } from '#lib/test-utils/factories.ts';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { audioPlayer, type PlaybackInfo } from './audioPlayer.svelte';
import { TakeNotAppended } from './continuousDeck';
import {
	attachedDeck,
	callbacks,
	continuousDecks,
	holdTakes,
	makeInfo,
	stubPlayerGlobals,
	takeInfo,
	type FakeAudio
} from './audioPlayer-test-fixtures';

vi.mock('./continuousDeck', async () =>
	(await import('./audioPlayer-test-fixtures')).continuousDeckModule()
);

let fakeAudio: FakeAudio;
let createdAudios: FakeAudio[];

beforeEach(() => {
	({ fakeAudio, createdAudios } = stubPlayerGlobals());
	vi.stubGlobal('MediaSource', vi.fn());
	continuousDecks.supported = true;
	continuousDecks.attached = [];
	audioPlayer.destroy();
	audioPlayer.swapCallbacks(callbacks());
});

afterEach(() => {
	continuousDecks.supported = false;
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

const first = makeInfo({
	generation: makeGen({ id: 'g1', mp3_path: 'a1/first.mp3', audio_duration_sec: 10 })
});
const second = makeInfo({
	generation: makeGen({ id: 'g2', mp3_path: 'a1/second.mp3', audio_duration_sec: 20 })
});
const third = takeInfo('g3', 'a1/third.mp3');

function playFirstWithSecondAppended(): void {
	audioPlayer.load(first);
	audioPlayer.preload(second);
	holdTakes([first, 0, 10], [second, 10, 20]);
	fakeAudio.fire('canplay');
	fakeAudio.fire('play');
	fakeAudio.fire('playing');
}

function refuse(take: PlaybackInfo, requestIndex: number): Promise<void> {
	attachedDeck().requests[requestIndex].fail(
		new TakeNotAppended(take, 'refused', 'the server answered 404')
	);
	return Promise.resolve();
}

describe('the continuous deck, REQ-PLAYER-20 to REQ-PLAYER-23', () => {
	// Spec: REQ-PLAYER-20 -- a take loaded without saying whether to play starts playing.
	it.each([
		{ ask: 'nothing', opts: {}, pausedBefore: true, playsAfter: true },
		{ ask: 'to stay paused', opts: { autoplay: false }, pausedBefore: false, playsAfter: false }
	])('moves to a take the deck holds and, asked $ask, plays: $playsAfter', (scenario) => {
		playFirstWithSecondAppended();
		if (scenario.pausedBefore) audioPlayer.pause();
		fakeAudio.paused = scenario.pausedBefore;

		audioPlayer.load(second, scenario.opts);

		expect(audioPlayer.current).toBe(second);
		expect(fakeAudio.paused).toBe(!scenario.playsAfter);
	});

	// Spec: REQ-PLAYER-21 -- where the deck holds no take at the playhead, the position follows the audio clock.
	it('follows the audio clock while the deck holds no take at the playhead', () => {
		playFirstWithSecondAppended();
		holdTakes();

		fakeAudio.currentTime = 3;
		fakeAudio.fire('timeupdate');

		expect(audioPlayer.currentTime).toBe(3);
	});

	// Spec: REQ-PLAYER-21 -- a load while the deck holds no take at the playhead starts a fresh deck.
	it('starts a fresh deck for a load while the deck holds no take at the playhead', () => {
		audioPlayer.load(first);
		const left = attachedDeck();

		audioPlayer.load(second);

		expect(continuousDecks.attached).toHaveLength(2);
		expect(left.closed).toBe(true);
		expect(audioPlayer.current).toBe(second);
	});

	// Spec: REQ-PLAYER-22 -- a failure of a deck the player has left changes nothing the listener hears or sees.
	it.each([
		{ failure: 'a refused take', error: new TakeNotAppended(second, 'refused', 'answered 404') },
		{ failure: 'a broken deck', error: new Error('source buffer broke') }
	])('ignores $failure reported by a deck the player has left', async ({ error }) => {
		const onTakeSkipped = vi.fn();
		audioPlayer.swapCallbacks(callbacks({ onTakeSkipped }));
		audioPlayer.load(first);
		audioPlayer.preload(second);
		const left = attachedDeck();
		audioPlayer.load(third, { restart: true });

		left.requests[1].fail(error);
		await Promise.resolve();

		expect(onTakeSkipped).not.toHaveBeenCalled();
		expect(continuousDecks.attached).toHaveLength(2);
		expect(fakeAudio.src).toBe('');
		expect(audioPlayer.current).toBe(third);
	});

	// Spec: REQ-PLAYER-23 -- a refused take ahead is skipped, and the take after it is appended in its place only while it was the last one handed to the deck.
	it('appends the take after a refused one in its place when the refused one was handed last', async () => {
		const onTakeSkipped = vi.fn();
		audioPlayer.swapCallbacks(
			callbacks({ onTakeSkipped, takeAfter: (take) => (take === second ? third : null) })
		);
		audioPlayer.load(first);
		audioPlayer.preload(second);

		await refuse(second, 1);

		expect(onTakeSkipped).toHaveBeenCalledWith(second);
		expect(attachedDeck().requests.map((request) => request.take)).toEqual([first, second, third]);
	});

	it('appends nothing in place of a refused take that nothing follows', async () => {
		const onTakeSkipped = vi.fn();
		audioPlayer.swapCallbacks(callbacks({ onTakeSkipped, takeAfter: () => null }));
		audioPlayer.load(first);
		audioPlayer.preload(second);

		await refuse(second, 1);

		expect(onTakeSkipped).toHaveBeenCalledWith(second);
		expect(attachedDeck().requests.map((request) => request.take)).toEqual([first, second]);
	});

	it('appends nothing in place of a refused take once another take was handed behind it', async () => {
		const onTakeSkipped = vi.fn();
		const takeAfter = vi.fn(() => third);
		audioPlayer.swapCallbacks(callbacks({ onTakeSkipped, takeAfter }));
		audioPlayer.load(first);
		audioPlayer.preload(second);
		audioPlayer.preload(third);

		await refuse(second, 1);

		expect(onTakeSkipped).toHaveBeenCalledWith(second);
		expect(attachedDeck().requests.map((request) => request.take)).toEqual([first, second, third]);
	});

	it('gives up the take held ahead once no take is to follow the playing one, and only once', () => {
		playFirstWithSecondAppended();

		audioPlayer.withdrawPreload();
		audioPlayer.withdrawPreload();

		expect(attachedDeck().drops).toBe(1);
	});

	it('takes the standby take back when the queue plays on two decks', () => {
		continuousDecks.supported = false;
		audioPlayer.load(first);
		audioPlayer.preload(second);
		const standby = createdAudios.at(-1);

		audioPlayer.withdrawPreload();

		expect(standby?.src).toBe('');
	});
});
