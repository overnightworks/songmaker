import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync } from 'svelte';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { currentUser } from '$lib/stores/auth';
import { makeGeneration, makeSong } from '$lib/test-utils/factories';
import { followPlaybackForResume, savedPlayback, type ResumeQueueSource } from './playbackResume';

const LISTENER = { id: 'u-listener', username: 'listener', role: 'user' as const };
const OTHER_LISTENER = { id: 'u-other', username: 'other', role: 'user' as const };
const ALBUM_QUEUE: ResumeQueueSource = { type: 'album', albumId: 'a-resume' };

followPlaybackForResume({ queueSource: () => ALBUM_QUEUE, takeAfterCurrent: () => null });

function recordKey(userId: string): string {
	return `playbackResume:${userId}`;
}

function storedRecord(userId: string): unknown {
	return JSON.parse(localStorage.getItem(recordKey(userId)) ?? 'null');
}

// Another tab's logout removes the record; this tab hears of it only later,
// as a storage event, and may have ticked in between.
function logOutInAnotherTab(userId: string, beforeThisTabHears: () => void = () => {}): void {
	const key = recordKey(userId);
	const oldValue = localStorage.getItem(key);
	localStorage.removeItem(key);
	beforeThisTabHears();
	window.dispatchEvent(new StorageEvent('storage', { key, oldValue, newValue: null }));
}

function savedPoint(userId = LISTENER.id): { generationId: string; position: number } | null {
	const record = storedRecord(userId) as { generationId: string; position: number } | null;
	return record && { generationId: record.generationId, position: record.position };
}

function playTake(generationId: string, status: 'playing' | 'loading' = 'playing'): void {
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
	audioPlayer.status = status;
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

		expect(storedRecord(LISTENER.id)).toEqual({
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

	it('a take started under user A is never saved under user B', () => {
		playTake('g-shared-device');
		playTo(42);
		setPageVisibility('hidden');

		currentUser.set(OTHER_LISTENER);
		playTo(48);
		audioPlayer.status = 'paused';
		flushSync();
		setPageVisibility('hidden');

		expect(savedPoint(OTHER_LISTENER.id)).toBeNull();
		expect(savedPoint(LISTENER.id)).toEqual({ generationId: 'g-shared-device', position: 42 });
	});

	it("a take started under user B is saved under B's own record", () => {
		currentUser.set(OTHER_LISTENER);
		playTake('g-started-by-other');
		playTo(7);

		expect(savedPoint(OTHER_LISTENER.id)).toEqual({
			generationId: 'g-started-by-other',
			position: 7
		});
		expect(savedPoint(LISTENER.id)).toBeNull();
	});

	it("pause saves the element's current time", () => {
		playTake('g-paused');
		playTo(2.5);
		vi.spyOn(audioPlayer, 'getElement').mockReturnValue({
			currentTime: 2.75
		} as HTMLAudioElement);

		audioPlayer.status = 'paused';
		flushSync();

		expect(savedPoint()).toEqual({ generationId: 'g-paused', position: 2.75 });
	});

	it('saving reads storage at most once per window', () => {
		const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
			throw new DOMException('storage is full', 'QuotaExceededError');
		});
		const getItem = vi.spyOn(Storage.prototype, 'getItem');

		playTake('g-window');
		setItem.mockClear();
		getItem.mockClear();
		for (let second = 0.25; second < 5; second += 0.25) playTo(second);

		expect(setItem.mock.calls.length + getItem.mock.calls.length).toBe(0);
	});

	it('a logout in another tab stops this tab saving the record again', () => {
		playTake('g-two-tabs');

		logOutInAnotherTab(LISTENER.id, () => playTo(3));
		playTo(9);
		audioPlayer.status = 'paused';
		flushSync();
		setPageVisibility('hidden');
		playTake('g-two-tabs-next');

		expect(storedRecord(LISTENER.id)).toBeNull();
	});

	it('saves again once the user signs in anew after a logout in another tab', () => {
		playTake('g-signed-in-again');
		logOutInAnotherTab(LISTENER.id);

		currentUser.set({ ...LISTENER });
		playTo(9);

		expect(savedPoint()).toEqual({ generationId: 'g-signed-in-again', position: 9 });
	});

	it('saves nothing without a signed-in user', () => {
		currentUser.set(null);
		playTake('g-anonymous');
		setPageVisibility('hidden');

		expect(localStorage.length).toBe(0);
	});

	it("reads the signed-in user's saved take", () => {
		playTake('g-read-back');
		playTo(12);

		expect(savedPlayback()).toEqual({
			songId: 's-g-read-back',
			generationId: 'g-read-back',
			position: 12
		});
	});

	it.each([
		{ record: 'a damaged record', stored: '{"generationId": 7' },
		{ record: 'a record without a take', stored: '{"songId": "s-x", "position": 3}' },
		{
			record: 'a record with a negative position',
			stored: '{"songId": "s-x", "generationId": "g-x", "position": -1}'
		}
	])('$record reads as nothing saved', ({ stored }) => {
		localStorage.setItem(recordKey(LISTENER.id), stored);

		expect(savedPlayback()).toBeNull();
	});

	it('unreadable storage reads as nothing saved', () => {
		vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
			throw new DOMException('storage is blocked', 'SecurityError');
		});

		expect(savedPlayback()).toBeNull();
	});

	it('a restored take keeps its saved position while it loads', () => {
		playTake('g-before-the-kill');
		localStorage.setItem(
			recordKey(LISTENER.id),
			JSON.stringify({
				source: ALBUM_QUEUE,
				songId: 's-g-restored',
				generationId: 'g-restored',
				position: 42
			})
		);
		audioPlayer.current = null;
		audioPlayer.status = 'idle';
		flushSync();

		savedPlayback();
		playTake('g-restored', 'loading');
		setPageVisibility('hidden');

		expect(savedPoint()).toEqual({ generationId: 'g-restored', position: 42 });
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
		expect(localStorage.length).toBe(0);
	});
});
