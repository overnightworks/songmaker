import type {
	AlbumItem,
	AuthUser,
	Capabilities,
	LoginAttemptItem,
	SessionItem,
	SetupRequired,
	SongItem,
	UserItem,
	VersionGenerationParams,
	VersionItem
} from './types';
import { getClaudeKey } from '$lib/stores/settings';

/* v8 ignore next 4 -- SSR guard, untestable in jsdom */
const API_KEY =
	typeof window !== 'undefined'
		? (new URLSearchParams(window.location.search).get('key') ?? '')
		: '';

function apiUrl(path: string): string {
	const sep = path.includes('?') ? '&' : '?';
	return API_KEY ? `${path}${sep}api_key=${API_KEY}` : path;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
	const resp = await fetch(apiUrl(path), { credentials: 'include', ...init });
	if (!resp.ok) throw new Error(`API ${path}: ${resp.status}`);
	return resp.json() as Promise<T>;
}

export async function fetchAlbums(): Promise<AlbumItem[]> {
	return apiFetch<AlbumItem[]>('/api/albums');
}

export async function createAlbum(title: string, artist: string = ''): Promise<AlbumItem> {
	return apiFetch<AlbumItem>('/api/albums', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ title, artist })
	});
}

export async function fetchSongs(albumId?: string): Promise<SongItem[]> {
	let path = '/api/songs';
	if (albumId) path += `?album_id=${albumId}`;
	const songs = await apiFetch<SongItem[]>(path);
	return songs.map((s) => ({ ...s, generations: s.generations ?? [] }));
}

export async function fetchSong(songId: string): Promise<SongItem> {
	return apiFetch<SongItem>(`/api/songs/${songId}`);
}

export async function createSong(params: {
	title: string;
	album_id: string;
	lyrics?: string;
	prompt?: string;
	bpm?: number;
	duration?: number;
	key?: string;
	language?: string;
}): Promise<SongItem> {
	return apiFetch<SongItem>('/api/songs', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(params)
	});
}

export async function updateSong(
	songId: string,
	params: {
		lyrics?: string;
		prompt?: string;
		bpm?: number;
		duration?: number;
		key?: string;
		generation_params?: VersionGenerationParams | null;
	}
): Promise<SongItem> {
	return apiFetch<SongItem>(`/api/songs/${songId}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(params)
	});
}

export async function fetchVersions(songId: string): Promise<VersionItem[]> {
	return apiFetch<VersionItem[]>(`/api/songs/${songId}/versions`);
}

export async function deleteVersion(versionId: string, deleteGenerations: boolean): Promise<void> {
	await apiFetch(`/api/versions/${versionId}?delete_generations=${deleteGenerations}`, {
		method: 'DELETE'
	});
}

export async function deleteGeneration(genId: string): Promise<void> {
	await apiFetch(`/api/generations/${genId}`, { method: 'DELETE' });
}

export interface JobStatus {
	id: string;
	type: string;
	status: string;
	progress: number;
	error: string | null;
	error_type: string | null;
	started_at: string | null;
	completed_at: string | null;
}

export async function generateSong(songId: string, count: number = 1): Promise<JobStatus> {
	return apiFetch<JobStatus>(`/api/songs/${songId}/generate`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ count })
	});
}

export async function scoreGeneration(genId: string): Promise<JobStatus> {
	return apiFetch<JobStatus>(`/api/generations/${genId}/score`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({})
	});
}

export async function fetchJob(jobId: string): Promise<JobStatus> {
	return apiFetch<JobStatus>(`/api/jobs/${jobId}`);
}

export async function pickGeneration(genId: string): Promise<void> {
	await apiFetch(`/api/generations/${genId}/pick`, { method: 'POST' });
}

export async function unpickGeneration(genId: string): Promise<void> {
	await apiFetch(`/api/generations/${genId}/unpick`, { method: 'POST' });
}

export async function cleanupAlbum(albumId: string): Promise<{ deleted: number }> {
	return apiFetch<{ deleted: number }>(`/api/albums/${albumId}/cleanup`, { method: 'POST' });
}

export async function fetchCapabilities(): Promise<Capabilities> {
	return apiFetch<Capabilities>('/api/capabilities');
}

export async function fetchGenerationDefaults(): Promise<Record<string, VersionGenerationParams>> {
	return apiFetch<Record<string, VersionGenerationParams>>('/api/settings/generation-defaults');
}

export async function updateGenerationDefaults(
	data: Record<string, VersionGenerationParams>
): Promise<Record<string, VersionGenerationParams>> {
	return apiFetch<Record<string, VersionGenerationParams>>('/api/settings/generation-defaults', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data)
	});
}

// ── Auth ──────────────────────────────────────────────────────────

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

export async function chatWithClaude(
	message: string,
	context: string = '',
	system: string = ''
): Promise<string> {
	const headers: Record<string, string> = { 'Content-Type': 'application/json' };
	const claudeKey = getClaudeKey();
	if (claudeKey) headers['X-Claude-Key'] = claudeKey;

	const resp = await fetch(apiUrl('/api/chat'), {
		method: 'POST',
		headers,
		body: JSON.stringify({ message, context, system })
	});
	if (!resp.ok) {
		if (resp.status === 503) throw new Error('Claude unavailable. Add API key in settings.');
		throw new Error(`Chat failed: ${resp.status}`);
	}
	const data = await resp.json();
	return data.response;
}

// ── Admin ─────────────────────────────────────────────────────────

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

export async function fetchSessions(): Promise<SessionItem[]> {
	return apiFetch<SessionItem[]>('/api/admin/sessions');
}

export async function forceLogout(sessionId: string): Promise<void> {
	await apiFetch(`/api/admin/sessions/${sessionId}`, { method: 'DELETE' });
}

export async function fetchLoginAttempts(limit: number = 100): Promise<LoginAttemptItem[]> {
	return apiFetch<LoginAttemptItem[]>(`/api/admin/login-attempts?limit=${limit}`);
}

export async function getAceStepStatus(): Promise<{
	online: boolean;
	model: string | null;
	lm_model: string | null;
	jobs: Record<string, number>;
}> {
	return apiFetch('/api/admin/acestep/status');
}

export async function reinitializeAceStep(): Promise<void> {
	await apiFetch('/api/admin/acestep/reinitialize', { method: 'POST' });
}

export async function changePassword(current: string, newPassword: string): Promise<void> {
	await apiFetch('/api/auth/password', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ current, new_password: newPassword })
	});
}
