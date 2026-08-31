import { get } from 'svelte/store';
import type { JobItem } from './types';
import { RATE_LIMITED_TOAST_MESSAGE } from '$lib/constants';
import { addToast, toasts } from '$lib/stores/toast';

export const API_TIMEOUT_MS = 30_000;
export const CHAT_TIMEOUT_MS = 600_000;

export class ApiError extends Error {
	constructor(
		public readonly status: number,
		public readonly detail: string,
		public readonly path: string,
		public readonly retryAfterSeconds: number | null = null
	) {
		super(detail || `API ${path}: ${status}`);
		this.name = 'ApiError';
	}
}

export function isRateLimited(err: unknown): boolean {
	return err instanceof ApiError && err.status === 429;
}

export function isNotFound(err: unknown): boolean {
	return err instanceof ApiError && err.status === 404;
}

function parseRetryAfterSeconds(resp: {
	headers?: { get: (name: string) => string | null };
}): number | null {
	const header = resp.headers?.get?.('Retry-After') ?? null;
	if (!header) return null;
	const seconds = Number(header);
	return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

function getCsrfToken(): string {
	const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
	return match ? decodeURIComponent(match[1]) : '';
}

const AUTH_ENDPOINTS = ['/api/auth/login', '/api/auth/setup'];

// A path whose own 429 is already visible some other way, so the generic
// toast below would only repeat it. Kept as its own literal list, not
// derived from `AUTH_ENDPOINTS` above (that one exists for the unrelated
// 401-redirect suppression) -- a future path added there for its 401 reason
// should not silently also lose this toast.
//   - '/api/auth/login': `stores/auth.ts`'s `login()` turns a 429 into
//     "Too many attempts. Try again later." under the login form.
//   - '/api/auth/me': `stores/auth.ts`'s `checkAuth()` turns a 429 into the
//     full-page session-check retry banner.
//   - '/api/auth/setup': not auth.ts -- `routes/setup/+page.svelte`'s own
//     catch block shows the error inline via `err.message`.
const RATE_LIMIT_TOAST_EXEMPT_PATHS = new Set([
	'/api/auth/login',
	'/api/auth/me',
	'/api/auth/setup'
]);

/**
 * Never more than one throttle toast on screen at once, not one per
 * rejected request: a 429 burst calls this many times in a row, but a
 * toast already showing the same message is left alone instead of being
 * duplicated (issue #257). The toast auto-dismisses after 5s (`addToast`'s
 * 'info' type), so a burst that outlasts that raises a fresh toast every
 * ~5s for as long as it's still being throttled -- which reads as "still
 * throttled", not as a bug.
 */
function notifyIfRateLimited(status: number, path: string): void {
	if (status !== 429 || RATE_LIMIT_TOAST_EXEMPT_PATHS.has(path)) return;
	const alreadyShown = get(toasts).some((toast) => toast.message === RATE_LIMITED_TOAST_MESSAGE);
	if (alreadyShown) return;
	addToast(RATE_LIMITED_TOAST_MESSAGE, 'info');
}

function abortOnCallerOrTimeout(
	callerSignal: AbortSignal | null | undefined,
	timeoutSignal: AbortSignal
): AbortSignal {
	return callerSignal ? AbortSignal.any([callerSignal, timeoutSignal]) : timeoutSignal;
}

export async function apiFetch<T>(
	path: string,
	init?: RequestInit,
	timeoutMs?: number
): Promise<T> {
	const method = init?.method?.toUpperCase() ?? 'GET';
	const controller = new AbortController();
	const timeout = setTimeout(() => controller.abort(), timeoutMs ?? API_TIMEOUT_MS);
	let opts: RequestInit = {
		credentials: 'include',
		...init,
		signal: abortOnCallerOrTimeout(init?.signal, controller.signal)
	};
	if (method !== 'GET' && method !== 'HEAD') {
		const token = getCsrfToken();
		if (token) {
			opts = {
				...opts,
				headers: { 'X-CSRF-Token': token, ...(init?.headers as Record<string, string>) }
			};
		}
	}
	try {
		const resp = await fetch(path, opts);
		if (!resp.ok) {
			let detail = '';
			try {
				const body = await resp.json();
				detail = body.detail ?? '';
			} catch {
				// response body not JSON — use empty detail
			}
			notifyIfRateLimited(resp.status, path);
			if (resp.status === 401 && !AUTH_ENDPOINTS.includes(path)) {
				const { clearAuth } = await import('$lib/stores/auth');
				const { goto } = await import('$app/navigation');
				clearAuth();
				await goto('/login');
			}
			throw new ApiError(resp.status, detail, path, parseRetryAfterSeconds(resp));
		}
		return resp.json() as Promise<T>;
	} finally {
		clearTimeout(timeout);
	}
}

export type JobStatus = JobItem;

export async function* sseFetch<T = unknown>(
	path: string,
	init: RequestInit,
	timeoutMs?: number
): AsyncGenerator<T> {
	const method = init.method?.toUpperCase() ?? 'GET';
	const controller = new AbortController();
	const timeout = setTimeout(() => controller.abort(), timeoutMs ?? API_TIMEOUT_MS);
	let opts: RequestInit = {
		credentials: 'include',
		...init,
		signal: abortOnCallerOrTimeout(init.signal, controller.signal),
		headers: {
			Accept: 'text/event-stream',
			...((init.headers as Record<string, string>) ?? {})
		}
	};
	if (method !== 'GET' && method !== 'HEAD') {
		const token = getCsrfToken();
		if (token) {
			opts = {
				...opts,
				headers: { 'X-CSRF-Token': token, ...(opts.headers as Record<string, string>) }
			};
		}
	}
	try {
		const resp = await fetch(path, opts);
		if (!resp.ok) {
			let detail = '';
			try {
				const body = await resp.json();
				detail = body.detail ?? '';
			} catch {
				// non-JSON body on error
			}
			notifyIfRateLimited(resp.status, path);
			if (resp.status === 401 && !AUTH_ENDPOINTS.includes(path)) {
				const { clearAuth } = await import('$lib/stores/auth');
				const { goto } = await import('$app/navigation');
				clearAuth();
				await goto('/login');
			}
			throw new ApiError(resp.status, detail, path, parseRetryAfterSeconds(resp));
		}
		if (!resp.body) {
			return;
		}
		const reader = resp.body.getReader();
		const decoder = new TextDecoder('utf-8');
		let buffer = '';
		while (true) {
			const { value, done } = await reader.read();
			if (done) break;
			buffer += decoder.decode(value, { stream: true });
			let boundary = buffer.indexOf('\n\n');
			while (boundary !== -1) {
				const frame = buffer.slice(0, boundary);
				buffer = buffer.slice(boundary + 2);
				const line = frame.split('\n').find((l) => l.startsWith('data: '));
				if (line) {
					const json = line.slice('data: '.length);
					try {
						yield JSON.parse(json) as T;
					} catch {
						// drop malformed frame
					}
				}
				boundary = buffer.indexOf('\n\n');
			}
		}
	} finally {
		clearTimeout(timeout);
	}
}
