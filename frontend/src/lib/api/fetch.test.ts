import { afterEach, describe, expect, it, onTestFinished, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

vi.mock('$app/navigation', async () =>
	(await import('#lib/test-utils/app-navigation.ts')).fakeAppNavigation()
);

import {
	apiFetch,
	fetchMediaBytes,
	sseFetch,
	ApiError,
	NetworkError,
	describeFailure,
	installRefusalReactions,
	isTransientApiFailure,
	signInAddress
} from './fetch';
import { API_ERROR_GENERIC_MESSAGE } from '#lib/constants.ts';
import { hangsUntilAborted } from '#lib/test-utils/network.ts';

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
	it.each(['timeout', 'caller'] as const)(
		'1160-F38-body: preserves the cause of a mid-body %s abort',
		async (cause) => {
			vi.useFakeTimers();
			onTestFinished(() => {
				vi.useRealTimers();
			});
			mockFetch.mockImplementationOnce(async (_path: string, init: RequestInit) => ({
				ok: true,
				body: new ReadableStream<Uint8Array>({
					start(stream) {
						stream.enqueue(new TextEncoder().encode('data: {"type":"started"}\n\n'));
						init.signal?.addEventListener('abort', () =>
							stream.error(new DOMException('Aborted', 'AbortError'))
						);
					}
				})
			}));
			const caller = new AbortController();
			const events = sseFetch('/api/chat/turn', { signal: caller.signal }, 100);
			await expect(events.next()).resolves.toEqual({ value: { type: 'started' }, done: false });
			const failure = events.next().catch((error: unknown) => error);
			if (cause === 'timeout') await vi.advanceTimersByTimeAsync(100);
			else caller.abort();
			const error = await failure;
			if (cause === 'timeout') {
				expect(error).toBeInstanceOf(NetworkError);
				expect(error).toMatchObject({ path: '/api/chat/turn', reason: 'timeout' });
			} else {
				expect(error).not.toBeInstanceOf(NetworkError);
				expect(error).toMatchObject({ name: 'AbortError' });
			}
		}
	);

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

	it.each([
		{
			body: { detail: 'Not now', error_type: 'generation_unavailable', job_id: 'job9' },
			errorType: 'generation_unavailable',
			jobId: 'job9'
		},
		{ body: { detail: 'Not now', error_type: 7, job_id: null }, errorType: null, jobId: null },
		{ body: { detail: 'Not now' }, errorType: null, jobId: null }
	])('keeps error_type and job_id of $body as typed fields', async ({ body, errorType, jobId }) => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			status: 503,
			headers: { get: () => null },
			json: () => Promise.resolve(body)
		});

		const err = await apiFetch('/api/songs/s1/generate').catch((e: unknown) => e);

		expect(err).toMatchObject({ detail: 'Not now', errorType, jobId });
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

describe('refusal reactions', () => {
	const throughApiFetch = (path: string) => apiFetch(path);
	const throughSseFetch = (path: string) => sseFetch(path, { method: 'POST' }).next();
	const clients = [
		{ client: 'apiFetch', request: throughApiFetch },
		{ client: 'sseFetch', request: throughSseFetch }
	];

	const NOTHING_HAPPENS = {
		sessionLost: () => Promise.resolve(),
		rateLimited: () => undefined
	};

	function serverRefusesWith(status: number) {
		mockFetch.mockImplementation(async () => ({
			ok: false,
			status,
			headers: { get: () => null },
			json: () => Promise.resolve({ detail: 'refused' })
		}));
	}

	function aRefusedRequest() {
		return throughApiFetch('/api/songs').catch((e: unknown) => e);
	}

	function refusalsTold(): string[] {
		const told: string[] = [];
		onTestFinished(
			installRefusalReactions({
				rateLimited: (path) => told.push(`rateLimited ${path}`),
				sessionLost: () => {
					told.push('sessionLost');
					return Promise.resolve();
				}
			})
		);
		return told;
	}

	afterEach(() => {
		mockFetch.mockReset();
	});

	it.each(clients)(
		'925_M3_P1: a 429 tells rateLimited its path through $client',
		async ({ request }) => {
			const told: string[] = [];
			onTestFinished(
				installRefusalReactions({ ...NOTHING_HAPPENS, rateLimited: (path) => told.push(path) })
			);
			serverRefusesWith(429);

			await request('/api/songs').catch((e: unknown) => e);

			expect(told).toEqual(['/api/songs']);
		}
	);

	it.each([400, 403, 404, 500, 502, 503])(
		'925_M3_P2: a %i tells neither rateLimited nor sessionLost anything',
		async (status) => {
			const told = refusalsTold();
			serverRefusesWith(status);

			const failure = await aRefusedRequest();

			expect(failure).toBeInstanceOf(ApiError);
			expect(told).toEqual([]);
		}
	);

	// Through apiFetch the same guarantee is pinned by 'carries status and
	// Retry-After seconds on the ApiError' above, which installs nothing either.
	it.each([429, 401])(
		'925_M3_P3: with nothing installed a %i still rejects with its ApiError through sseFetch',
		async (status) => {
			serverRefusesWith(status);

			const failure = await throughSseFetch('/api/songs').catch((e: unknown) => e);

			expect(failure).toBeInstanceOf(ApiError);
			expect((failure as ApiError).status).toBe(status);
		}
	);

	it('925_M3_P4: an uninstall puts back the set installed before it, and after the last one a 429 reaches no reaction', async () => {
		const told: string[] = [];
		const listening = (name: string) =>
			installRefusalReactions({ ...NOTHING_HAPPENS, rateLimited: () => told.push(name) });
		const uninstallFirst = listening('first');
		const uninstallSecond = listening('second');
		serverRefusesWith(429);

		try {
			await aRefusedRequest();
			uninstallSecond();
			await aRefusedRequest();
			uninstallFirst();
			await aRefusedRequest();
		} finally {
			uninstallSecond();
			uninstallFirst();
		}

		expect(told).toEqual(['second', 'first']);
	});

	it.each(clients)(
		'925_M3_P5: a 401 outside the public share reads tells sessionLost through $client',
		async ({ request }) => {
			const told = refusalsTold();
			serverRefusesWith(401);

			await request('/api/songs/s1').catch((e: unknown) => e);

			expect(told).toEqual(['sessionLost']);
		}
	);

	const PUBLIC_SHARE_REQUESTS = [
		{ request: 'a share read', path: '/shared/playlist/p1', init: undefined },
		{ request: 'a share stream build', path: '/shared/p1/stream', init: { method: 'POST' } }
	];

	it.each(PUBLIC_SHARE_REQUESTS)(
		'925_M2_C3: a 401 from $request tells sessionLost nothing and rejects with its ApiError',
		async ({ path, init }) => {
			const told = refusalsTold();
			serverRefusesWith(401);

			const failure = await apiFetch(path, init).catch((e: unknown) => e);

			expect(failure).toBeInstanceOf(ApiError);
			expect((failure as ApiError).status).toBe(401);
			expect(told).toEqual([]);
		}
	);

	it('925_M3_P7: the request rejects only after sessionLost has settled', async () => {
		const happened: string[] = [];
		let settleReaction: () => void = () => undefined;
		onTestFinished(
			installRefusalReactions({
				...NOTHING_HAPPENS,
				sessionLost: () =>
					new Promise<void>((resolve) => {
						happened.push('reaction told');
						settleReaction = () => {
							happened.push('reaction settled');
							resolve();
						};
					})
			})
		);
		serverRefusesWith(401);

		const rejected = apiFetch('/api/songs/s1').catch(() => happened.push('request rejected'));
		await vi.waitFor(() => expect(happened).toEqual(['reaction told']));
		settleReaction();
		await rejected;

		expect(happened).toEqual(['reaction told', 'reaction settled', 'request rejected']);
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

	it('rejects a request that hits the timeout as a NetworkError with a timeout reason', async () => {
		vi.useFakeTimers();
		mockFetch.mockImplementationOnce(hangsUntilAborted);
		const failure = apiFetch('/api/songs/s1').catch((err: unknown) => err);
		await vi.advanceTimersByTimeAsync(30_000);
		const rejected = await failure;
		expect(rejected).toBeInstanceOf(NetworkError);
		expect(rejected).toMatchObject({ path: '/api/songs/s1', reason: 'timeout' });
		expect((rejected as Error).message).not.toContain('signal is aborted');
	});

	it("leaves the caller's own abort an AbortError", async () => {
		mockFetch.mockImplementationOnce(hangsUntilAborted);
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

describe('sign-in address', () => {
	const SIGN_IN_START = '/login/oidc?next=';

	it.each([
		[
			'the asked-for song',
			'/album/northern-lights/glass-river',
			'/album/northern-lights/glass-river'
		],
		['a same-origin path with its query', '/album/a1?tab=lyrics', '/album/a1?tab=lyrics'],
		['a nested page', '/album/a/b', '/album/a/b'],
		['the library', '/', '/'],
		['an absolute URL', 'https://attacker.example/x', '/'],
		['a protocol-relative host', '//attacker.example/x', '/'],
		['a triple slash host', '///attacker.example/x', '/'],
		['a backslash host', '/\\attacker.example/x', '/'],
		['a host split by a tab', '/\t/attacker.example/x', '/'],
		['a host behind an encoded slash', '/%2F%2Fattacker.example/x', '/'],
		['a script URL', 'javascript:alert(1)', '/'],
		['the signed-out page', '/login', '/'],
		['the signed-out page spelled encoded', '/%6Cogin', '/'],
		['the sign-in start', '/login/oidc?next=/x', '/'],
		['the signed-out page in capitals', '/LOGIN/', '/'],
		['the no-access page', '/no-access', '/'],
		['the failed sign-in page', '/auth/callback', '/'],
		['an API address', '/api/auth/me', '/'],
		['an API address spelled encoded', '/%61pi/auth/me', '/'],
		['the API root in capitals', '/API', '/']
	])('asks to return from %s to %s', (_label, returnTo, target) => {
		expect(signInAddress(returnTo)).toBe(`${SIGN_IN_START}${encodeURIComponent(target)}`);
	});
});

describe('fetchMediaBytes', () => {
	afterEach(() => mockFetch.mockReset());

	it('925_M2_M1: returns the media bytes', async () => {
		const bytes = new Uint8Array([1, 2, 3]);
		mockFetch.mockResolvedValueOnce(new Response(bytes));
		expect(new Uint8Array(await fetchMediaBytes('/audio/a'))).toEqual(bytes);
	});

	it.each([401, 404, 429])(
		'925_M2_M1: a %i refuses media without app reactions',
		async (status) => {
			const told: string[] = [];
			onTestFinished(
				installRefusalReactions({
					rateLimited: () => told.push('rateLimited'),
					sessionLost: async () => {
						told.push('sessionLost');
					}
				})
			);
			mockFetch.mockResolvedValueOnce(new Response(null, { status }));
			const failure = await fetchMediaBytes('/audio/a').catch((error: unknown) => error);
			expect(failure).toBeInstanceOf(ApiError);
			expect(failure).toMatchObject({ status, detail: '', path: '/audio/a' });
			expect(told).toEqual([]);
		}
	);

	it.each(['request', 'body'])('925_M2_M3: propagates a failed media %s', async (stage) => {
		const failure = new TypeError('connection lost');
		if (stage === 'request') mockFetch.mockRejectedValueOnce(failure);
		else mockFetch.mockResolvedValueOnce({ ok: true, arrayBuffer: () => Promise.reject(failure) });
		await expect(fetchMediaBytes('/audio/a')).rejects.toBe(failure);
	});
});
