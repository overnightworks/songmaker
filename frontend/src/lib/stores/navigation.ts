import { writable, derived } from 'svelte/store';
import {
	selectedSongId,
	selectedGenerationId,
	selectSong as playerSelectSong,
	selectAlbum as playerSelectAlbum,
	selectGenerationInSidebar as playerSelectGeneration,
	clearGenerationSelection as playerClearGeneration,
	ensureGenerationsLoaded
} from '$lib/stores/player';
import {
	deselectPlaylist as storeDeselectPlaylist,
	selectPlaylist as storeSelectPlaylist
} from '$lib/stores/playlists';
import { closeSidebar } from '$lib/stores/ui';
import type { GenerationItem, SongItem } from '$lib/api/types';

export type DetailTab = 'generations' | 'edit' | 'chat';

export const detailTab = writable<DetailTab>('generations');

let suppressPush = false;

function buildUrl(songId: string | null, genId: string | null): string {
	if (songId && genId) return `/?song=${songId}&gen=${genId}`;
	if (songId) return `/?song=${songId}`;
	return '/';
}

function pushUrl(songId: string | null, genId: string | null = null): void {
	if (suppressPush) return;
	const url = buildUrl(songId, genId);
	history.pushState({ songId, genId }, '', url);
}

function replaceUrl(songId: string | null, genId: string | null = null): void {
	const url = buildUrl(songId, genId);
	history.replaceState({ songId, genId }, '', url);
}

export function selectAlbumOverview(albumId: string): void {
	storeDeselectPlaylist();
	playerSelectAlbum(albumId);
	closeSidebar();
}

export function deselectAlbum(): void {
	playerSelectAlbum(null);
}

export function backToAlbum(): void {
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	pushUrl(null);
}

export function selectSong(songId: string): void {
	storeDeselectPlaylist();
	playerSelectSong(songId);
	ensureGenerationsLoaded(songId);
	detailTab.set('generations');
	closeSidebar();
	pushUrl(songId);
}

export function selectPlaylistView(playlistId: string): void {
	playerSelectAlbum(null);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	storeSelectPlaylist(playlistId);
	closeSidebar();
}

export function deselectPlaylistView(): void {
	storeDeselectPlaylist();
}

export function deselectSong(): void {
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	detailTab.set('generations');
	pushUrl(null);
}

export function selectGeneration(gen: GenerationItem, song: SongItem): void {
	playerSelectGeneration(gen, song);
	pushUrl(song.id, gen.id);
}

export function backToSong(): void {
	const songId = playerGetSongId();
	playerClearGeneration();
	if (songId) {
		pushUrl(songId);
	}
}

export function clearGenerationSelection(): void {
	playerClearGeneration();
}

export function navigateToSongTab(tab: DetailTab): void {
	playerClearGeneration();
	detailTab.set(tab);
}

export function switchTab(tab: DetailTab): void {
	detailTab.set(tab);
}

function playerGetSongId(): string | null {
	let id: string | null = null;
	const unsub = selectedSongId.subscribe((v) => (id = v));
	unsub();
	return id;
}

export function initNavigation(): () => void {
	const params = new URLSearchParams(window.location.search);
	const songId = params.get('song');
	const genId = params.get('gen');

	replaceUrl(songId, genId);

	if (songId) {
		suppressPush = true;
		playerSelectSong(songId);
		ensureGenerationsLoaded(songId);
		if (genId) {
			selectedGenerationId.set(genId);
		}
		suppressPush = false;
	}

	function onPopstate(e: PopStateEvent): void {
		suppressPush = true;
		const state = (e.state as { songId: string | null; genId: string | null } | null) ?? {
			songId: null,
			genId: null
		};
		if (state.songId) {
			playerSelectSong(state.songId);
			ensureGenerationsLoaded(state.songId);
			if (state.genId) {
				selectedGenerationId.set(state.genId);
			} else {
				selectedGenerationId.set(null);
			}
		} else {
			selectedSongId.set(null);
			selectedGenerationId.set(null);
		}
		detailTab.set('generations');
		suppressPush = false;
	}

	window.addEventListener('popstate', onPopstate);
	return () => window.removeEventListener('popstate', onPopstate);
}

export const canGoBack = derived(selectedSongId, ($songId) => $songId !== null);
