import type {
	JobItem,
	LoginAttemptItem,
	PaginatedResponse,
	RegistryResponse,
	SessionItem,
	UserItem,
	WorkerPoolResponse
} from './types';
import { apiFetch } from './fetch';

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

export async function listWorkers(): Promise<WorkerPoolResponse> {
	return apiFetch<WorkerPoolResponse>('/api/admin/workers');
}

export async function getRegistry(): Promise<RegistryResponse> {
	return apiFetch<RegistryResponse>('/api/admin/registry');
}

export async function loadModelOnWorker(workerId: string, mode: string): Promise<JobItem> {
	return apiFetch<JobItem>(`/api/admin/workers/${workerId}/load_model`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ mode })
	});
}

export async function evictModelOnWorker(workerId: string, mode: string): Promise<void> {
	await apiFetch(`/api/admin/workers/${workerId}/evict_model`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ mode })
	});
}

export async function downloadModel(mode: string): Promise<JobItem> {
	return apiFetch<JobItem>(`/api/admin/registry/${encodeURIComponent(mode)}/download`, {
		method: 'POST'
	});
}
