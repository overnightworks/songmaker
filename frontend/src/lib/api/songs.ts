import type { CleanupResult, PaginatedResponse, ShareResult, SongItem, VersionItem } from './types';
import { apiFetch } from './fetch';
import type { LibraryListOptions } from './library';

export async function fetchSongs(
	albumId?: string,
	offset: number = 0,
	limit: number = 200,
	options?: LibraryListOptions
): Promise<PaginatedResponse<SongItem>> {
	const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
	if (albumId) params.set('album_id', albumId);
	if (options?.q) params.set('q', options.q);
	if (options?.sort) params.set('sort', options.sort);
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
	audio_duration?: number;
	key_scale?: string;
	vocal_language?: string;
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
		audio_duration?: number;
		key_scale?: string;
		generation_params?: import('./types').VersionGenerationParams | null;
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

export async function deleteSong(songId: string): Promise<void> {
	await apiFetch(`/api/songs/${songId}`, { method: 'DELETE' });
}

export async function restoreSong(songId: string): Promise<SongItem> {
	return apiFetch<SongItem>(`/api/songs/${songId}/restore`, { method: 'POST' });
}

export async function moveSong(songId: string, albumId: string): Promise<SongItem> {
	return apiFetch<SongItem>(`/api/songs/${songId}/album`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ album_id: albumId })
	});
}

export async function renameSong(songId: string, title: string): Promise<SongItem> {
	return apiFetch<SongItem>(`/api/songs/${songId}/title`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ title })
	});
}

export async function shareSong(songId: string): Promise<ShareResult> {
	return apiFetch<ShareResult>(`/api/songs/${songId}/share`, { method: 'POST' });
}

export async function unshareSong(songId: string): Promise<void> {
	await apiFetch(`/api/songs/${songId}/share`, { method: 'DELETE' });
}

export async function cleanupSong(songId: string): Promise<CleanupResult> {
	return apiFetch<CleanupResult>(`/api/songs/${songId}/cleanup`, { method: 'POST' });
}
