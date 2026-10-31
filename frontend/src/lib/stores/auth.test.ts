import { afterEach, describe, expect, it, onTestFinished, vi, beforeEach } from 'vitest';
import { flushSync } from 'svelte';
import { get } from 'svelte/store';

const mockFetchMe = vi.fn();

vi.mock('#lib/api/client.ts', async () => {
	const { ApiError } =
		await vi.importActual<typeof import('#lib/api/client.ts')>('#lib/api/client.ts');
	return {
		ApiError,
		fetchMe: (...args: unknown[]) => mockFetchMe(...args)
	};
});

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);

import {
	currentUser,
	authLoading,
	authCheckError,
	authCheckUnreachable,
	isAdmin,
	checkAuth,
	classifyAuthFailure,
	logout,
	handleSessionLost,
	resetAuthForTests,
	signOutFailed
} from './auth';
import { offline, resetConnectivityForTests } from './connectivity';
import { AUTH_CHECK_RETURN_PROBE_INTERVAL_MS, LOGOUT_ADDRESS } from '#lib/constants/auth.ts';
import { ApiError } from '#lib/api/client.ts';
import { NetworkError, apiFetch, installRefusalReactions, sseFetch } from '#lib/api/fetch.ts';
import {
	navigateTo,
	resetHistoryControllerForTests,
	standInForDocumentLoadsForTests
} from '#lib/history/historyController.ts';
import { notifyRateLimited } from '#lib/stores/rateLimitNotice.ts';
import { followPlaybackForResume } from '#lib/stores/playbackResume.ts';
import { audioPlayer, type AudioPlayerCallbacks } from '#lib/services/audioPlayer.svelte.ts';
import { holdRouteLoads } from '#lib/test-utils/app-navigation.ts';
import { documentLoads } from '#lib/test-utils/document-loads.ts';
import { makeGeneration, makeSong } from '#lib/test-utils/factories.ts';
import { replaceHistoryEntry } from '#lib/test-utils/library-history.ts';

const AUTH_ME_PATH = '/api/auth/me';
const KNOWN_USER = { id: 'u1', username: 'admin', role: 'admin' as const };

// The app's own reactions, installed as the root layout installs them: without
// them a refused request would reach no reaction, and every test that sends
// one would pass without auth being asked.
let uninstallRefusalReactions: () => void;

function serverRefusesEveryRequest(): () => void {
	const refused = vi
		.spyOn(globalThis, 'fetch')
		.mockImplementation(
			async () => new Response(JSON.stringify({ detail: 'Not authenticated' }), { status: 401 })
		);
	return () => refused.mockRestore();
}

beforeEach(() => {
	mockFetchMe.mockReset();
	currentUser.set(null);
	authLoading.set(true);
	authCheckError.set(null);
	resetHistoryControllerForTests();
	standInForDocumentLoadsForTests(documentLoads);
	for (const load of Object.values(documentLoads)) load.mockReset();
	uninstallRefusalReactions = installRefusalReactions({
		sessionLost: handleSessionLost,
		rateLimited: notifyRateLimited
	});
});

afterEach(() => {
	uninstallRefusalReactions();
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
		['a 403 ApiError', new ApiError(403, 'Forbidden', AUTH_ME_PATH), 'retryable'],
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
		mockFetchMe.mockResolvedValueOnce({ id: 'u1', username: 'admin', role: 'admin' });
		const user = await checkAuth(vi.fn());
		expect(user).toEqual({ id: 'u1', username: 'admin', role: 'admin' });
		expect(get(currentUser)).toEqual(user);
		expect(get(authLoading)).toBe(false);
		expect(get(authCheckError)).toBeNull();
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

	it('keeps an unknown user null through a transient failure on first load', async () => {
		mockFetchMe.mockRejectedValueOnce(new ApiError(429, 'slow down', AUTH_ME_PATH));
		const user = await checkAuth(vi.fn());
		expect(user).toBeNull();
		expect(get(currentUser)).toBeNull();
		expect(get(authCheckError)).not.toBeNull();
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

describe('logout', () => {
	// K4
	it('checks that the server answers before it posts the logout form', async () => {
		const order: string[] = [];
		mockFetchMe.mockImplementation(async () => {
			order.push('check');
			return KNOWN_USER;
		});
		documentLoads.submitPost.mockImplementation((action: string) => order.push(`post ${action}`));
		currentUser.set(KNOWN_USER);

		await logout();

		expect(order).toEqual(['check', `post ${LOGOUT_ADDRESS}`]);
		expect(documentLoads.assign).not.toHaveBeenCalled();
		expect(documentLoads.replace).not.toHaveBeenCalled();
	});

	it('925_M3_S5: stays a sign-out when a request is refused while it checks, or after', async () => {
		currentUser.set(KNOWN_USER);
		const refused = vi
			.spyOn(globalThis, 'fetch')
			.mockResolvedValue(
				new Response(JSON.stringify({ detail: 'Not authenticated' }), { status: 401 })
			);
		mockFetchMe.mockImplementation(async () => {
			await apiFetch('/api/songs/s1').catch(() => undefined);
			return KNOWN_USER;
		});

		await logout();
		await apiFetch('/api/songs/s2').catch(() => undefined);
		refused.mockRestore();

		expect(documentLoads.submitPost.mock.calls).toEqual([[LOGOUT_ADDRESS]]);
		expect(documentLoads.reload).not.toHaveBeenCalled();
		expect(documentLoads.replace).not.toHaveBeenCalled();
	});

	it.each([
		{ answer: 'the server answers', reply: () => Promise.resolve(KNOWN_USER), keeps: false },
		{
			answer: 'the server cannot be reached',
			reply: () => Promise.reject(new NetworkError(AUTH_ME_PATH, new TypeError('Failed to fetch'))),
			keeps: true
		}
	])('H4: when $answer, the theme copy is kept: $keeps', async ({ reply, keeps }) => {
		localStorage.setItem('songmaker.theme', 'dark');
		currentUser.set(KNOWN_USER);
		mockFetchMe.mockImplementationOnce(reply);

		await logout();

		expect(localStorage.getItem('songmaker.theme')).toBe(keeps ? 'dark' : null);
	});

	// Only an unreachable server keeps the person signed in, and says so: the
	// check is about reaching the server, so a session already gone (a 401) or
	// any other answer still leaves, because the identity provider's session
	// has to end (#1340, ruling A; E2 of #1807).
	it.each([
		{ answer: 'a 2xx', reply: () => Promise.resolve(KNOWN_USER), leaves: true },
		{
			answer: 'a 401',
			reply: () => Promise.reject(new ApiError(401, 'Not authenticated', AUTH_ME_PATH)),
			leaves: true
		},
		{
			answer: 'a 429',
			reply: () => Promise.reject(new ApiError(429, 'Too many requests', AUTH_ME_PATH)),
			leaves: true
		},
		{
			answer: 'no answer',
			reply: () => Promise.reject(new NetworkError(AUTH_ME_PATH, new TypeError('Failed to fetch'))),
			leaves: false
		},
		{
			answer: 'a 503',
			reply: () => Promise.reject(new ApiError(503, 'Unavailable', AUTH_ME_PATH)),
			leaves: false
		}
	])(
		'925_M3_S6: after $answer to the check, posts the logout form: $leaves, and a later refusal loads afresh only if it did not',
		async ({ reply, leaves }) => {
			onTestFinished(serverRefusesEveryRequest());
			replaceHistoryEntry('/');
			currentUser.set(KNOWN_USER);
			mockFetchMe.mockImplementationOnce(reply);

			await logout();
			await apiFetch('/api/songs/s1').catch(() => undefined);

			expect(documentLoads.submitPost).toHaveBeenCalledTimes(leaves ? 1 : 0);
			expect(get(signOutFailed)).toBe(!leaves);
			expect(get(currentUser)).toEqual(KNOWN_USER);
			expect(documentLoads.reload).toHaveBeenCalledTimes(leaves ? 0 : 1);
		}
	);
});

describe('a request refused as a lost session', () => {
	const throughApiFetch = (path: string) => apiFetch(path);
	const throughSseFetch = (path: string) => sseFetch(path, { method: 'POST' }).next();
	const clients = [
		{ client: 'apiFetch', request: throughApiFetch },
		{ client: 'sseFetch', request: throughSseFetch }
	];
	const noOtherCallbacks: AudioPlayerCallbacks = {
		onEnded: null,
		onPlaybackStarted: null,
		onAuthLost: null,
		onStreamRebuild: null,
		onCurrentChange: null,
		networkFailureIsAnnounced: () => false
	};
	const aTake = {
		generation: makeGeneration({ id: 'g-refused', song_id: 's-refused' }),
		songId: 's-refused',
		songTitle: 'Refused',
		artist: 'Artist',
		albumTitle: 'Album',
		lyrics: null
	};
	const openingTheAlbum = () =>
		navigateTo('/album/b2', { replace: false, reset: false, state: {} });
	// The refusal travels through promises only, so one task later it has been
	// handed to the reaction and nothing further is pending without history.
	const refusalIsHandedOver = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

	function theElementOf(player: typeof audioPlayer): HTMLAudioElement {
		const element = player.getElement();
		if (element === null) throw new Error('the player holds no element to fail');
		return element;
	}

	beforeEach(() => {
		onTestFinished(serverRefusesEveryRequest());
		replaceHistoryEntry('/');
	});

	it.each(clients)(
		'925_M3_S1: a refusal through $client with a session to lose loads afresh once',
		async ({ request }) => {
			currentUser.set(KNOWN_USER);
			replaceHistoryEntry('/album/a1/song-1');

			await request('/api/songs/s1').catch((e: unknown) => e);

			expect(documentLoads.reload).toHaveBeenCalledOnce();
			expect(documentLoads.assign).not.toHaveBeenCalled();
			expect(documentLoads.replace).not.toHaveBeenCalled();
		}
	);

	it('925_M3_S2: a navigation already under way lands first, then the page it landed on loads afresh', async () => {
		currentUser.set(KNOWN_USER);
		replaceHistoryEntry('/settings/voices');
		let reloadedOn: string | undefined;
		documentLoads.reload.mockImplementation(() => (reloadedOn = location.pathname));
		const releaseRouteLoads = holdRouteLoads();
		const albumOpened = openingTheAlbum();

		const refused = apiFetch('/api/songs/s1').catch((e: unknown) => e);
		await refusalIsHandedOver();
		const loadedWhileTheNavigationWasHeld = documentLoads.reload.mock.calls.length > 0;
		releaseRouteLoads();
		await Promise.all([albumOpened, refused]);

		expect({ loadedWhileTheNavigationWasHeld, reloadedOn }).toEqual({
			loadedWhileTheNavigationWasHeld: false,
			reloadedOn: '/album/b2'
		});
	});

	it('925_M3_S3: a visitor who never signed in loads nothing', async () => {
		await apiFetch('/api/songs/s1').catch((e: unknown) => e);

		expect(documentLoads.reload).not.toHaveBeenCalled();
		expect(documentLoads.assign).not.toHaveBeenCalled();
		expect(documentLoads.replace).not.toHaveBeenCalled();
	});

	it('925_M3_S4: a second refusal in flight joins the first, so there is one load and both waits end with it', async () => {
		currentUser.set(KNOWN_USER);
		let loaded = false;
		documentLoads.reload.mockImplementation(() => (loaded = true));
		const releaseRouteLoads = holdRouteLoads();
		const albumOpened = openingTheAlbum();

		const loadedWhenDone = [
			throughApiFetch('/api/songs/s1'),
			throughSseFetch('/api/chat/turn')
		].map((request) => request.catch((e: unknown) => e).then(() => loaded));
		await refusalIsHandedOver();
		releaseRouteLoads();
		await albumOpened;

		expect(await Promise.all(loadedWhenDone)).toEqual([true, true]);
		expect(documentLoads.reload).toHaveBeenCalledOnce();
	});

	it("925_M3_S9: a transport refusal and a media-probe refusal under one navigation both reach auth's reaction and end with its one load", async () => {
		currentUser.set(KNOWN_USER);
		replaceHistoryEntry('/settings/voices');
		let loaded = false;
		let reloadedOn: string | undefined;
		documentLoads.reload.mockImplementation(() => {
			loaded = true;
			reloadedOn = location.pathname;
		});
		const entered: string[] = [];
		const loadedWhenWaitsEnded: Promise<boolean>[] = [];
		const enterThenForward = (caller: string) => () => {
			entered.push(caller);
			const wait = handleSessionLost();
			loadedWhenWaitsEnded.push(wait.then(() => loaded));
			return wait;
		};
		const uninstall = installRefusalReactions({
			sessionLost: enterThenForward('transport'),
			rateLimited: () => undefined
		});
		const previousOwner = audioPlayer.swapCallbacks({
			...noOtherCallbacks,
			onAuthLost: enterThenForward('media probe')
		});
		const releaseRouteLoads = holdRouteLoads();
		const albumOpened = openingTheAlbum();
		const albumRead = apiFetch('/api/albums/b2').catch(() => undefined);
		try {
			audioPlayer.load(aTake, { autoplay: false });
			theElementOf(audioPlayer).dispatchEvent(new Event('error'));
			await vi.waitFor(() => expect([...entered].sort()).toEqual(['media probe', 'transport']));
			const loadedWhileTheNavigationWasHeld = loaded;
			releaseRouteLoads();
			await Promise.all([albumOpened, albumRead]);

			expect({
				loadedWhileTheNavigationWasHeld,
				loadedWhenWaitsEnded: await Promise.all(loadedWhenWaitsEnded),
				loads: documentLoads.reload.mock.calls.length,
				reloadedOn
			}).toEqual({
				loadedWhileTheNavigationWasHeld: false,
				loadedWhenWaitsEnded: [true, true],
				loads: 1,
				reloadedOn: '/album/b2'
			});
		} finally {
			releaseRouteLoads();
			await Promise.allSettled([albumOpened, albumRead, ...loadedWhenWaitsEnded]);
			audioPlayer.restoreCallbacks(previousOwner);
			audioPlayer.unload();
			uninstall();
			localStorage.removeItem(`playbackResume:${KNOWN_USER.id}`);
		}
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

	it('logout stops the take that was playing and leaves no take loaded', async () => {
		mockFetchMe.mockResolvedValueOnce(KNOWN_USER);

		await logout();

		expect(audioPlayer.current).toBeNull();
		expect(audioPlayer.status).toBe('idle');
	});

	it('logout forgets the record', async () => {
		mockFetchMe.mockResolvedValueOnce(KNOWN_USER);
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
			},
			expectSessionGone: () => expect(get(currentUser)).toBeNull()
		},
		{
			loss: 'a session lost mid-request',
			loseSession: () => handleSessionLost(),
			expectSessionGone: () => expect(documentLoads.reload).toHaveBeenCalledOnce()
		}
	])('a lost session keeps it ($loss)', async ({ loseSession, expectSessionGone }) => {
		await loseSession();

		expectSessionGone();
		expect(storedRecord()).toMatchObject({ generationId: 'g-session' });
	});
});
