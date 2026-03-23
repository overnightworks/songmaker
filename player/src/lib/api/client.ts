import type { AlbumItem, PaginatedResponse, VersionItem } from './types';

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
