import type { AuthUser, LogoutResponse, SetupRequired } from './types';
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

export async function logout(): Promise<string> {
	const answer = await apiFetch<LogoutResponse>('/auth/logout', { method: 'POST' });
	return answer.logout_url;
}

export async function fetchMe(): Promise<AuthUser> {
	return apiFetch<AuthUser>('/api/auth/me');
}
