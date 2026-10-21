import type { AuthUser, LogoutResponse } from './types';
import { apiFetch } from './fetch';

export async function logout(): Promise<string> {
	const answer = await apiFetch<LogoutResponse>('/auth/logout', { method: 'POST' });
	return answer.logout_url;
}

export async function fetchMe(): Promise<AuthUser> {
	return apiFetch<AuthUser>('/api/auth/me');
}
