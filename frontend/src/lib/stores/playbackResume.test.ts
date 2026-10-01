import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync } from 'svelte';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { currentUser } from '$lib/stores/auth';
import { makeGeneration, makeSong } from '$lib/test-utils/factories';
import {
	followPlaybackForResume,
	readPlaybackResume,
	type ResumeQueueSource
} from './playbackResume';

const LISTENER = { id: 'u-listener', username: 'listener', role: 'user' as const };
const OTHER_LISTENER = { id: 'u-other', username: 'other', role: 'user' as const };
const ALBUM_QUEUE: ResumeQueueSource = { type: 'album', albumId: 'a-resume' };

followPlaybackForResume(() => ALBUM_QUEUE);

function playTake(generationId: string): void {
	const song = makeSong({ id: `s-${generationId}` });
	audioPlayer.current = {
		generation: makeGeneration({ id: generationId, song_id: song.id }),
		songId: song.id,
		songTitle: song.title,
		artist: song.artist,
		albumTitle: song.album_title,
		lyrics: null
	};
	audioPlayer.currentTime = 0;
	audioPlayer.status = 'playing';
	flushSync();
}

function playTo(seconds: number): void {
	audioPlayer.currentTime = seconds;
	flushSync();
}

function setPageVisibility(state: DocumentVisibilityState): void {
	Object.defineProperty(document, 'visibilityState', { configurable: true, value: state });
	document.dispatchEvent(new Event('visibilitychange'));
}

function savedPoint(): { generationId: string; position: number } | null {
	const record = readPlaybackResume();
	return record && { generationId: record.generationId, position: record.position };
}

beforeEach(() => {
	currentUser.set(LISTENER);
});

afterEach(() => {
	vi.restoreAllMocks();
	currentUser.set(null);
	audioPlayer.current = null;
	audioPlayer.currentTime = 0;
	audioPlayer.status = 'idle';
	flushSync();
	setPageVisibility('visible');
	localStorage.clear();
});

describe('playback resume record', () => {
	it('saves take and position when the page hides', () => {
		playTake('g-hide');
		playTo(3.5);

		setPageVisibility('hidden');

		expect(readPlaybackResume()).toEqual({
			source: ALBUM_QUEUE,
			songId: 's-g-hide',
			generationId: 'g-hide',
			position: 3.5,
			savedAt: expect.any(Number)
		});
	});

	it('saves on a take change and on pause', () => {
		playTake('g-first');
		expect(savedPoint()).toEqual({ generationId: 'g-first', position: 0 });

		playTo(2.5);
		audioPlayer.status = 'paused';
		flushSync();
		expect(savedPoint()).toEqual({ generationId: 'g-first', position: 2.5 });

		playTake('g-second');
		expect(savedPoint()).toEqual({ generationId: 'g-second', position: 0 });
	});

	it('saves about every 5 s of playback, not on every tick', () => {
		playTake('g-progress');

		playTo(4);
		expect(savedPoint()).toEqual({ generationId: 'g-progress', position: 0 });

		playTo(5.25);
		expect(savedPoint()).toEqual({ generationId: 'g-progress', position: 5.25 });
	});

	it("another user's record is never read", () => {
		playTake('g-mine');
		playTo(42);
		setPageVisibility('hidden');

		currentUser.set(OTHER_LISTENER);
		expect(readPlaybackResume()).toBeNull();

		playTake('g-theirs');
		expect(savedPoint()).toEqual({ generationId: 'g-theirs', position: 0 });

		currentUser.set(LISTENER);
		expect(savedPoint()).toEqual({ generationId: 'g-mine', position: 42 });
	});

	it('saves nothing without a signed-in user', () => {
		currentUser.set(null);
		playTake('g-anonymous');
		setPageVisibility('hidden');

		currentUser.set(LISTENER);
		expect(readPlaybackResume()).toBeNull();
	});

	it('reads a damaged record as nothing', () => {
		playTake('g-damaged');
		expect(readPlaybackResume()).not.toBeNull();
		const listenerKeys = Object.keys(localStorage).filter((key) => key.includes(LISTENER.id));
		for (const key of listenerKeys) localStorage.setItem(key, '{"generationId": 7}');

		expect(readPlaybackResume()).toBeNull();
	});

	it('with storage unavailable saves nothing and plays on silently', () => {
		vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
			throw new DOMException('storage is full', 'QuotaExceededError');
		});

		expect(() => {
			playTake('g-no-storage');
			playTo(6);
			setPageVisibility('hidden');
		}).not.toThrow();
		expect(readPlaybackResume()).toBeNull();

		vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
			throw new DOMException('storage is blocked', 'SecurityError');
		});
		expect(readPlaybackResume()).toBeNull();
	});
});
