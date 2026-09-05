import type {
	AddAlbumToPlaylistResult,
	PlaylistDetailItem,
	PlaylistEntryItem,
	PlaylistItem,
	ShareResult
} from './types';
import { apiFetch } from './fetch';

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

export async function addAlbumToPlaylist(
	playlistId: string,
	albumId: string
): Promise<AddAlbumToPlaylistResult> {
	return apiFetch<AddAlbumToPlaylistResult>(`/api/playlists/${playlistId}/entries/album`, {
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

export async function uploadPlaylistCover(playlistId: string, file: File): Promise<PlaylistItem> {
	const form = new FormData();
	form.append('file', file);
	return apiFetch<PlaylistItem>(`/api/playlists/${playlistId}/cover`, {
		method: 'PUT',
		body: form
	});
}

export async function deletePlaylistCover(playlistId: string): Promise<PlaylistItem> {
	return apiFetch<PlaylistItem>(`/api/playlists/${playlistId}/cover`, { method: 'DELETE' });
}
