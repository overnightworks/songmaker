import type { JobItem } from './types';

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
