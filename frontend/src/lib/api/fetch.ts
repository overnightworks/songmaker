import type { JobItem } from './types';

export const API_TIMEOUT_MS = 30_000;
export const CHAT_TIMEOUT_MS = 120_000;

export class ApiError extends Error {
	constructor(
		public readonly status: number,
		public readonly detail: string,
		public readonly path: string
	) {
		super(detail || `API ${path}: ${status}`);
		this.name = 'ApiError';
	}
}

function getCsrfToken(): string {
	const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
	return match ? decodeURIComponent(match[1]) : '';
}

const AUTH_ENDPOINTS = ['/api/auth/login', '/api/auth/setup'];

export async function apiFetch<T>(
	path: string,
	init?: RequestInit,
	timeoutMs?: number
): Promise<T> {
	const method = init?.method?.toUpperCase() ?? 'GET';
	const controller = new AbortController();
	const timeout = setTimeout(() => controller.abort(), timeoutMs ?? API_TIMEOUT_MS);
	let opts: RequestInit = { credentials: 'include', signal: controller.signal, ...init };
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
			throw new ApiError(resp.status, detail, path);
		}
		return resp.json() as Promise<T>;
	} finally {
		clearTimeout(timeout);
	}
}

export type JobStatus = JobItem;
