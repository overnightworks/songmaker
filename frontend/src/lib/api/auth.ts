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

interface LogoutAnswer {
	/** The identity provider's address, which ends its own session too. */
	logout_url: string;
}

export async function logout(): Promise<string> {
	const answer = await apiFetch<LogoutAnswer>('/auth/logout', { method: 'POST' });
	return answer.logout_url;
}

export async function fetchMe(): Promise<AuthUser> {
	return apiFetch<AuthUser>('/api/auth/me');
}
