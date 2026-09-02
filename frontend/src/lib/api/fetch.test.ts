import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

vi.mock('$lib/stores/auth', () => ({ clearAuth: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import { API_TIMEOUT_MS, apiFetch, sseFetch, ApiError, isRateLimited } from './fetch';
import { API_ERROR_GENERIC_MESSAGE, RATE_LIMITED_TOAST_MESSAGE } from '$lib/constants';
import { dismissToast, toasts } from '$lib/stores/toast';

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
		expect(isRateLimited(err)).toBe(true);
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
		expect(isRateLimited(err)).toBe(false);
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

	it('does not toast for a path auth.ts already surfaces its own 429 copy for', async () => {
		mockFetch.mockResolvedValue(rateLimitedResponse());

		await apiFetch('/api/auth/login', { method: 'POST' }).catch((e: unknown) => e);
		await apiFetch('/api/auth/me').catch((e: unknown) => e);

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

	it('still times out when the caller never aborts', () => {
		vi.useFakeTimers();
		neverResolvingFetch();
		const caller = new AbortController();
		void apiFetch('/api/library/pool-queue', { signal: caller.signal }).catch(() => {});
		vi.advanceTimersByTime(API_TIMEOUT_MS - 1);
		expect(signalPassedToFetch().aborted).toBe(false);
		vi.advanceTimersByTime(1);
		expect(signalPassedToFetch().aborted).toBe(true);
		expect(caller.signal.aborted).toBe(false);
	});
});
