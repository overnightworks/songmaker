import type {
	AlbumItem,
	AuthUser,
	Capabilities,
	ChatResult,
	CleanupResult,
	JobItem,
	LoginAttemptItem,
	PaginatedResponse,
	PlaylistDetailItem,
	PlaylistEntryItem,
	PlaylistItem,
	PresetItem,
	RateLimitsResponse,
	RateResult,
	SessionItem,
	SetupRequired,
	ShareResult,
	SongItem,
	UserItem,
	UserRateLimitsResponse,
	VersionGenerationParams,
	VersionItem
} from './types';

const API_TIMEOUT_MS = 30_000;
const CHAT_TIMEOUT_MS = 120_000;

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

async function apiFetch<T>(path: string, init?: RequestInit, timeoutMs?: number): Promise<T> {
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

export async function fetchAlbums(
	offset: number = 0,
	limit: number = 50
): Promise<PaginatedResponse<AlbumItem>> {
	return apiFetch<PaginatedResponse<AlbumItem>>(`/api/albums?offset=${offset}&limit=${limit}`);
}

export async function createAlbum(title: string, artist: string = ''): Promise<AlbumItem> {
	return apiFetch<AlbumItem>('/api/albums', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ title, artist })
	});
}

export async function shareAlbum(albumId: string): Promise<ShareResult> {
	return apiFetch<ShareResult>(`/api/albums/${albumId}/share`, { method: 'POST' });
}

export async function unshareAlbum(albumId: string): Promise<void> {
	await apiFetch(`/api/albums/${albumId}/share`, { method: 'DELETE' });
}

export async function shareSong(songId: string): Promise<ShareResult> {
	return apiFetch<ShareResult>(`/api/songs/${songId}/share`, { method: 'POST' });
}

export async function unshareSong(songId: string): Promise<void> {
	await apiFetch(`/api/songs/${songId}/share`, { method: 'DELETE' });
}

export async function shareGeneration(genId: string): Promise<ShareResult> {
	return apiFetch<ShareResult>(`/api/generations/${genId}/share`, { method: 'POST' });
}

export async function unshareGeneration(genId: string): Promise<void> {
	await apiFetch(`/api/generations/${genId}/share`, { method: 'DELETE' });
}

export async function fetchSongs(
	albumId?: string,
	offset: number = 0,
	limit: number = 50
): Promise<PaginatedResponse<SongItem>> {
	const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
	if (albumId) params.set('album_id', albumId);
	const resp = await apiFetch<PaginatedResponse<SongItem>>(`/api/songs?${params}`);
	return {
		...resp,
		items: resp.items.map((s) => ({ ...s, generations: s.generations ?? [] }))
	};
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

export async function deleteSong(songId: string): Promise<void> {
	await apiFetch(`/api/songs/${songId}`, { method: 'DELETE' });
}

export async function deleteAlbum(albumId: string): Promise<void> {
	await apiFetch(`/api/albums/${albumId}`, { method: 'DELETE' });
}

export async function moveSong(songId: string, albumId: string): Promise<SongItem> {
	return apiFetch<SongItem>(`/api/songs/${songId}/album`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ album_id: albumId })
	});
}

export type JobStatus = JobItem;

export async function generateSong(
	songId: string,
	count: number = 1,
	model?: string | null,
	versionId?: string | null,
	seed?: number | null
): Promise<JobStatus> {
	const payload: Record<string, unknown> = { count };
	if (model) payload.model = model;
	if (versionId) payload.version_id = versionId;
	if (seed != null) payload.seed = seed;
	return apiFetch<JobStatus>(`/api/songs/${songId}/generate`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
}

export async function repaintGeneration(
	genId: string,
	repaintingStart: number,
	repaintingEnd: number,
	lyrics?: string | null,
	prompt?: string | null,
	model?: string | null,
	seed?: number | null
): Promise<JobStatus> {
	const payload: Record<string, unknown> = {
		src_generation_id: genId,
		repainting_start: repaintingStart,
		repainting_end: repaintingEnd
	};
	if (lyrics != null) payload.lyrics = lyrics;
	if (prompt != null) payload.prompt = prompt;
	if (model) payload.model = model;
	if (seed != null) payload.seed = seed;
	return apiFetch<JobStatus>(`/api/generations/${genId}/repaint`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
}

export async function rateGeneration(
	genId: string,
	rating: number,
	notes: string = ''
): Promise<RateResult> {
	return apiFetch<RateResult>(`/api/generations/${genId}/rate`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ rating, notes })
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

export async function cancelJob(jobId: string): Promise<JobStatus> {
	return apiFetch<JobStatus>(`/api/jobs/${jobId}/cancel`, { method: 'POST' });
}

export async function pickGeneration(genId: string): Promise<void> {
	await apiFetch(`/api/generations/${genId}/pick`, { method: 'POST' });
}

export async function unpickGeneration(genId: string): Promise<void> {
	await apiFetch(`/api/generations/${genId}/unpick`, { method: 'POST' });
}

export async function cleanupAlbum(albumId: string): Promise<CleanupResult> {
	return apiFetch<CleanupResult>(`/api/albums/${albumId}/cleanup`, { method: 'POST' });
}

export async function cleanupSong(songId: string): Promise<CleanupResult> {
	return apiFetch<CleanupResult>(`/api/songs/${songId}/cleanup`, { method: 'POST' });
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

export interface ModelCapabilities {
	defaults: Record<string, unknown>;
	max_inference_steps: number;
	hidden_params: string[];
}

export interface AvailableModel {
	id: string;
	is_active: boolean;
	capabilities?: ModelCapabilities | null;
}

export async function fetchActiveModels(): Promise<AvailableModel[]> {
	return apiFetch<AvailableModel[]>('/api/settings/models');
}

export async function fetchAllModels(): Promise<AvailableModel[]> {
	return apiFetch<AvailableModel[]>('/api/settings/models/all');
}

export async function toggleModel(modelId: string, active: boolean): Promise<AvailableModel> {
	return apiFetch<AvailableModel>(`/api/settings/models/${modelId}?active=${active}`, {
		method: 'PUT'
	});
}

export interface ClaudeModelsResponse {
	chat_model: string;
	scoring_model: string;
	allowed_models: string[];
}

export async function fetchClaudeModels(): Promise<ClaudeModelsResponse> {
	return apiFetch<ClaudeModelsResponse>('/api/settings/claude-models');
}

export async function updateClaudeModels(
	chat_model: string,
	scoring_model: string
): Promise<ClaudeModelsResponse> {
	return apiFetch<ClaudeModelsResponse>('/api/settings/claude-models', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ chat_model, scoring_model })
	});
}

export async function fetchBuiltinDefaults(): Promise<Record<string, VersionGenerationParams>> {
	return apiFetch<Record<string, VersionGenerationParams>>('/api/settings/generation-builtins');
}

export async function fetchDefaultConfig(): Promise<{ config: string | null }> {
	return apiFetch<{ config: string | null }>('/api/settings/default-config');
}

export async function updateDefaultConfig(
	config: string | null
): Promise<{ config: string | null }> {
	return apiFetch<{ config: string | null }>('/api/settings/default-config', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ config })
	});
}

export async function fetchPresets(): Promise<PresetItem[]> {
	return apiFetch<PresetItem[]>('/api/settings/presets');
}

export async function createPreset(
	name: string,
	model_mode: string,
	params: VersionGenerationParams,
	is_default: boolean = false
): Promise<PresetItem> {
	return apiFetch<PresetItem>('/api/settings/presets', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ name, model_mode, params, is_default })
	});
}

export async function updatePreset(
	presetId: string,
	data: { name?: string; params?: VersionGenerationParams; is_default?: boolean }
): Promise<PresetItem> {
	return apiFetch<PresetItem>(`/api/settings/presets/${presetId}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(data)
	});
}

export async function deletePresetApi(presetId: string): Promise<void> {
	await apiFetch(`/api/settings/presets/${presetId}`, { method: 'DELETE' });
}

export async function setPresetDefault(presetId: string): Promise<PresetItem> {
	return apiFetch<PresetItem>(`/api/settings/presets/${presetId}/set-default`, { method: 'POST' });
}

// ── Playlists ────────────────────────────────────────────────────

export async function fetchPlaylists(): Promise<PlaylistItem[]> {
	return apiFetch<PlaylistItem[]>('/api/playlists');
}

export async function createPlaylist(title: string): Promise<PlaylistItem> {
	return apiFetch<PlaylistItem>('/api/playlists', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ title })
	});
}

export async function fetchPlaylist(id: string): Promise<PlaylistDetailItem> {
	return apiFetch<PlaylistDetailItem>(`/api/playlists/${id}`);
}

export async function updatePlaylist(id: string, title: string): Promise<PlaylistItem> {
	return apiFetch<PlaylistItem>(`/api/playlists/${id}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ title })
	});
}

export async function deletePlaylistApi(id: string): Promise<void> {
	await apiFetch(`/api/playlists/${id}`, { method: 'DELETE' });
}

export async function addGenerationToPlaylist(
	playlistId: string,
	generationId: string
): Promise<PlaylistEntryItem> {
	return apiFetch<PlaylistEntryItem>(`/api/playlists/${playlistId}/entries/generation`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ generation_id: generationId })
	});
}

export async function addSongToPlaylist(playlistId: string, songId: string): Promise<void> {
	await apiFetch(`/api/playlists/${playlistId}/entries/song`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ song_id: songId })
	});
}

export async function addAlbumToPlaylist(playlistId: string, albumId: string): Promise<void> {
	await apiFetch(`/api/playlists/${playlistId}/entries/album`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ album_id: albumId })
	});
}

export async function removeFromPlaylist(playlistId: string, entryId: string): Promise<void> {
	await apiFetch(`/api/playlists/${playlistId}/entries/${entryId}`, { method: 'DELETE' });
}

export async function reorderPlaylistEntry(
	playlistId: string,
	entryId: string,
	newPosition: number
): Promise<void> {
	await apiFetch(`/api/playlists/${playlistId}/entries/${entryId}/position`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ new_position: newPosition })
	});
}

export async function sharePlaylist(id: string): Promise<ShareResult> {
	return apiFetch<ShareResult>(`/api/playlists/${id}/share`, { method: 'POST' });
}

export async function unsharePlaylist(id: string): Promise<void> {
	await apiFetch(`/api/playlists/${id}/share`, { method: 'DELETE' });
}

export async function keepGeneration(genId: string): Promise<void> {
	await apiFetch(`/api/generations/${genId}/keep`, { method: 'POST' });
}

export async function unkeepGeneration(genId: string): Promise<void> {
	await apiFetch(`/api/generations/${genId}/unkeep`, { method: 'POST' });
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

export async function chatWithClaude(message: string, context: string = ''): Promise<string> {
	const data = await apiFetch<ChatResult>(
		'/api/chat',
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ message, context })
		},
		CHAT_TIMEOUT_MS
	);
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

// ── Rate limits ───────────────────────────────────────────────────

export async function fetchRateLimits(): Promise<RateLimitsResponse> {
	return apiFetch<RateLimitsResponse>('/api/settings/rate-limits');
}

export async function updateRateLimits(
	settings: Record<string, number>
): Promise<RateLimitsResponse> {
	return apiFetch<RateLimitsResponse>('/api/settings/rate-limits', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ settings })
	});
}

export async function fetchUserRateLimits(userId: string): Promise<UserRateLimitsResponse> {
	return apiFetch<UserRateLimitsResponse>(`/api/settings/rate-limits/user/${userId}`);
}

export async function updateUserRateLimits(
	userId: string,
	settings: Record<string, number>
): Promise<UserRateLimitsResponse> {
	return apiFetch<UserRateLimitsResponse>(`/api/settings/rate-limits/user/${userId}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ settings })
	});
}

export async function deleteUserRateLimits(userId: string): Promise<void> {
	await apiFetch(`/api/settings/rate-limits/user/${userId}`, { method: 'DELETE' });
}

export async function changePassword(current: string, newPassword: string): Promise<void> {
	await apiFetch('/api/auth/password', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ current, new_password: newPassword })
	});
}
