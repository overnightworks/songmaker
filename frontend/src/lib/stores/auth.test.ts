import { afterEach, describe, expect, it, vi, beforeEach } from 'vitest';
import { flushSync } from 'svelte';
import { get } from 'svelte/store';

const mockFetchMe = vi.fn();
const mockApiLogin = vi.fn();
const mockApiLogout = vi.fn();
const mockStopLibraryResourceSync = vi.fn();
const mockFetchLibraryContinue = vi.fn();

vi.mock('$lib/api/client', async () => {
	const { ApiError } = await vi.importActual<typeof import('$lib/api/client')>('$lib/api/client');
	return {
		ApiError,
		fetchMe: (...args: unknown[]) => mockFetchMe(...args),
		login: (...args: unknown[]) => mockApiLogin(...args),
		logout: (...args: unknown[]) => mockApiLogout(...args)
	};
});

vi.mock('$lib/api/library', () => ({
	fetchLibraryContinue: (...args: unknown[]) => mockFetchLibraryContinue(...args)
}));

vi.mock('$lib/stores/resourceSync', () => ({
	stopLibraryResourceSync: (...args: unknown[]) => mockStopLibraryResourceSync(...args)
}));

import {
	currentUser,
	authLoading,
	authError,
	authCheckError,
	authCheckUnreachable,
	authNotice,
	isAdmin,
	checkAuth,
	classifyAuthFailure,
	login,
	logout,
	clearAuth,
	resetAuthForTests
} from './auth';
import { offline, resetConnectivityForTests } from './connectivity';
import {
	AUTH_CHECK_RETURN_PROBE_INTERVAL_MS,
	AUTH_SESSION_EXPIRED_DETAIL
} from '$lib/constants/auth';
import { ApiError } from '$lib/api/client';
import { NetworkError } from '$lib/api/fetch';
import { playlistList, selectedPlaylistDetail } from '$lib/stores/playlists';
import { generationFailures } from '$lib/stores/jobs';
import { ensureRecentWorkRead, lastWorkByPlace, resetLibraryOrder } from '$lib/stores/libraryOrder';
import { followPlaybackForResume } from '$lib/stores/playbackResume';
import { audioPlayer } from '$lib/services/audioPlayer.svelte';
import { makeGeneration, makeSong } from '$lib/test-utils/factories';

const AUTH_ME_PATH = '/api/auth/me';
const KNOWN_USER = { id: 'u1', username: 'admin', role: 'admin' as const };

beforeEach(() => {
	mockFetchMe.mockReset();
	mockApiLogin.mockReset();
	mockApiLogout.mockReset();
	mockStopLibraryResourceSync.mockReset();
	mockFetchLibraryContinue.mockReset();
	resetLibraryOrder();
	currentUser.set(null);
	authLoading.set(true);
	authError.set('');
	authCheckError.set(null);
	authNotice.set(null);
});

afterEach(() => {
	vi.useRealTimers();
	resetAuthForTests();
	resetConnectivityForTests();
});

describe('auth store', () => {
	it('defaults to null user', () => {
		expect(get(currentUser)).toBeNull();
	});

	it('isAdmin derived from currentUser', () => {
		expect(get(isAdmin)).toBe(false);
		currentUser.set({ id: 'u1', username: 'admin', role: 'admin' });
		expect(get(isAdmin)).toBe(true);
		currentUser.set({ id: 'u2', username: 'user', role: 'user' });
		expect(get(isAdmin)).toBe(false);
	});
});

describe('classifyAuthFailure', () => {
	it.each([
		['a 401 ApiError', new ApiError(401, 'unauthorized', AUTH_ME_PATH), 'unauthorized'],
		['a 403 ApiError', new ApiError(403, 'Account disabled', AUTH_ME_PATH), 'disabled'],
		['a 429 ApiError', new ApiError(429, 'slow down', AUTH_ME_PATH), 'retryable'],
		['a 500 ApiError', new ApiError(500, 'boom', AUTH_ME_PATH), 'retryable'],
		['a 502 ApiError', new ApiError(502, 'bad gateway', AUTH_ME_PATH), 'unreachable'],
		['a 503 ApiError', new ApiError(503, 'unavailable', AUTH_ME_PATH), 'unreachable'],
		['a 504 ApiError', new ApiError(504, 'gateway timeout', AUTH_ME_PATH), 'unreachable'],
		[
			'a network error',
			new NetworkError(AUTH_ME_PATH, new TypeError('Failed to fetch')),
			'unreachable'
		],
		['an unexpected failure', new TypeError('bad json'), 'retryable']
	])('classifies %s as %s', (_label, error, expected) => {
		expect(classifyAuthFailure(error)).toBe(expected);
	});
});

describe('checkAuth', () => {
	it('sets currentUser on success and clears any prior check error', async () => {
		authCheckError.set('stale error');
		authNotice.set('disabled');
		mockFetchMe.mockResolvedValueOnce({ id: 'u1', username: 'admin', role: 'admin' });
		const user = await checkAuth(vi.fn());
		expect(user).toEqual({ id: 'u1', username: 'admin', role: 'admin' });
		expect(get(currentUser)).toEqual(user);
		expect(get(authLoading)).toBe(false);
		expect(get(authCheckError)).toBeNull();
		expect(get(authNotice)).toBeNull();
	});

	it('logs out on a 401 and clears the known user', async () => {
		currentUser.set(KNOWN_USER);
		mockFetchMe.mockRejectedValueOnce(new ApiError(401, 'unauthorized', AUTH_ME_PATH));
		const user = await checkAuth(vi.fn());
		expect(user).toBeNull();
		expect(get(currentUser)).toBeNull();
		expect(get(authLoading)).toBe(false);
		expect(get(authCheckError)).toBeNull();
	});

	it.each([
		['a first visit without a session', 'Authentication required', null],
		['a reload whose session has expired', AUTH_SESSION_EXPIRED_DETAIL, 'unauthorized']
	])(
		'tells %s about an expired session only when there was one',
		async (_label, detail, notice) => {
			mockFetchMe.mockRejectedValueOnce(new ApiError(401, detail, AUTH_ME_PATH));
			await checkAuth(vi.fn());
			expect(get(authNotice)).toBe(notice);
		}
	);

	it('keeps the expiry notice of a session that ended through the next session check', async () => {
		currentUser.set(KNOWN_USER);
		clearAuth('unauthorized');
		mockFetchMe.mockRejectedValueOnce(new ApiError(401, 'unauthorized', AUTH_ME_PATH));
		await checkAuth(vi.fn());
		expect(get(authNotice)).toBe('unauthorized');
	});

	it('logs out on a 403 (account disabled) and clears the known user', async () => {
		currentUser.set(KNOWN_USER);
		mockFetchMe.mockRejectedValueOnce(new ApiError(403, 'Account disabled', AUTH_ME_PATH));
		const user = await checkAuth(vi.fn());
		expect(user).toBeNull();
		expect(get(currentUser)).toBeNull();
		expect(get(authLoading)).toBe(false);
		expect(get(authCheckError)).toBeNull();
		expect(get(authNotice)).toBe('disabled');
	});

	it('keeps an unknown user null through a transient failure on first load', async () => {
		authNotice.set('disabled');
		mockFetchMe.mockRejectedValueOnce(new ApiError(429, 'slow down', AUTH_ME_PATH));
		const user = await checkAuth(vi.fn());
		expect(user).toBeNull();
		expect(get(currentUser)).toBeNull();
		expect(get(authCheckError)).not.toBeNull();
		expect(get(authNotice)).toBeNull();
	});

	it.each([
		['a 429 rate limit', new ApiError(429, 'slow down', AUTH_ME_PATH)],
		['a 503 outage', new ApiError(503, 'unavailable', AUTH_ME_PATH)]
	])('keeps the known user through %s and records a retryable error', async (_label, error) => {
		currentUser.set(KNOWN_USER);
		mockFetchMe.mockRejectedValueOnce(error);
		const user = await checkAuth(vi.fn());
		expect(user).toEqual(KNOWN_USER);
		expect(get(currentUser)).toEqual(KNOWN_USER);
		expect(get(authLoading)).toBe(false);
		expect(get(authCheckError)).not.toBeNull();
	});
});

describe('checkAuth with the server out of reach', () => {
	const lostNetwork = () => new NetworkError(AUTH_ME_PATH, new TypeError('Failed to fetch'));
	const LONGER_THAN_ANY_BACKOFF_MS = 60_000;

	it('with the browser online shows the offline strip, names no failure, and asks again until the server answers', async () => {
		vi.useFakeTimers();
		mockFetchMe.mockRejectedValue(lostNetwork());
		const checkAgain = vi.fn(() => void checkAuth(checkAgain));

		expect(await checkAuth(checkAgain)).toBeNull();
		await vi.advanceTimersByTimeAsync(LONGER_THAN_ANY_BACKOFF_MS);

		expect(get(offline)).toBe(true);
		expect(get(authCheckUnreachable)).toBe(true);
		expect(get(authCheckError)).toBeNull();

		mockFetchMe.mockResolvedValue(KNOWN_USER);
		await vi.advanceTimersByTimeAsync(AUTH_CHECK_RETURN_PROBE_INTERVAL_MS);

		expect(get(currentUser)).toEqual(KNOWN_USER);
		expect(get(offline)).toBe(false);
		expect(get(authCheckUnreachable)).toBe(false);
		const checksUntilAnswered = mockFetchMe.mock.calls.length;
		await vi.advanceTimersByTimeAsync(LONGER_THAN_ANY_BACKOFF_MS);
		expect(mockFetchMe).toHaveBeenCalledTimes(checksUntilAnswered);
	});

	it('a server that answers with a refusal clears the offline strip', async () => {
		mockFetchMe
			.mockRejectedValueOnce(lostNetwork())
			.mockRejectedValueOnce(new ApiError(401, 'unauthorized', AUTH_ME_PATH));
		await checkAuth(vi.fn());

		await checkAuth(vi.fn());

		expect(get(offline)).toBe(false);
		expect(get(authCheckUnreachable)).toBe(false);
	});
});

describe('login', () => {
	it('sets currentUser on success', async () => {
		mockApiLogin.mockResolvedValueOnce({ id: 'u1', username: 'alice', role: 'user' });
		const user = await login('alice', 'password');
		expect(user.username).toBe('alice');
		expect(get(currentUser)).toEqual(user);
		expect(get(authError)).toBe('');
	});

	it('sets authError on 401', async () => {
		authNotice.set('disabled');
		mockApiLogin.mockRejectedValueOnce(new ApiError(401, 'Invalid credentials', '/api/auth/login'));
		await expect(login('alice', 'wrong')).rejects.toThrow();
		expect(get(authError)).toBe('Invalid username or password.');
		expect(get(authNotice)).toBeNull();
	});

	it('sets authError on 429', async () => {
		mockApiLogin.mockRejectedValueOnce(new ApiError(429, 'Too many requests', '/api/auth/login'));
		await expect(login('alice', 'x')).rejects.toThrow();
		expect(get(authError)).toBe('Too many attempts. Try again later.');
	});

	it('sets detail from ApiError on other status', async () => {
		mockApiLogin.mockRejectedValueOnce(new ApiError(403, 'Account disabled', '/api/auth/login'));
		await expect(login('alice', 'x')).rejects.toThrow();
		expect(get(authError)).toBe('Account disabled');
	});

	it('sets generic authError on non-API error', async () => {
		mockApiLogin.mockRejectedValueOnce(new Error('Network failure'));
		await expect(login('alice', 'x')).rejects.toThrow();
		expect(get(authError)).toBe('Network failure');
	});
});

describe('clearAuth', () => {
	it('sets currentUser to null', () => {
		currentUser.set({ id: 'u1', username: 'admin', role: 'admin' });
		clearAuth();
		expect(get(currentUser)).toBeNull();
	});

	it.each([
		['an expired session', 'unauthorized' as const, 'unauthorized'],
		['a sign-out', undefined, null]
	])('leaves the sign-in page the notice of %s', (_label, notice, expected) => {
		authNotice.set('disabled');
		clearAuth(notice);
		expect(get(authNotice)).toBe(expected);
	});

	it('wipes the per-user playlist and generation-failure caches so the next session starts clean', () => {
		playlistList.set([
			{
				id: 'p1',
				title: 'Leftover',
				slug: 'leftover',
				entry_count: 1,
				is_shared: false,
				share_slug: null,
				album_covers: [],
				created_at: ''
			}
		]);
		selectedPlaylistDetail.set({
			id: 'p1',
			title: 'Leftover',
			slug: 'leftover',
			entry_count: 1,
			is_shared: false,
			share_slug: null,
			album_covers: [],
			created_at: '',
			entries: []
		});
		generationFailures.set({ s1: 'Music generation failed' });

		clearAuth();

		expect(get(generationFailures)).toEqual({});
		expect(get(playlistList)).toEqual([]);
		expect(get(selectedPlaylistDetail)).toBeNull();
	});

	it("forgets the previous musician's Recent ranking and reads the next one's afresh", async () => {
		const workedOn = (id: string) => ({
			items: [
				{ type: 'album', id, title: id, album_covers: [], activity_at: '2026-09-27T03:47:00Z' }
			]
		});
		mockFetchLibraryContinue.mockResolvedValueOnce(workedOn('alices-album'));
		await ensureRecentWorkRead();

		clearAuth();
		expect(get(lastWorkByPlace).size).toBe(0);

		mockFetchLibraryContinue.mockResolvedValueOnce(workedOn('bobs-album'));
		await ensureRecentWorkRead();
		expect([...get(lastWorkByPlace).keys()]).toEqual(['album:bobs-album']);
	});

	it("drops the previous musician's Recent ranking that arrives after the session ended", async () => {
		let answerAlicesRead: (page: unknown) => void = () => {};
		mockFetchLibraryContinue.mockReturnValueOnce(
			new Promise((resolve) => {
				answerAlicesRead = resolve;
			})
		);
		const alicesRead = ensureRecentWorkRead();

		clearAuth();
		answerAlicesRead({
			items: [{ type: 'album', id: 'alices-album', title: 'A', album_covers: [], activity_at: '' }]
		});
		await alicesRead;

		expect(get(lastWorkByPlace).size).toBe(0);
	});
});

describe('logout', () => {
	it('stops resource sync before the logout request', async () => {
		const order: string[] = [];
		mockStopLibraryResourceSync.mockImplementation(() => {
			order.push('stop');
		});
		mockApiLogout.mockImplementation(async () => {
			order.push('api');
		});
		currentUser.set({ id: 'u1', username: 'admin', role: 'admin' });
		await logout();
		expect(order).toEqual(['stop', 'api']);
		expect(get(currentUser)).toBeNull();
	});

	it('clears currentUser', async () => {
		currentUser.set({ id: 'u1', username: 'admin', role: 'admin' });
		mockApiLogout.mockResolvedValueOnce(undefined);
		await logout();
		expect(get(currentUser)).toBeNull();
	});

	it('clears user even if API fails', async () => {
		currentUser.set({ id: 'u1', username: 'admin', role: 'admin' });
		mockApiLogout.mockRejectedValueOnce(new Error('fail'));
		await logout();
		expect(get(currentUser)).toBeNull();
	});
});

describe('the remembered playback across the session', () => {
	followPlaybackForResume({
		playsTheAppsTakes: () => true,
		queueSource: () => ({ type: 'album', albumId: 'a-session' }),
		takeAfterCurrent: () => null
	});

	function rememberAPlayingTake(): void {
		const song = makeSong({ id: 's-session' });
		audioPlayer.current = {
			generation: makeGeneration({ id: 'g-session', song_id: song.id }),
			songId: song.id,
			songTitle: song.title,
			artist: song.artist,
			albumTitle: song.album_title,
			lyrics: null
		};
		audioPlayer.status = 'playing';
		flushSync();
	}

	function storedRecord(): unknown {
		return JSON.parse(localStorage.getItem(`playbackResume:${KNOWN_USER.id}`) ?? 'null');
	}

	beforeEach(() => {
		currentUser.set(KNOWN_USER);
		rememberAPlayingTake();
	});

	afterEach(() => {
		currentUser.set(null);
		audioPlayer.current = null;
		audioPlayer.status = 'idle';
		flushSync();
		localStorage.clear();
	});

	it('logout forgets the record', async () => {
		mockApiLogout.mockResolvedValueOnce(undefined);
		expect(storedRecord()).toMatchObject({ generationId: 'g-session' });

		await logout();

		expect(storedRecord()).toBeNull();
	});

	it.each([
		{
			loss: 'a 401 on the session check',
			loseSession: async () => {
				mockFetchMe.mockRejectedValueOnce(new ApiError(401, 'unauthorized', AUTH_ME_PATH));
				await checkAuth(vi.fn());
			}
		},
		{ loss: 'a session lost mid-request', loseSession: async () => clearAuth() }
	])('a lost session keeps it ($loss)', async ({ loseSession }) => {
		await loseSession();

		expect(get(currentUser)).toBeNull();
		expect(storedRecord()).toMatchObject({ generationId: 'g-session' });
	});
});
