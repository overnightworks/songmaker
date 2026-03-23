import type { AlbumItem, Capabilities, PaginatedResponse, VersionItem } from './types';
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

export async function fetchLibrary(
	albumId?: string,
	limit = 200,
	offset = 0
): Promise<PaginatedResponse> {
	let path = `/api/library?limit=${limit}&offset=${offset}`;
	if (albumId) path += `&album_id=${albumId}`;
	return apiFetch<PaginatedResponse>(path);
}

export async function fetchVersions(songId: string): Promise<VersionItem[]> {
	return apiFetch<VersionItem[]>(`/api/songs/${songId}/versions`);
}

export async function fetchVersion(versionId: string): Promise<VersionItem> {
	return apiFetch<VersionItem>(`/api/versions/${versionId}`);
}

export async function rateVersion(
	album: string,
	version: string,
	rating: number,
	notes: string
): Promise<void> {
	await apiFetch(`/api/rate/${album}/${version}`, {
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
	if (claudeKey) {
		headers['X-Claude-Key'] = claudeKey;
	}
	const resp = await fetch(apiUrl('/api/chat'), {
		method: 'POST',
		headers,
		body: JSON.stringify({ message, context, system })
	});
	if (!resp.ok) {
		if (resp.status === 503)
			throw new Error('Claude is not available. Add an API key in settings.');
		throw new Error(`Chat failed: ${resp.status}`);
	}
	const data = await resp.json();
	return data.response;
}
