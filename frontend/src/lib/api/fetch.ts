import { get } from 'svelte/store';
import type { JobItem } from './types';
import {
	API_ERROR_GENERIC_MESSAGE,
	RATE_LIMITED_TOAST_MESSAGE,
	SESSION_LOST_REDIRECT_PARAM
} from '$lib/constants';
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
		super(detail || API_ERROR_GENERIC_MESSAGE);
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

function isSessionLostResponse(status: number, path: string): boolean {
	return status === 401 && !AUTH_ENDPOINTS.includes(path);
}

// The one reaction to "the session is gone", for the whole app (issue #385).
// apiFetch and sseFetch below call this directly on their own 401 (every
// other response reads its own status, but what a 401 *means* and what to do
// about it is decided here, once). Two callers outside this module reach it
// too, because they detect a lost session a way apiFetch never sees: an
// audio element's stream/media probe (`stores/player.ts`'s `onAuthLost`
// callback, wired from `audioPlayer.svelte.ts`) and a dropped SSE
// connection's auth probe (`stores/resourceSync.ts`'s `onUnauthorized`,
// which also treats a 403 on `/api/auth/me` as a lost session -- a disabled
// account -- something a plain 401 check can't tell apart from an ordinary
// ownership 403 elsewhere in the app). All three funnel into this one
// function instead of each clearing auth and navigating on their own.
//
// A visitor who was never signed in (first load with no cookie, or a second
// caller losing the race after the first already cleared it) has no session
// to lose: `currentUser` is already null, and the app's own unauthenticated
// routing (`+layout.svelte`'s `initAuth`) already knows whether that sends
// them to /login or /setup, so this leaves it alone rather than forcing a
// redirect that can race that more informed choice.
//
// A concurrent second caller -- e.g. resourceSync's own auth probe racing an
// ordinary apiFetch call that both fail with 401 at once -- joins the same
// in-flight run instead of repeating the redirect, so the listener is told
// exactly once no matter how many places noticed at the same time.
let sessionLostRun: Promise<void> | null = null;

export function handleSessionLost(): Promise<void> {
	if (!sessionLostRun) {
		sessionLostRun = reactToSessionLost().finally(() => {
			sessionLostRun = null;
		});
	}
	return sessionLostRun;
}

async function reactToSessionLost(): Promise<void> {
	const { currentUser, clearAuth } = await import('$lib/stores/auth');
	if (get(currentUser) === null) return;
	clearAuth();
	const { goto } = await import('$app/navigation');
	const returnTo = window.location.pathname + window.location.search;
	await goto(`/login?${SESSION_LOST_REDIRECT_PARAM}=${encodeURIComponent(returnTo)}`);
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
			if (isSessionLostResponse(resp.status, path)) await handleSessionLost();
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
			if (isSessionLostResponse(resp.status, path)) await handleSessionLost();
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
