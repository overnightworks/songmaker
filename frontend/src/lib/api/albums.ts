import type { AlbumItem, CleanupResult, PaginatedResponse, ShareResult } from './types';
import { apiFetch } from './fetch';

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

export async function deleteAlbum(albumId: string): Promise<void> {
	await apiFetch(`/api/albums/${albumId}`, { method: 'DELETE' });
}

export async function cleanupAlbum(albumId: string): Promise<CleanupResult> {
	return apiFetch<CleanupResult>(`/api/albums/${albumId}/cleanup`, { method: 'POST' });
}
