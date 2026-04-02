import type { LoginAttemptItem, PaginatedResponse, SessionItem, UserItem } from './types';
import { apiFetch, type JobStatus } from './fetch';

export async function fetchUsers(): Promise<UserItem[]> {
	return apiFetch<UserItem[]>('/api/admin/users');
}

export async function createUser(
	username: string,
	password: string,
	role: string = 'user'
): Promise<UserItem> {
	return apiFetch<UserItem>('/api/admin/users', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ username, password, role })
	});
}

export async function updateUser(
	userId: string,
	data: { role?: string; is_active?: boolean; password?: string }
): Promise<UserItem> {
	return apiFetch<UserItem>(`/api/admin/users/${userId}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data)
	});
}

export async function deactivateUser(userId: string): Promise<void> {
	await apiFetch(`/api/admin/users/${userId}`, { method: 'DELETE' });
}

export async function hardDeleteUser(userId: string): Promise<void> {
	await apiFetch(`/api/admin/users/${userId}/permanent`, { method: 'DELETE' });
}

export async function fetchSessions(
	offset: number = 0,
	limit: number = 100
): Promise<PaginatedResponse<SessionItem>> {
	return apiFetch<PaginatedResponse<SessionItem>>(
		`/api/admin/sessions?offset=${offset}&limit=${limit}`
	);
}

export async function forceLogout(sessionId: string): Promise<void> {
	await apiFetch(`/api/admin/sessions/${sessionId}`, { method: 'DELETE' });
}

export async function fetchLoginAttempts(
	offset: number = 0,
	limit: number = 100
): Promise<PaginatedResponse<LoginAttemptItem>> {
	return apiFetch<PaginatedResponse<LoginAttemptItem>>(
		`/api/admin/login-attempts?offset=${offset}&limit=${limit}`
	);
}

export async function getAceStepStatus(): Promise<{
	online: boolean;
	model: string | null;
	lm_model: string | null;
	jobs: Record<string, number>;
}> {
	return apiFetch('/api/admin/acestep/status');
}

export async function reinitializeAceStep(targetModel?: string): Promise<JobStatus> {
	return apiFetch<JobStatus>('/api/admin/acestep/reinitialize', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ target_model: targetModel ?? null })
	});
}
