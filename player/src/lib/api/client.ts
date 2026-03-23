import type { AlbumItem, Capabilities, SongItem, VersionItem } from './types';
import { getClaudeKey } from '$lib/stores/settings';

const API_KEY =
	typeof window !== 'undefined'
		? (new URLSearchParams(window.location.search).get('key') ?? '')
		: '';

function apiUrl(path: string): string {
	const sep = path.includes('?') ? '&' : '?';
	return API_KEY ? `${path}${sep}api_key=${API_KEY}` : path;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
	const resp = await fetch(apiUrl(path), init);
	if (!resp.ok) throw new Error(`API ${path}: ${resp.status}`);
	return resp.json() as Promise<T>;
}

export async function fetchAlbums(): Promise<AlbumItem[]> {
	return apiFetch<AlbumItem[]>('/api/albums');
}

export async function fetchSongs(albumId?: string): Promise<SongItem[]> {
	let path = '/api/songs';
	if (albumId) path += `?album_id=${albumId}`;
	return apiFetch<SongItem[]>(path);
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
	params: { lyrics?: string; prompt?: string; bpm?: number; duration?: number; key?: string }
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

export async function rateGeneration(
	album: string,
	genName: string,
	rating: number,
	notes: string
): Promise<void> {
	await apiFetch(`/api/rate/${album}/${genName}`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ rating, notes })
	});
}

export async function fetchCapabilities(): Promise<Capabilities> {
	return apiFetch<Capabilities>('/api/capabilities');
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
