import { writable, derived, get } from 'svelte/store';
import { ApiError } from '$lib/api/fetch';
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
import type { AddAlbumToPlaylistResult, PlaylistDetailItem, PlaylistItem } from '$lib/api/types';
import { LIBRARY_PLAYLISTS_ERROR } from '$lib/constants';
import { openCollection, setOpenCollection } from '$lib/stores/collection';

export type PlaylistLoadStatus = 'idle' | 'loading' | 'ready' | 'error';

export interface PlaylistLoadState {
	status: PlaylistLoadStatus;
	error: string | null;
}

// A detail fetched within this window is reused instead of refetched on a
// LibraryWall remount or a quick back-and-forth (wall -> album -> back ->
// playlist) — the request-storm this guards against (#139).
const PLAYLIST_DETAIL_FRESH_MS = 15_000;

export const playlistList = writable<PlaylistItem[]>([]);
// The currently open playlist is a projection of the single navigation
// collection (see stores/collection.ts) — not an independently writable
// selection. Opening a playlist detail is the only writer, via
// loadPlaylistDetail below.
export const selectedPlaylistId = derived(openCollection, ($collection) =>
	$collection?.kind === 'playlist' ? $collection.id : null
);
export const selectedPlaylistDetail = writable<PlaylistDetailItem | null>(null);
export const playlistLoad = writable<PlaylistLoadState>({ status: 'idle', error: null });

export const selectedPlaylist = derived(
	[playlistList, selectedPlaylistId],
	([$list, $id]) => $list.find((p) => p.id === $id) ?? null
);

let playlistsInflight: Promise<boolean> | null = null;
let playlistDetailRequest = 0;

interface CachedPlaylistDetail {
	detail: PlaylistDetailItem;
	fetchedAt: number;
}

const playlistDetailCache = new Map<string, CachedPlaylistDetail>();
const playlistDetailInflight = new Map<string, Promise<PlaylistDetailItem>>();

function freshPlaylistDetail(id: string): PlaylistDetailItem | null {
	const cached = playlistDetailCache.get(id);
	if (!cached || Date.now() - cached.fetchedAt >= PLAYLIST_DETAIL_FRESH_MS) return null;
	return cached.detail;
}

function invalidatePlaylistDetailCache(id: string): void {
	playlistDetailCache.delete(id);
}

function fetchPlaylistDetailDeduped(id: string): Promise<PlaylistDetailItem> {
	const inflight = playlistDetailInflight.get(id);
	if (inflight) return inflight;
	const request = (async () => {
		const detail = await fetchPlaylist(id);
		playlistDetailCache.set(id, { detail, fetchedAt: Date.now() });
		return detail;
	})().finally(() => {
		playlistDetailInflight.delete(id);
	});
	playlistDetailInflight.set(id, request);
	return request;
}

export async function loadPlaylists(): Promise<boolean> {
	if (playlistsInflight) return playlistsInflight;
	playlistLoad.set({ status: 'loading', error: null });
	playlistsInflight = (async () => {
		try {
			const items = await fetchPlaylists();
			playlistList.update((current) => mergeFetchedPlaylists(items, current));
			playlistLoad.set({ status: 'ready', error: null });
			return true;
		} catch (err) {
			playlistLoad.set({ status: 'error', error: playlistErrorMessage(err) });
			return false;
		} finally {
			playlistsInflight = null;
		}
	})();
	return playlistsInflight;
}

export async function ensurePlaylistsLoaded(): Promise<boolean> {
	if (get(playlistLoad).status === 'ready') return true;
	return loadPlaylists();
}

export function resetPlaylistsForTests(): void {
	playlistsInflight = null;
	playlistList.set([]);
	setOpenCollection(null);
	selectedPlaylistDetail.set(null);
	playlistLoad.set({ status: 'idle', error: null });
	playlistDetailRequest += 1;
	playlistDetailCache.clear();
	playlistDetailInflight.clear();
}

function mergeFetchedPlaylists(server: PlaylistItem[], local: PlaylistItem[]): PlaylistItem[] {
	const serverIds = new Set(server.map((playlist) => playlist.id));
	const createdWhileLoading = local.filter((playlist) => !serverIds.has(playlist.id));
	return [...server, ...createdWhileLoading];
}

function playlistErrorMessage(err: unknown): string {
	if (err instanceof ApiError) return err.detail || err.message;
	if (err instanceof Error) return err.message;
	return LIBRARY_PLAYLISTS_ERROR;
}

export async function loadPlaylistDetail(
	id: string,
	options: { forceRefresh?: boolean } = {}
): Promise<void> {
	const request = ++playlistDetailRequest;
	setOpenCollection({ kind: 'playlist', id });
	if (options.forceRefresh) {
		invalidatePlaylistDetailCache(id);
	} else {
		const fresh = freshPlaylistDetail(id);
		if (fresh) {
			selectedPlaylistDetail.set(fresh);
			return;
		}
	}
	const detail = await fetchPlaylistDetailDeduped(id);
	if (request !== playlistDetailRequest || get(selectedPlaylistId) !== id) return;
	selectedPlaylistDetail.set(detail);
}

export function deselectPlaylist(): void {
	playlistDetailRequest += 1;
	if (get(openCollection)?.kind === 'playlist') {
		setOpenCollection(null);
	}
	selectedPlaylistDetail.set(null);
}

// Every local write to selectedPlaylistDetail must also refresh the detail
// cache, or a rename/unshare would appear reverted for up to
// PLAYLIST_DETAIL_FRESH_MS the next time the cache serves this id.
function cachePlaylistDetail(detail: PlaylistDetailItem): void {
	playlistDetailCache.set(detail.id, { detail, fetchedAt: Date.now() });
}

export function updatePlaylistInList(
	playlistId: string,
	updater: (p: PlaylistItem) => PlaylistItem
): void {
	playlistList.update((list) => list.map((p) => (p.id === playlistId ? updater(p) : p)));
	selectedPlaylistDetail.update((d) => {
		if (!d || d.id !== playlistId) return d;
		const updated = { ...d, ...updater(d) };
		cachePlaylistDetail(updated);
		return updated;
	});
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
		selectedPlaylistDetail.update((d) => {
			if (!d) return d;
			const next = { ...d, title };
			cachePlaylistDetail(next);
			return next;
		});
	}
}

export async function deletePlaylist(id: string): Promise<void> {
	await deletePlaylistApi(id);
	playlistList.update((list) => list.filter((p) => p.id !== id));
	invalidatePlaylistDetailCache(id);
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

export async function addAlbumToPlaylist(
	playlistId: string,
	albumId: string
): Promise<AddAlbumToPlaylistResult> {
	const result = await apiAddAlbum(playlistId, albumId);
	await refreshPlaylist(playlistId);
	return result;
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
		await loadPlaylistDetail(playlistId, { forceRefresh: true });
	} else {
		invalidatePlaylistDetailCache(playlistId);
	}
}
