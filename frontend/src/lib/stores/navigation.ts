import { writable, derived, get } from 'svelte/store';
import {
	selectedSongId,
	selectedGenerationId,
	selectedAlbumId,
	selectSong as playerSelectSong,
	selectAlbum as playerSelectAlbum,
	selectGenerationInSidebar as playerSelectGeneration,
	clearGenerationSelection as playerClearGeneration,
	ensureGenerationsLoaded,
	songList
} from '$lib/stores/player';
import {
	deselectPlaylist as storeDeselectPlaylist,
	selectPlaylist as storeSelectPlaylist,
	selectedPlaylistId
} from '$lib/stores/playlists';
import { closeSidebar } from '$lib/stores/ui';
import type { GenerationItem, SongItem } from '$lib/api/types';
import type { LibrarySection } from '$lib/constants';
import {
	applyLibraryHistory,
	expandAlbum,
	isLibraryHistoryState,
	libraryBrowseStateFrom,
	libraryRootState,
	setLibrarySection,
	snapshotLibraryHistory,
	type LibraryHistoryState
} from '$lib/stores/libraryContext';

export type DetailTab = 'generations' | 'edit' | 'chat';

export const detailTab = writable<DetailTab>('generations');

let suppressPush = false;

function urlFromState(state: LibraryHistoryState): string {
	if (state.songId && state.generationId) return `/?song=${state.songId}&gen=${state.generationId}`;
	if (state.songId) return `/?song=${state.songId}`;
	return '/';
}

function currentHistoryIndex(): number {
	const state = history.state;
	return isLibraryHistoryState(state) ? state.index : 0;
}

function replaceLibraryHistory(): void {
	if (suppressPush) return;
	const next = snapshotLibraryHistory(currentHistoryIndex());
	history.replaceState(next, '', urlFromState(next));
}

function pushLibraryHistory(): void {
	if (suppressPush) return;
	const current = history.state;
	if (isLibraryHistoryState(current)) {
		const leaving = snapshotLibraryHistory(current.index);
		history.replaceState(
			{ ...current, scrollAnchor: leaving.scrollAnchor },
			'',
			urlFromState(current)
		);
	}
	const next = snapshotLibraryHistory(currentHistoryIndex() + 1);
	history.pushState(next, '', urlFromState(next));
}

export function selectLibrarySection(section: LibrarySection): void {
	setLibrarySection(section);
	replaceLibraryHistory();
}

export function persistLibraryHistory(): void {
	replaceLibraryHistory();
}

export function selectAlbumOverview(albumId: string): void {
	storeDeselectPlaylist();
	playerSelectAlbum(albumId);
	expandAlbum(albumId);
	closeSidebar();
	pushLibraryHistory();
}

export function deselectAlbum(): void {
	goBack();
}

export function backToAlbum(): void {
	goBack();
}

export function selectSong(songId: string): void {
	storeDeselectPlaylist();
	const song = get(songList).find((item) => item.id === songId);
	if (song) {
		selectedAlbumId.set(song.album_id);
		expandAlbum(song.album_id);
	}
	playerSelectSong(songId);
	ensureGenerationsLoaded(songId);
	detailTab.set('generations');
	closeSidebar();
	pushLibraryHistory();
}

export function selectPlaylistView(playlistId: string): void {
	playerSelectAlbum(null);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	storeSelectPlaylist(playlistId);
	closeSidebar();
	pushLibraryHistory();
}

export function deselectPlaylistView(): void {
	goBack();
}

export function deselectSong(): void {
	goBack();
}

export function selectGeneration(gen: GenerationItem, song: SongItem): void {
	playerSelectGeneration(gen, song);
	pushLibraryHistory();
}

export function backToSong(): void {
	goBack();
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

export function goBack(): void {
	const state = history.state;
	if (isLibraryHistoryState(state) && state.index > 0) {
		history.back();
		return;
	}
	const current = isLibraryHistoryState(state) ? state : snapshotLibraryHistory(0);
	suppressPush = true;
	applyLibraryHistory(libraryBrowseStateFrom(current));
	detailTab.set('generations');
	suppressPush = false;
	replaceLibraryHistory();
}

export function initNavigation(): () => void {
	const params = new URLSearchParams(window.location.search);
	const songId = params.get('song');
	const genId = params.get('gen');

	if (songId) {
		suppressPush = true;
		playerSelectSong(songId);
		ensureGenerationsLoaded(songId);
		if (genId) {
			selectedGenerationId.set(genId);
		}
		suppressPush = false;
	}

	replaceLibraryHistory();

	function onPopstate(e: PopStateEvent): void {
		suppressPush = true;
		if (isLibraryHistoryState(e.state)) {
			applyLibraryHistory(e.state);
			if (e.state.songId) {
				ensureGenerationsLoaded(e.state.songId);
			}
		} else {
			applyLibraryHistory(libraryRootState());
		}
		detailTab.set('generations');
		suppressPush = false;
	}

	window.addEventListener('popstate', onPopstate);
	return () => window.removeEventListener('popstate', onPopstate);
}

export function resetNavigationForTests(): void {
	suppressPush = false;
	detailTab.set('generations');
}

export const canGoBack = derived(
	[selectedSongId, selectedGenerationId, selectedAlbumId, selectedPlaylistId],
	([$songId, $genId, $albumId, $playlistId]) =>
		$songId !== null || $genId !== null || $albumId !== null || $playlistId !== null
);
