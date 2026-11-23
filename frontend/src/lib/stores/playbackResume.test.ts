import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync } from 'svelte';
import { fetchPlaylist, fetchSong } from '#lib/api/client.ts';
import { ApiError, NetworkError } from '#lib/api/fetch.ts';
import type { GenerationItem } from '#lib/api/types.ts';
import { audioPlayer } from '#lib/services/audioPlayer.svelte.ts';
import { currentUser } from '#lib/stores/auth.ts';
import {
	makeAuthUser,
	makeGeneration,
	makePlaylistDetail,
	makePlaylistEntry,
	makeSong
} from '#lib/test-utils/factories.ts';
import {
	followPlaybackForResume,
	forgetPlaybackResume,
	loadSavedPlaylist,
	loadSavedTake,
	savedPlayback,
	type ResumeQueueSource,
	type SavedPlayback
} from './playbackResume';

vi.mock('#lib/api/client.ts', () => ({ fetchPlaylist: vi.fn(), fetchSong: vi.fn() }));

const LISTENER = makeAuthUser({ id: 'u-listener', username: 'listener', role: 'user' });
const OTHER_LISTENER = makeAuthUser({ id: 'u-other', username: 'other', role: 'user' });
const ALBUM_QUEUE: ResumeQueueSource = { type: 'album', albumId: 'a-resume' };

followPlaybackForResume({
	playsTheAppsTakes: () => true,
	queueSource: () => ALBUM_QUEUE,
	takeAfterCurrent: () => null
});

function recordKey(userId: string): string {
	return `playbackResume:${userId}`;
}

function logoutKey(userId: string): string {
	return `playbackLogout:${userId}`;
}

function storedRecord(userId: string): unknown {
	return JSON.parse(localStorage.getItem(recordKey(userId)) ?? 'null');
}

// Deliver the public storage boundary after a remote tab has published logout.
function logOutInAnotherTab(userId: string, beforeThisTabHears: () => void = () => {}): void {
	const key = logoutKey(userId);
	const oldValue = localStorage.getItem(key);
	const newValue = crypto.randomUUID();
	localStorage.removeItem(recordKey(userId));
	localStorage.setItem(key, newValue);
	beforeThisTabHears();
	window.dispatchEvent(
		new StorageEvent('storage', {
			key,
			oldValue,
			newValue,
			storageArea: localStorage
		})
	);
}

// jsdom has no media engine. Replace only its unimplemented platform methods;
// drive the real player's public load/pause API and the element's event boundary.
function loadBoundaryTake(): HTMLAudioElement {
	vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
	vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
	const song = makeSong();
	audioPlayer.load(
		{
			generation: makeGeneration({ song_id: song.id }),
			songId: song.id,
			songTitle: song.title,
			artist: song.artist,
			albumTitle: song.album_title,
			lyrics: null
		},
		{ autoplay: false }
	);
	audioPlayer.pause();
	flushSync();
	const element = audioPlayer.getElement();
	if (!element) throw new Error('Public load did not create an audio element');
	return element;
}

function advanceBoundaryTake(element: HTMLAudioElement): void {
	element.currentTime = 9;
	element.dispatchEvent(new Event('timeupdate'));
	flushSync();
	audioPlayer.pause();
	flushSync();
	setPageVisibility('hidden');
}

function savedPoint(userId = LISTENER.id): { generationId: string; position: number } | null {
	const record = storedRecord(userId) as { generationId: string; position: number } | null;
	return record && { generationId: record.generationId, position: record.position };
}

function playTake(
	generationId: string,
	status: 'playing' | 'loading' | 'error' = 'playing',
	songId = `s-${generationId}`
): void {
	const song = makeSong({ id: songId });
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
	audioPlayer.destroy();
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

	it("pause saves the take's position on the element clock", () => {
		playTake('g-paused');
		playTo(2.5);
		vi.spyOn(audioPlayer, 'currentTimeNow', 'get').mockReturnValue(2.75);

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

	it('1354_52_C2: a logout in another tab stops this tab saving the record again', () => {
		playTake('g-two-tabs');

		logOutInAnotherTab(LISTENER.id, () => playTo(3));
		playTo(9);
		audioPlayer.status = 'paused';
		flushSync();
		setPageVisibility('hidden');
		playTake('g-two-tabs-next');

		expect(storedRecord(LISTENER.id)).toBeNull();
	});

	it('1354_52_C3: saves again once the user signs in anew after a logout in another tab', () => {
		playTake('g-signed-in-again');
		logOutInAnotherTab(LISTENER.id);

		currentUser.set({ ...LISTENER });
		playTo(9);

		expect(savedPoint()).toEqual({ generationId: 'g-signed-in-again', position: 9 });
	});

	it.each([
		{ record: 'present', origin: 'originating' },
		{ record: 'absent', origin: 'originating' },
		{ record: 'present', origin: 'receiving' },
		{ record: 'absent', origin: 'receiving' }
	])(
		'1354_52_C2: $origin tab suppresses saves with current record $record',
		({ record, origin }) => {
			const element = loadBoundaryTake();
			expect(savedPoint()).not.toBeNull();
			if (record === 'absent') localStorage.removeItem(recordKey(LISTENER.id));
			const key = logoutKey(LISTENER.id);
			localStorage.setItem(key, 'previous-logout');

			if (origin === 'originating') forgetPlaybackResume(LISTENER.id);
			else logOutInAnotherTab(LISTENER.id);
			const marker = localStorage.getItem(key);
			expect(marker).not.toBeNull();
			expect(marker).not.toBe('previous-logout');
			advanceBoundaryTake(element);
			expect(savedPoint()).toBeNull();
			expect(localStorage.getItem(key)).toBe(marker);
			if (origin === 'originating') {
				forgetPlaybackResume(LISTENER.id);
				expect(localStorage.getItem(key)).not.toBe(marker);
			}
		}
	);

	it.each([
		{
			boundary: 'foreign viewer',
			key: logoutKey(OTHER_LISTENER.id),
			oldValue: null,
			newValue: 'logout',
			session: false
		},
		{
			boundary: 'current-record retirement',
			key: recordKey(LISTENER.id),
			oldValue: 'record',
			newValue: null,
			session: false
		},
		{
			boundary: 'removed marker',
			key: logoutKey(LISTENER.id),
			oldValue: 'logout',
			newValue: null,
			session: false
		},
		{
			boundary: 'unchanged marker',
			key: logoutKey(LISTENER.id),
			oldValue: 'logout',
			newValue: 'logout',
			session: false
		},
		{
			boundary: 'session storage',
			key: logoutKey(LISTENER.id),
			oldValue: null,
			newValue: 'logout',
			session: true
		}
	])(
		'1354_52_C3: $boundary does not suppress this viewer',
		({ key, oldValue, newValue, session }) => {
			const element = loadBoundaryTake();
			window.dispatchEvent(
				new StorageEvent('storage', {
					key,
					oldValue,
					newValue,
					storageArea: session ? sessionStorage : localStorage
				})
			);
			advanceBoundaryTake(element);
			expect(savedPoint()?.position).toBe(9);
		}
	);

	it('saves nothing without a signed-in user', () => {
		currentUser.set(null);
		playTake('g-anonymous');
		setPageVisibility('hidden');

		expect(localStorage).toHaveLength(0);
	});

	it("reads the signed-in user's saved take", () => {
		const songId = '7e1d2c3b-4a59-4f6e-8d7c-6b5a4f3e2d03';
		const generationId = '7e1d2c3b-4a59-4f6e-8d7c-6b5a4f3e2d04';
		playTake(generationId, 'playing', songId);
		playTo(12);

		expect(savedPlayback()).toEqual({ source: ALBUM_QUEUE, songId, generationId, position: 12 });
	});

	const WHOLE_RECORD = {
		source: ALBUM_QUEUE,
		songId: '7e1d2c3b-4a59-4f6e-8d7c-6b5a4f3e2d01',
		generationId: '7e1d2c3b-4a59-4f6e-8d7c-6b5a4f3e2d02',
		position: 3
	};

	it.each([
		{ queue: 'its song', source: { type: 'song' } },
		{ queue: 'an album', source: { type: 'album', albumId: 'a-resume' } },
		{
			queue: 'a playlist',
			source: { type: 'playlist', playlistId: '7e1d2c3b-4a59-4f6e-8d7c-6b5a4f3e2d05' }
		},
		{ queue: 'the library', source: { type: 'library', pool: 'picks', shuffle: true } }
	])('reads a record whose take played from $queue', ({ source }) => {
		localStorage.setItem(recordKey(LISTENER.id), JSON.stringify({ ...WHOLE_RECORD, source }));

		expect(savedPlayback()).toEqual({ ...WHOLE_RECORD, source });
	});

	it("never hands one user's saved take to another", () => {
		const songQueueRecord = { ...WHOLE_RECORD, source: { type: 'song' } };
		localStorage.setItem(recordKey(OTHER_LISTENER.id), JSON.stringify(songQueueRecord));

		expect(savedPlayback()).toBeNull();
	});

	it.each([
		{ record: 'a damaged record', stored: '{"generationId": 7' },
		{
			record: 'a record without a take',
			stored: JSON.stringify({ ...WHOLE_RECORD, generationId: undefined })
		},
		{
			record: 'a record without its queue',
			stored: JSON.stringify({ ...WHOLE_RECORD, source: undefined })
		},
		{
			record: 'a record naming a queue kind the app does not know',
			stored: JSON.stringify({ ...WHOLE_RECORD, source: { type: 'songs' } })
		},
		{
			record: 'a record naming an unknown library pool',
			stored: JSON.stringify({
				...WHOLE_RECORD,
				source: { type: 'library', pool: 'keeps', shuffle: false }
			})
		},
		{
			record: 'a record with a negative position',
			stored: JSON.stringify({ ...WHOLE_RECORD, position: -1 })
		}
	])('$record reads as nothing saved', ({ stored }) => {
		localStorage.setItem(recordKey(LISTENER.id), stored);

		expect(savedPlayback()).toBeNull();
	});

	describe('loading the saved take for a restore', () => {
		const PLAYLIST_RECORD = {
			...WHOLE_RECORD,
			source: { type: 'playlist', playlistId: 'b3a4c5d6-1e2f-4a3b-8c4d-5e6f7a8b9c0d' },
			savedAt: 1000
		} as const;
		const OTHER_PLAYLIST = 'c4b5d6e7-2f30-4b4c-9d5e-6f708192a3b4';

		function saveWholeRecord(record: object = WHOLE_RECORD): SavedPlayback {
			localStorage.setItem(recordKey(LISTENER.id), JSON.stringify(record));
			const saved = savedPlayback();
			if (saved === null) throw new Error('the record was not read');
			return saved;
		}

		const savedTake = makeGeneration({ id: WHOLE_RECORD.generationId });
		const songOf = (generations: GenerationItem[]) =>
			makeSong({ id: WHOLE_RECORD.songId, generations });

		it('finds a take that can still play, and keeps its record', async () => {
			const saved = saveWholeRecord();
			const song = songOf([savedTake]);
			vi.mocked(fetchSong).mockResolvedValueOnce(song);

			await expect(loadSavedTake(saved)).resolves.toEqual({ song, take: savedTake });

			expect(storedRecord(LISTENER.id)).not.toBeNull();
		});

		it.each([
			{ gone: 'a deleted song', answer: () => Promise.reject(new ApiError(404, 'gone', '/x')) },
			{ gone: 'a deleted take', answer: () => Promise.resolve(songOf([])) },
			{
				gone: 'an archived take',
				answer: () => Promise.resolve(songOf([{ ...savedTake, is_archived: true }]))
			},
			{
				gone: 'a take without audio',
				answer: () => Promise.resolve(songOf([{ ...savedTake, mp3_path: '' }]))
			}
		])('finds nothing and forgets the record naming $gone', async ({ answer }) => {
			const saved = saveWholeRecord();
			vi.mocked(fetchSong).mockImplementationOnce(answer);

			await expect(loadSavedTake(saved)).resolves.toBeNull();

			expect(storedRecord(LISTENER.id)).toBeNull();
		});

		it.each([
			{ failure: 'a song out of reach', error: new ApiError(403, 'no', '/x') },
			{ failure: 'a server error', error: new ApiError(503, 'down', '/x') },
			{
				failure: 'an unreachable server',
				error: new NetworkError('/x', new TypeError('Failed to fetch'))
			}
		])('finds nothing but keeps the record when the server answers $failure', async ({ error }) => {
			const saved = saveWholeRecord();
			vi.mocked(fetchSong).mockRejectedValueOnce(error);

			await expect(loadSavedTake(saved)).resolves.toBeNull();

			expect(storedRecord(LISTENER.id)).not.toBeNull();
		});

		it('forgets the record of a playlist the server no longer has, and keeps it on a server error', async () => {
			const saved = saveWholeRecord();
			vi.mocked(fetchPlaylist).mockRejectedValueOnce(new ApiError(503, 'down', '/x'));
			await expect(loadSavedPlaylist(saved, 'p-saved')).resolves.toBeNull();
			expect(storedRecord(LISTENER.id)).not.toBeNull();

			vi.mocked(fetchPlaylist).mockRejectedValueOnce(new ApiError(404, 'gone', '/x'));
			await expect(loadSavedPlaylist(saved, 'p-saved')).resolves.toBeNull();

			expect(storedRecord(LISTENER.id)).toBeNull();
		});

		it.each([
			{
				holds: 'the take',
				entries: [makePlaylistEntry({ generation_id: WHOLE_RECORD.generationId })],
				found: true,
				recordKept: true
			},
			{
				holds: 'other takes only',
				entries: [makePlaylistEntry({ generation_id: 'another-take' })],
				found: false,
				recordKept: false
			}
		])(
			'finds a playlist that holds $holds, and keeps its record only when it holds the take',
			async ({ entries, found, recordKept }) => {
				const saved = saveWholeRecord(PLAYLIST_RECORD);
				vi.mocked(fetchPlaylist).mockResolvedValueOnce(makePlaylistDetail({ entries }));

				const loaded = await loadSavedPlaylist(saved, PLAYLIST_RECORD.source.playlistId);

				expect({ found: loaded !== null, recordKept: storedRecord(LISTENER.id) !== null }).toEqual({
					found,
					recordKept
				});
			}
		);

		it.each([
			{ rewritten: 'from the song queue', record: { source: { type: 'song' } } },
			{ rewritten: 'at a later position', record: { position: PLAYLIST_RECORD.position + 20 } },
			{ rewritten: 'at a later time', record: { savedAt: PLAYLIST_RECORD.savedAt + 1 } },
			{
				rewritten: 'from another playlist',
				record: { source: { type: 'playlist', playlistId: OTHER_PLAYLIST } }
			}
		])(
			"keeps a record another tab rewrote for the same take $rewritten while its playlist's 404 was in flight",
			async ({ record }) => {
				const saved = saveWholeRecord(PLAYLIST_RECORD);
				const newerRecord = { ...PLAYLIST_RECORD, ...record };
				vi.mocked(fetchPlaylist).mockImplementationOnce(() => {
					localStorage.setItem(recordKey(LISTENER.id), JSON.stringify(newerRecord));
					return Promise.reject(new ApiError(404, 'gone', '/x'));
				});

				await loadSavedPlaylist(saved, PLAYLIST_RECORD.source.playlistId);

				expect(storedRecord(LISTENER.id)).toEqual(newerRecord);
			}
		);

		it("keeps the record of a user whose tab another user took over while the playlist's 404 was in flight", async () => {
			const saved = saveWholeRecord(PLAYLIST_RECORD);
			vi.mocked(fetchPlaylist).mockImplementationOnce(() => {
				currentUser.set(OTHER_LISTENER);
				localStorage.setItem(recordKey(OTHER_LISTENER.id), JSON.stringify(PLAYLIST_RECORD));
				return Promise.reject(new ApiError(404, 'gone', '/x'));
			});

			await loadSavedPlaylist(saved, PLAYLIST_RECORD.source.playlistId);

			expect(storedRecord(OTHER_LISTENER.id)).toEqual(PLAYLIST_RECORD);
			expect(storedRecord(LISTENER.id)).toEqual(PLAYLIST_RECORD);
		});

		it("keeps a record that names another take than the one found gone, as another tab's save", async () => {
			const saved = saveWholeRecord();
			const newerRecord = {
				...WHOLE_RECORD,
				generationId: '7e1d2c3b-4a59-4f6e-8d7c-6b5a4f3e2d09'
			};
			localStorage.setItem(recordKey(LISTENER.id), JSON.stringify(newerRecord));
			vi.mocked(fetchSong).mockRejectedValueOnce(new ApiError(404, 'gone', '/x'));

			await loadSavedTake(saved);

			expect(storedRecord(LISTENER.id)).toEqual(newerRecord);
		});
	});

	it('unreadable storage reads as nothing saved', () => {
		vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
			throw new DOMException('storage is blocked', 'SecurityError');
		});

		expect(savedPlayback()).toBeNull();
	});

	it.each(['loading', 'error'] as const)(
		'a restored take keeps its saved position while %s',
		(status) => {
			playTake('g-before-the-kill');
			localStorage.setItem(
				recordKey(LISTENER.id),
				JSON.stringify({ ...WHOLE_RECORD, position: 42 })
			);
			audioPlayer.current = null;
			audioPlayer.status = 'idle';
			flushSync();

			savedPlayback();
			playTake(WHOLE_RECORD.generationId, status, WHOLE_RECORD.songId);
			setPageVisibility('hidden');

			expect(savedPoint()).toEqual({ generationId: WHOLE_RECORD.generationId, position: 42 });
		}
	);

	it('with storage unavailable saves nothing and plays on silently', () => {
		vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
			throw new DOMException('storage is full', 'QuotaExceededError');
		});

		expect(() => {
			playTake('g-no-storage');
			playTo(6);
			setPageVisibility('hidden');
		}).not.toThrow();
		expect(localStorage).toHaveLength(0);
	});
});
