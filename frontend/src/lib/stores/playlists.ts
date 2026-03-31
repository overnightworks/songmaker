import { writable, derived, get } from 'svelte/store';
import {
	fetchPlaylists,
	fetchPlaylist,
	createPlaylist as apiCreatePlaylist,
	deletePlaylistApi,
	updatePlaylist as apiUpdatePlaylist,
	addGenerationToPlaylist as apiAddGen,
	addSongToPlaylist as apiAddSong,
	addAlbumToPlaylist as apiAddAlbum,
	removeFromPlaylist as apiRemoveEntry,
	reorderPlaylistEntry as apiReorder
} from '$lib/api/client';
import type { PlaylistDetailItem, PlaylistItem } from '$lib/api/types';

export const playlistList = writable<PlaylistItem[]>([]);
export const selectedPlaylistId = writable<string | null>(null);
export const selectedPlaylistDetail = writable<PlaylistDetailItem | null>(null);

export const selectedPlaylist = derived(
	[playlistList, selectedPlaylistId],
	([$list, $id]) => $list.find((p) => p.id === $id) ?? null
);

export async function loadPlaylists(): Promise<void> {
	const items = await fetchPlaylists();
	playlistList.set(items);
}

export async function loadPlaylistDetail(id: string): Promise<void> {
	const detail = await fetchPlaylist(id);
	selectedPlaylistDetail.set(detail);
}

export function selectPlaylist(id: string): void {
	selectedPlaylistId.set(id);
	loadPlaylistDetail(id);
}

export function deselectPlaylist(): void {
	selectedPlaylistId.set(null);
	selectedPlaylistDetail.set(null);
}

export async function createNewPlaylist(title: string): Promise<PlaylistItem> {
	const playlist = await apiCreatePlaylist(title);
	playlistList.update((list) => [...list, playlist]);
	return playlist;
}

export async function renamePlaylist(id: string, title: string): Promise<void> {
	const updated = await apiUpdatePlaylist(id, title);
	playlistList.update((list) => list.map((p) => (p.id === id ? updated : p)));
	const detail = get(selectedPlaylistDetail);
	if (detail && detail.id === id) {
		selectedPlaylistDetail.update((d) => (d ? { ...d, title } : d));
	}
}

export async function deletePlaylist(id: string): Promise<void> {
	await deletePlaylistApi(id);
	playlistList.update((list) => list.filter((p) => p.id !== id));
	if (get(selectedPlaylistId) === id) {
		deselectPlaylist();
	}
}

export async function addGenerationToPlaylist(playlistId: string, genId: string): Promise<void> {
	await apiAddGen(playlistId, genId);
	await refreshPlaylist(playlistId);
}

export async function addSongToPlaylist(playlistId: string, songId: string): Promise<void> {
	await apiAddSong(playlistId, songId);
	await refreshPlaylist(playlistId);
}

export async function addAlbumToPlaylist(playlistId: string, albumId: string): Promise<void> {
	await apiAddAlbum(playlistId, albumId);
	await refreshPlaylist(playlistId);
}

export async function removePlaylistEntry(playlistId: string, entryId: string): Promise<void> {
	await apiRemoveEntry(playlistId, entryId);
	await refreshPlaylist(playlistId);
}

export async function movePlaylistEntry(
	playlistId: string,
	entryId: string,
	newPosition: number
): Promise<void> {
	await apiReorder(playlistId, entryId, newPosition);
	await refreshPlaylist(playlistId);
}

async function refreshPlaylist(playlistId: string): Promise<void> {
	const playlists = await fetchPlaylists();
	playlistList.set(playlists);
	if (get(selectedPlaylistId) === playlistId) {
		await loadPlaylistDetail(playlistId);
	}
}
