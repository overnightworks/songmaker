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
import { closeSidebar } from '$lib/stores/ui';
import type { GenerationItem, SongItem } from '$lib/api/types';

export type DetailTab = 'generations' | 'edit' | 'chat';

export const detailTab = writable<DetailTab>('generations');

let suppressPush = false;

function pushSongUrl(songId: string | null): void {
	if (suppressPush) return;
	const url = songId ? `/?song=${songId}` : '/';
	history.pushState({ songId }, '', url);
}

function replaceSongUrl(songId: string | null): void {
	const url = songId ? `/?song=${songId}` : '/';
	history.replaceState({ songId }, '', url);
}

export function selectAlbumOverview(albumId: string): void {
	playerSelectAlbum(albumId);
	closeSidebar();
}

export function backToAlbum(): void {
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	pushSongUrl(null);
}

export function selectSong(songId: string): void {
	playerSelectSong(songId);
	ensureGenerationsLoaded(songId);
	detailTab.set('generations');
	closeSidebar();
	pushSongUrl(songId);
}

export function deselectSong(): void {
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	detailTab.set('generations');
	pushSongUrl(null);
}

export function selectGeneration(gen: GenerationItem, song: SongItem): void {
	playerSelectGeneration(gen, song);
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

export function initNavigation(): () => void {
	const params = new URLSearchParams(window.location.search);
	const songId = params.get('song');

	replaceSongUrl(songId);

	if (songId) {
		suppressPush = true;
		playerSelectSong(songId);
		ensureGenerationsLoaded(songId);
		suppressPush = false;
	}

	function onPopstate(e: PopStateEvent): void {
		suppressPush = true;
		const state = (e.state as { songId: string | null } | null) ?? { songId: null };
		if (state.songId) {
			playerSelectSong(state.songId);
			ensureGenerationsLoaded(state.songId);
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
