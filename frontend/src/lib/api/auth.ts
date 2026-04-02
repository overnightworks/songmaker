import type { AuthUser, SetupRequired } from './types';
import { apiFetch } from './fetch';

export async function checkSetupRequired(): Promise<SetupRequired> {
	return apiFetch<SetupRequired>('/api/auth/setup-required');
}

export async function setupAdmin(username: string, password: string): Promise<AuthUser> {
	return apiFetch<AuthUser>('/api/auth/setup', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ username, password })
	});
}

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

export async function changePassword(current: string, newPassword: string): Promise<void> {
	await apiFetch('/api/auth/password', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ current, new_password: newPassword })
	});
}
