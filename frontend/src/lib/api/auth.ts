import type { AuthUser } from './types';
import { apiFetch } from './fetch';

export async function login(username: string, password: string): Promise<AuthUser> {
	return apiFetch<AuthUser>('/api/auth/login', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ username, password })
	});
}

export async function logout(): Promise<void> {
	await apiFetch('/api/auth/session', { method: 'DELETE' });
}

export async function fetchMe(): Promise<AuthUser> {
	return apiFetch<AuthUser>('/api/auth/me');
}
