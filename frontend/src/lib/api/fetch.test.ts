import { replaceHistoryEntry } from '$lib/test-utils/library-history';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// Synchronous factory -- an async one leaves a window where a concurrent
// dynamic import('$lib/stores/auth') can bypass the mock.
vi.mock('$lib/stores/auth', () => {
	let user: { id: string } | null = null;
	const subscribers = new Set<(value: typeof user) => void>();
	const currentUser = {
		subscribe(fn: (value: typeof user) => void) {
			fn(user);
			subscribers.add(fn);
			return () => subscribers.delete(fn);
		},
		set(value: typeof user) {
			user = value;
			subscribers.forEach((fn) => fn(user));
		}
	};
	return {
		currentUser,
		hasSessionToLose: () => user !== null
	};
});
vi.mock('$app/navigation', async () =>
	(await import('$lib/test-utils/app-navigation')).fakeAppNavigation()
);

import {
	apiFetch,
	sseFetch,
	addCsrfToken,
	ApiError,
	NetworkError,
	describeFailure,
	handleSessionLost,
	isTransientApiFailure,
	signInAddress,
	signInReturnPath
} from './fetch';
import { UserFacingError } from './userFacingError';
import { API_ERROR_GENERIC_MESSAGE, RATE_LIMITED_TOAST_MESSAGE } from '$lib/constants';
import { dismissToast, toasts } from '$lib/stores/toast';
import { currentUser } from '$lib/stores/auth';
import {
	navigateTo,
	resetHistoryControllerForTests,
	standInForDocumentLoadsForTests
} from '$lib/history/historyController';
import { holdRouteLoads } from '$lib/test-utils/app-navigation';
import type { AuthUser } from '$lib/api/types';

function streamFrom(chunks: string[]): ReadableStream<Uint8Array> {
	const encoder = new TextEncoder();
	return new ReadableStream({
		start(controller) {
			for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
			controller.close();
		}
	});
}

describe('sseFetch', () => {
	it('yields parsed events from SSE frames', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			body: streamFrom([
				'data: {"type":"assistant_text","text":"hi"}\n\n',
				'data: {"type":"final","conversation_id":"c1"}\n\n'
			])
		});
		const events: unknown[] = [];
		for await (const ev of sseFetch<{ type: string }>('/api/chat/turn', { method: 'POST' })) {
			events.push(ev);
		}
		expect(events).toEqual([
			{ type: 'assistant_text', text: 'hi' },
			{ type: 'final', conversation_id: 'c1' }
		]);
	});

	it('handles events split across chunks', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			body: streamFrom(['data: {"type":"assist', 'ant_text","text":"x"}\n\n'])
		});
		const events: unknown[] = [];
		for await (const ev of sseFetch('/api/chat/turn', { method: 'POST' })) {
			events.push(ev);
		}
		expect(events).toEqual([{ type: 'assistant_text', text: 'x' }]);
	});

	it('skips malformed JSON frames', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: true,
			body: streamFrom(['data: not-json\n\n', 'data: {"type":"final"}\n\n'])
		});
		const events: { type: string }[] = [];
		for await (const ev of sseFetch<{ type: string }>('/api/chat/turn', { method: 'POST' })) {
			events.push(ev);
		}
		expect(events).toEqual([{ type: 'final' }]);
	});

	it('throws ApiError on non-2xx', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 503,
			json: () => Promise.resolve({ detail: 'down' })
		});
		const gen = sseFetch('/api/chat/turn', { method: 'POST' });
		await expect(gen.next()).rejects.toBeInstanceOf(ApiError);
	});

	it('sends CSRF header on mutating requests', async () => {
		document.cookie = 'csrf_token=token-xyz';
		mockFetch.mockResolvedValueOnce({ ok: true, body: streamFrom([]) });
		const gen = sseFetch('/api/chat/turn', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: '{}'
		});
		await gen.next();
		const call = mockFetch.mock.calls[mockFetch.mock.calls.length - 1];
		const headers = call[1].headers as Record<string, string>;
		expect(headers['X-CSRF-Token']).toBe('token-xyz');
	});
});

describe('addCsrfToken', () => {
	// jsdom's real cookie jar refuses a `__Host-` prefixed cookie on the
	// insecure `http://localhost` test origin (the prefix requires a secure
	// context), so the raw `document.cookie` string -- the one shape
	// `getCsrfToken` actually parses -- is stubbed directly instead.
	let cookieValue = '';
	const originalCookieDescriptor = Object.getOwnPropertyDescriptor(Document.prototype, 'cookie');
	if (!originalCookieDescriptor) throw new Error('jsdom dropped the document.cookie descriptor');

	beforeEach(() => {
		cookieValue = '';
		Object.defineProperty(document, 'cookie', {
			configurable: true,
			get: () => cookieValue
		});
	});

	afterEach(() => {
		Object.defineProperty(document, 'cookie', originalCookieDescriptor);
	});

	it.each([
		[
			'the __Host- cookie set first',
			'__Host-csrf_token=host-tok; csrf_token=plain-tok',
			'host-tok'
		],
		['the plain cookie set first', 'csrf_token=plain-tok; __Host-csrf_token=host-tok', 'host-tok'],
		['only the plain cookie present', 'csrf_token=plain-tok', 'plain-tok']
	])('with %s, the token used is %s', (_label, rawCookie, expectedToken) => {
		cookieValue = rawCookie;
		const init = addCsrfToken({}, 'POST');
		const headers = init.headers as Record<string, string>;
		expect(headers['X-CSRF-Token']).toBe(expectedToken);
	});

	it('adds no header when neither cookie is present', () => {
		const init = addCsrfToken({}, 'POST');
		expect(init.headers).toBeUndefined();
	});
});

describe('ApiError', () => {
	it('falls back to a readable sentence when the server sends no detail', () => {
		const err = new ApiError(500, '', '/api/albums');
		expect(err.message).toBe(API_ERROR_GENERIC_MESSAGE);
	});

	it('uses the server detail as the message when one is sent', () => {
		const err = new ApiError(500, 'Album not found', '/api/albums/x');
		expect(err.message).toBe('Album not found');
	});
});

describe('apiFetch error detail', () => {
	it.each([
		[
			'voice limit',
			{
				detail:
					'Could not create voice\nYou have reached the limit of 10 voices. Delete a voice before creating another.',
				reason: 'voice_limit'
			}
		],
		[
			'training queue limit',
			{
				detail:
					'Training queue is full\n2 trainings are already waiting. Try again when one training starts or finishes.',
				reason: 'training_queue_full'
			}
		]
	])('preserves the server %s sentence in ApiError.detail', async (_name, body) => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 409,
			headers: { get: () => null },
			json: () => Promise.resolve(body)
		});

		const err = await apiFetch('/api/loras').catch((e: unknown) => e);

		expect((err as ApiError).detail).toBe(body.detail);
	});

	it('surfaces a readable sentence, not the raw status line, for a non-JSON error body', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 500,
			headers: { get: () => null },
			json: () => Promise.reject(new SyntaxError('Unexpected token'))
		});

		const err = await apiFetch('/api/albums').catch((e: unknown) => e);

		expect(err).toBeInstanceOf(ApiError);
		expect((err as ApiError).detail).toBe('');
		expect((err as ApiError).message).toBe(API_ERROR_GENERIC_MESSAGE);
	});

	it('surfaces a readable sentence for a JSON body with no detail field', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 500,
			headers: { get: () => null },
			json: () => Promise.resolve({})
		});

		const err = await apiFetch('/api/albums').catch((e: unknown) => e);

		expect((err as ApiError).message).toBe(API_ERROR_GENERIC_MESSAGE);
	});

	it('keeps a structured detail payload while preserving the legacy string detail', async () => {
		const responseDetail = {
			provider: 'grok',
			surface: 'cowriter',
			status: { state: 'unconfigured', needs: 'api_key', environment_key: 'XAI_API_KEY' }
		};
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 422,
			headers: { get: () => null },
			json: () => Promise.resolve({ detail: responseDetail })
		});

		const err = await apiFetch('/api/settings/cowriter').catch((e: unknown) => e);

		expect((err as ApiError).detail).toBe('');
		expect((err as ApiError).responseDetail).toEqual(responseDetail);
		expect((err as ApiError).message).toBe(API_ERROR_GENERIC_MESSAGE);
	});
});

describe('apiFetch 429 classification', () => {
	function headersWithRetryAfter(value: string | null) {
		return { get: (name: string) => (name === 'Retry-After' ? value : null) };
	}

	it('carries status and Retry-After seconds on the ApiError', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 429,
			headers: headersWithRetryAfter('60'),
			json: () => Promise.resolve({ detail: 'Too many requests' })
		});

		const err = await apiFetch('/api/library/pool-queue').catch((e: unknown) => e);

		expect(err).toBeInstanceOf(ApiError);
		expect((err as ApiError).status).toBe(429);
		expect((err as ApiError).retryAfterSeconds).toBe(60);
	});

	it('leaves retryAfterSeconds null when the header is absent', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 500,
			headers: headersWithRetryAfter(null),
			json: () => Promise.resolve({ detail: 'boom' })
		});

		const err = await apiFetch('/api/library/pool-queue').catch((e: unknown) => e);

		expect((err as ApiError).retryAfterSeconds).toBeNull();
	});
});

describe('429 throttle toast', () => {
	function rateLimitedResponse() {
		return {
			ok: false,
			status: 429,
			headers: { get: () => null },
			json: () => Promise.resolve({ detail: 'Too many requests' })
		};
	}

	beforeEach(() => {
		toasts.set([]);
	});

	it('shows exactly one toast for a burst of 429s', async () => {
		mockFetch.mockResolvedValue(rateLimitedResponse());

		await Promise.all(
			Array.from({ length: 5 }, () => apiFetch('/api/songs').catch((e: unknown) => e))
		);

		const shown = get(toasts).filter((toast) => toast.message === RATE_LIMITED_TOAST_MESSAGE);
		expect(shown).toHaveLength(1);
	});

	it('raises a fresh toast once the earlier one is gone', async () => {
		mockFetch.mockResolvedValue(rateLimitedResponse());

		await apiFetch('/api/songs').catch((e: unknown) => e);
		const first = get(toasts).find((toast) => toast.message === RATE_LIMITED_TOAST_MESSAGE);
		if (!first) throw new Error('expected a throttle toast');
		dismissToast(first.id);

		await apiFetch('/api/songs').catch((e: unknown) => e);
		const shown = get(toasts).filter((toast) => toast.message === RATE_LIMITED_TOAST_MESSAGE);
		expect(shown).toHaveLength(1);
		expect(shown[0].id).not.toBe(first.id);
	});

	it('does not toast for a path that already surfaces its own 429 in place', async () => {
		mockFetch.mockResolvedValue(rateLimitedResponse());

		await apiFetch('/api/auth/login', { method: 'POST' }).catch((e: unknown) => e);
		await apiFetch('/api/auth/me').catch((e: unknown) => e);
		await apiFetch('/api/albums/a1/cover-suggestions', { method: 'POST' }).catch((e: unknown) => e);

		expect(get(toasts)).toHaveLength(0);
	});

	it('does not toast for a non-429 error', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 500,
			headers: { get: () => null },
			json: () => Promise.resolve({ detail: 'boom' })
		});

		await apiFetch('/api/songs').catch((e: unknown) => e);

		expect(get(toasts)).toHaveLength(0);
	});

	it('shows the same throttle toast through sseFetch', async () => {
		mockFetch.mockResolvedValueOnce(rateLimitedResponse());

		const gen = sseFetch('/api/chat/turn', { method: 'POST' });
		await gen.next().catch((e: unknown) => e);

		const shown = get(toasts).filter((toast) => toast.message === RATE_LIMITED_TOAST_MESSAGE);
		expect(shown).toHaveLength(1);
	});
});

describe('a request that gets no answer', () => {
	const firstEventFrom = (path: string) => sseFetch(path, { method: 'POST' }).next();

	it.each([
		{ client: 'apiFetch', request: (path: string) => apiFetch(path) },
		{ client: 'sseFetch', request: firstEventFrom }
	])('rejects through $client as a NetworkError keeping the browser text', async ({ request }) => {
		mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));
		const failure = await request('/api/songs/s1').catch((err: unknown) => err);
		expect(failure).toBeInstanceOf(NetworkError);
		expect(failure).toMatchObject({ path: '/api/songs/s1', message: 'Failed to fetch' });
	});

	it.each([
		{
			client: 'apiFetch',
			request: (path: string) => apiFetch(path),
			brokenAnswer: { ok: true, json: () => Promise.reject(new TypeError('network error')) }
		},
		{
			client: 'sseFetch',
			request: firstEventFrom,
			brokenAnswer: {
				ok: true,
				body: new ReadableStream({ pull: (stream) => stream.error(new TypeError('network error')) })
			}
		}
	])(
		'rejects through $client as a NetworkError when the answer breaks off mid-body',
		async ({ request, brokenAnswer }) => {
			mockFetch.mockResolvedValueOnce(brokenAnswer);
			const failure = await request('/api/songs/s1').catch((err: unknown) => err);
			expect(failure).toBeInstanceOf(NetworkError);
			expect(failure).toMatchObject({ path: '/api/songs/s1', message: 'network error' });
		}
	);

	it('leaves an aborted request as the abort, not as a network failure', async () => {
		mockFetch.mockRejectedValueOnce(new DOMException('The operation was aborted.', 'AbortError'));
		const failure = await apiFetch('/api/songs/s1').catch((err: unknown) => err);
		expect(failure).not.toBeInstanceOf(NetworkError);
		expect(failure).toMatchObject({ name: 'AbortError' });
	});
});

describe('describeFailure', () => {
	const fallback = 'Failed to load songs';

	it.each([
		{
			failure: 'a network failure',
			err: new NetworkError('/api/x', new TypeError('Failed to fetch'))
		},
		{ failure: 'a server answer without a reason', err: new ApiError(500, '', '/api/x') },
		{
			failure: 'an abort',
			err: new DOMException('signal is aborted without reason', 'AbortError')
		},
		{ failure: 'a plain error', err: new Error('undefined is not a function') },
		{ failure: 'a non-error value', err: 'boom' }
	])('gives the fallback for $failure', ({ err }) => {
		expect(describeFailure(err, fallback)).toBe(fallback);
	});

	it("gives the server's own words when it answered with a reason", () => {
		expect(describeFailure(new ApiError(409, 'Album is locked', '/api/x'), fallback)).toBe(
			'Album is locked'
		);
	});

	it('gives the words a module named for the musician itself', () => {
		expect(describeFailure(new UserFacingError('Nothing to save yet'), fallback)).toBe(
			'Nothing to save yet'
		);
	});

	it("gives the caller's offline wording when the request got no answer", () => {
		const unanswered = new NetworkError('/api/x', new TypeError('Failed to fetch'));

		expect(describeFailure(unanswered, fallback, { offline: 'You are offline' })).toBe(
			'You are offline'
		);
	});

	it("gives the fallback instead of the server's words when the caller withholds them", () => {
		const refusal = new ApiError(422, 'Validation error on: body.title', '/api/x');

		expect(describeFailure(refusal, fallback, { withholdServerDetail: true })).toBe(fallback);
	});
});

describe('isTransientApiFailure', () => {
	it.each([
		{
			failure: 'a rate limit',
			err: new ApiError(429, 'Too many requests', '/api/x'),
			transient: true
		},
		{ failure: 'a failing server', err: new ApiError(500, '', '/api/x'), transient: true },
		{ failure: 'a bad gateway', err: new ApiError(502, '', '/api/x'), transient: true },
		{ failure: 'an unavailable server', err: new ApiError(503, '', '/api/x'), transient: true },
		{ failure: 'a malformed request', err: new ApiError(400, '', '/api/x'), transient: false },
		{ failure: 'a missing session', err: new ApiError(401, '', '/api/x'), transient: false },
		{ failure: 'a forbidden request', err: new ApiError(403, '', '/api/x'), transient: false },
		{ failure: 'a missing resource', err: new ApiError(404, '', '/api/x'), transient: false },
		{
			failure: 'a request timeout, which no server of ours sends',
			err: new ApiError(408, '', '/api/x'),
			transient: false
		},
		{ failure: 'a conflict', err: new ApiError(409, '', '/api/x'), transient: false },
		{ failure: 'a validation refusal', err: new ApiError(422, '', '/api/x'), transient: false },
		{
			failure: 'a request that got no answer',
			err: new NetworkError('/api/x', new TypeError('Failed to fetch')),
			transient: false
		},
		{ failure: 'a plain error', err: new Error('undefined is not a function'), transient: false }
	])('defect:#1508 says a retry can help after $failure: $transient', ({ err, transient }) => {
		expect(isTransientApiFailure(err)).toBe(transient);
	});
});

describe('apiFetch abort signal', () => {
	afterEach(() => {
		vi.useRealTimers();
	});

	function signalPassedToFetch(): AbortSignal {
		const call = mockFetch.mock.calls[mockFetch.mock.calls.length - 1];
		return (call[1] as RequestInit).signal as AbortSignal;
	}

	function neverResolvingFetch(): void {
		mockFetch.mockImplementationOnce(() => new Promise(() => {}));
	}

	it('aborts the request when the caller aborts', () => {
		neverResolvingFetch();
		const caller = new AbortController();
		void apiFetch('/api/library/pool-queue', { signal: caller.signal }).catch(() => {});
		expect(signalPassedToFetch().aborted).toBe(false);
		caller.abort();
		expect(signalPassedToFetch().aborted).toBe(true);
	});

	function fetchRejectingOnAbort(): void {
		mockFetch.mockImplementationOnce(
			(_path: string, init: RequestInit) =>
				new Promise((_resolve, reject) => {
					init.signal?.addEventListener('abort', () =>
						reject(new DOMException('signal is aborted without reason', 'AbortError'))
					);
				})
		);
	}

	it('rejects a request that hits the timeout as a NetworkError with a timeout reason', async () => {
		vi.useFakeTimers();
		fetchRejectingOnAbort();
		const failure = apiFetch('/api/songs/s1').catch((err: unknown) => err);
		await vi.advanceTimersByTimeAsync(30_000);
		const rejected = await failure;
		expect(rejected).toBeInstanceOf(NetworkError);
		expect(rejected).toMatchObject({ path: '/api/songs/s1', reason: 'timeout' });
		expect((rejected as Error).message).not.toContain('signal is aborted');
	});

	it("leaves the caller's own abort an AbortError", async () => {
		fetchRejectingOnAbort();
		const caller = new AbortController();
		const failure = apiFetch('/api/songs/s1', { signal: caller.signal }).catch(
			(err: unknown) => err
		);
		caller.abort();
		const rejected = await failure;
		expect(rejected).not.toBeInstanceOf(NetworkError);
		expect(rejected).toMatchObject({ name: 'AbortError' });
	});

	it('times out after 30 seconds when the caller never aborts', () => {
		vi.useFakeTimers();
		neverResolvingFetch();
		const caller = new AbortController();
		void apiFetch('/api/library/pool-queue', { signal: caller.signal }).catch(() => {});
		vi.advanceTimersByTime(29_999);
		expect(signalPassedToFetch().aborted).toBe(false);
		vi.advanceTimersByTime(1);
		expect(signalPassedToFetch().aborted).toBe(true);
		expect(caller.signal.aborted).toBe(false);
	});
});

describe('session lost (401)', () => {
	const documentLoads = { assign: vi.fn(), replace: vi.fn(), reload: vi.fn() };

	function unauthorizedResponse() {
		return {
			ok: false,
			status: 401,
			headers: { get: () => null },
			json: () => Promise.resolve({ detail: 'Not authenticated' })
		};
	}

	function expectNoDocumentLoad(): void {
		for (const load of Object.values(documentLoads)) expect(load).not.toHaveBeenCalled();
	}

	beforeEach(() => {
		resetHistoryControllerForTests();
		standInForDocumentLoadsForTests(documentLoads);
		for (const load of Object.values(documentLoads)) load.mockReset();
		currentUser.set(null);
		replaceHistoryEntry('/');
	});

	it('loads the page afresh, which asks the server for the session again, when a session existed', async () => {
		currentUser.set({ id: 'u1', username: 'felix', role: 'user' } as AuthUser);
		replaceHistoryEntry('/album/a1/song-1');
		mockFetch.mockResolvedValueOnce(unauthorizedResponse());

		await apiFetch('/api/songs/s1').catch((e: unknown) => e);

		expect(documentLoads.reload).toHaveBeenCalledOnce();
		expect(documentLoads.assign).not.toHaveBeenCalled();
		expect(documentLoads.replace).not.toHaveBeenCalled();
	});

	it('loads afresh the page a navigation started before the session was lost lands on', async () => {
		currentUser.set({ id: 'u1', username: 'felix', role: 'user' } as AuthUser);
		replaceHistoryEntry('/settings/voices');
		let reloadedOn: string | undefined;
		documentLoads.reload.mockImplementation(() => (reloadedOn = location.pathname));
		const releaseRouteLoads = holdRouteLoads();
		const albumOpened = navigateTo('/album/b2', {
			replaceState: false,
			noScroll: true,
			keepFocus: true,
			state: {}
		});

		const reaction = handleSessionLost();
		await vi.dynamicImportSettled();
		expect(documentLoads.reload).not.toHaveBeenCalled();
		releaseRouteLoads();
		await Promise.all([albumOpened, reaction]);

		expect(reloadedOn).toBe('/album/b2');
	});

	it('reacts the same way through sseFetch as through apiFetch', async () => {
		currentUser.set({ id: 'u1', username: 'felix', role: 'user' } as AuthUser);
		mockFetch.mockResolvedValueOnce(unauthorizedResponse());

		const gen = sseFetch('/api/chat/turn', { method: 'POST' });
		await gen.next().catch((e: unknown) => e);

		expect(documentLoads.reload).toHaveBeenCalledOnce();
	});

	it('still rejects with an ApiError so the caller can show its own message', async () => {
		currentUser.set({ id: 'u1', username: 'felix', role: 'user' } as AuthUser);
		mockFetch.mockResolvedValueOnce(unauthorizedResponse());

		const err = await apiFetch('/api/songs/s1').catch((e: unknown) => e);

		expect(err).toBeInstanceOf(ApiError);
		expect((err as ApiError).status).toBe(401);
	});

	it('does not react for a visitor who was never signed in, leaving app routing to decide', async () => {
		currentUser.set(null);
		mockFetch.mockResolvedValueOnce(unauthorizedResponse());

		await apiFetch('/api/songs/s1').catch((e: unknown) => e);

		expectNoDocumentLoad();
	});

	it.each([
		{ form: 'the login form', path: '/api/auth/login' },
		{ form: 'the password change (wrong current password)', path: '/api/auth/password' }
	])(
		'does not react to a 401 from $form itself (a refusal, not a lost session)',
		async ({ path }) => {
			currentUser.set({ id: 'u1', username: 'felix', role: 'user' } as AuthUser);
			mockFetch.mockResolvedValueOnce(unauthorizedResponse());

			const err = await apiFetch(path, { method: 'POST' }).catch((e: unknown) => e);

			expect(err).toBeInstanceOf(ApiError);
			expectNoDocumentLoad();
		}
	);

	it('a second caller that arrives while the reaction is in flight joins it instead of starting a new one', async () => {
		currentUser.set({ id: 'u1', username: 'felix', role: 'user' } as AuthUser);
		// A navigation under way holds the one load back until it lands. Joined,
		// the second caller's wait ends with that load; a reaction of its own
		// would find the leave already counted and end before anything loaded.
		let loaded = false;
		documentLoads.reload.mockImplementation(() => {
			loaded = true;
		});
		const releaseRouteLoads = holdRouteLoads();
		const albumOpened = navigateTo('/album/b2', {
			replaceState: false,
			noScroll: true,
			keepFocus: true,
			state: {}
		});

		const loadedWhenDone = [handleSessionLost(), handleSessionLost()].map((reaction) =>
			reaction.then(() => loaded)
		);
		await vi.dynamicImportSettled();
		releaseRouteLoads();
		await albumOpened;

		expect(await Promise.all(loadedWhenDone)).toEqual([true, true]);
		expect(documentLoads.reload).toHaveBeenCalledOnce();
	});
});

describe('sign-in address', () => {
	it.each([
		[
			'/album/northern-lights/glass-river',
			'/login?redirect=%2Falbum%2Fnorthern-lights%2Fglass-river'
		],
		['/album/a1?tab=lyrics', `/login?redirect=${encodeURIComponent('/album/a1?tab=lyrics')}`],
		['/', '/login'],
		['/login', '/login'],
		['/login?redirect=%2Fx', '/login'],
		['//attacker.example/x', '/login'],
		['///attacker.example/x', '/login'],
		['/%2F%2Fattacker.example/x', '/login']
	])('asks to return from %s as %s', (returnTo, expected) => {
		expect(signInAddress(returnTo)).toBe(expected);
	});
});

describe('sign-in return path', () => {
	function signInPage(query: string): URL {
		return new URL(`/login${query}`, window.location.origin);
	}

	it.each([
		[
			'the asked-for song',
			'?redirect=%2Falbum%2Fnorthern-lights%2Fglass-river',
			'/album/northern-lights/glass-river'
		],
		[
			'a same-origin path with its query',
			`?redirect=${encodeURIComponent('/album/a1?tab=lyrics')}`,
			'/album/a1?tab=lyrics'
		],
		['no target', '', '/'],
		['an absolute URL', `?redirect=${encodeURIComponent('https://attacker.example/x')}`, '/'],
		['a protocol-relative host', `?redirect=${encodeURIComponent('//attacker.example/x')}`, '/'],
		['a backslash host', `?redirect=${encodeURIComponent('/\\attacker.example/x')}`, '/'],
		['a host split by a tab', `?redirect=${encodeURIComponent('/\t/attacker.example/x')}`, '/'],
		['a script URL', `?redirect=${encodeURIComponent('javascript:alert(1)')}`, '/'],
		['the sign-in page itself', `?redirect=${encodeURIComponent('/login?redirect=/x')}`, '/'],
		['the sign-in page spelled encoded', `?redirect=${encodeURIComponent('/%6Cogin')}`, '/'],
		['an API address spelled encoded', `?redirect=${encodeURIComponent('/%61pi/auth/me')}`, '/'],
		['a nested page', `?redirect=${encodeURIComponent('/album/a/b')}`, '/album/a/b'],
		['a path below the sign-in page', `?redirect=${encodeURIComponent('/login/x')}`, '/'],
		['the sign-in page with an encoded slash', `?redirect=${encodeURIComponent('/login%2F')}`, '/'],
		['the sign-in page in capitals', `?redirect=${encodeURIComponent('/LOGIN')}`, '/'],
		[
			'the sign-in page in capitals with a slash',
			`?redirect=${encodeURIComponent('/LOGIN/')}`,
			'/'
		],
		['an API address in capitals', `?redirect=${encodeURIComponent('/API/auth/me')}`, '/'],
		['the API root', `?redirect=${encodeURIComponent('/api')}`, '/']
	])('lands on %s', (_label, query, expected) => {
		expect(signInReturnPath(signInPage(query))).toBe(expected);
	});
});
