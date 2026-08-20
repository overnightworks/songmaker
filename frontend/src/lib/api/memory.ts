import type { MemoryBundle, MemoryScopeItem } from './types';
import { apiFetch } from './fetch';

export async function fetchMemory(songId: string | null = null): Promise<MemoryBundle> {
	const query = songId ? `?song_id=${encodeURIComponent(songId)}` : '';
	return apiFetch<MemoryBundle>(`/api/memory${query}`);
}

export async function saveUserMemory(body: string): Promise<MemoryScopeItem> {
	return apiFetch<MemoryScopeItem>('/api/memory/user', {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ body })
	});
}

export async function saveSongMemory(songId: string, body: string): Promise<MemoryScopeItem> {
	return apiFetch<MemoryScopeItem>(`/api/memory/songs/${songId}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ body })
	});
}

export async function saveAlbumMemory(albumId: string, body: string): Promise<MemoryScopeItem> {
	return apiFetch<MemoryScopeItem>(`/api/memory/albums/${albumId}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ body })
	});
}
