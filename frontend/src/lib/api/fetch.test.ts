import { afterEach, describe, expect, it, vi } from 'vitest';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

vi.mock('$lib/stores/auth', () => ({ clearAuth: vi.fn() }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

import { API_TIMEOUT_MS, apiFetch, sseFetch, ApiError } from './fetch';

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
