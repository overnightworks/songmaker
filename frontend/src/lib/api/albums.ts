import type { AlbumItem, CleanupResult, PaginatedResponse, ShareResult } from './types';
import { apiFetch } from './fetch';
import type { LibraryListOptions } from './library';

export async function fetchAlbum(albumId: string): Promise<AlbumItem> {
	return apiFetch<AlbumItem>(`/api/albums/${albumId}`);
}

export async function fetchAlbums(
	offset: number = 0,
	limit: number = 50,
	options?: LibraryListOptions
): Promise<PaginatedResponse<AlbumItem>> {
	const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
	if (options?.q) params.set('q', options.q);
	if (options?.sort) params.set('sort', options.sort);
	if (options?.archived) params.set('archived', 'true');
	return apiFetch<PaginatedResponse<AlbumItem>>(`/api/albums?${params}`);
}

export async function createAlbum(title: string, artist: string = ''): Promise<AlbumItem> {
	return apiFetch<AlbumItem>('/api/albums', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ title, artist })
	});
}

/**
 * Update album title, subtitle, and/or year independently. A field left
 * out of `fields` is left unchanged server-side; passing `null` for year
 * clears it, and an empty string clears the subtitle.
 */
export async function updateAlbum(
	albumId: string,
	fields: { title?: string; subtitle?: string; year?: number | null }
): Promise<AlbumItem> {
	return apiFetch<AlbumItem>(`/api/albums/${albumId}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(fields)
	});
}

export async function shareAlbum(albumId: string): Promise<ShareResult> {
	return apiFetch<ShareResult>(`/api/albums/${albumId}/share`, { method: 'POST' });
}

export async function unshareAlbum(albumId: string): Promise<void> {
	await apiFetch(`/api/albums/${albumId}/share`, { method: 'DELETE' });
}

export async function deleteAlbum(albumId: string): Promise<void> {
	await apiFetch(`/api/albums/${albumId}`, { method: 'DELETE' });
}

export async function restoreAlbum(albumId: string): Promise<AlbumItem> {
	return apiFetch<AlbumItem>(`/api/albums/${albumId}/restore`, { method: 'POST' });
}

export async function archiveAlbum(albumId: string): Promise<AlbumItem> {
	return apiFetch<AlbumItem>(`/api/albums/${albumId}/archive`, { method: 'POST' });
}

export async function unarchiveAlbum(albumId: string): Promise<AlbumItem> {
	return apiFetch<AlbumItem>(`/api/albums/${albumId}/unarchive`, { method: 'POST' });
}

export async function cleanupAlbum(albumId: string): Promise<CleanupResult> {
	return apiFetch<CleanupResult>(`/api/albums/${albumId}/cleanup`, { method: 'POST' });
}
