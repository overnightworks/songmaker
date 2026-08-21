import { writable, derived, get } from 'svelte/store';
import { goto } from '$app/navigation';
import { resolve } from '$app/paths';
import { fetchAlbum } from '$lib/api/albums';
import {
	selectedSongId,
	selectedGenerationId,
	selectedAlbumId,
	selectSong as playerSelectSong,
	selectAlbum as playerSelectAlbum,
	selectGenerationInSidebar as playerSelectGeneration,
	clearGenerationSelection as playerClearGeneration,
	ensureGenerationsLoaded,
	loadSongsForAlbum,
	albumList,
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
	cancelLibraryHistoryApply,
	expandAlbum,
	hasLibrarySelection,
	isLibraryHistoryState,
	libraryBrowseStateFrom,
	libraryHistoryUrl,
	libraryRootState,
	librarySurface,
	setLibrarySection,
	setLibrarySurface,
	snapshotLibraryHistory,
	type LibraryHistoryState
} from '$lib/stores/libraryContext';

export type DetailTab = 'generations' | 'edit' | 'chat';

export const detailTab = writable<DetailTab>('generations');

let suppressPush = false;

function urlFromState(state: LibraryHistoryState): string {
	return libraryHistoryUrl(state);
}

function currentHistoryIndex(): number {
	const state = history.state;
	return isLibraryHistoryState(state) ? state.index : 0;
}

function replaceLibraryHistory(): void {
	if (suppressPush) return;
	cancelLibraryHistoryApply();
	const next = snapshotLibraryHistory(currentHistoryIndex());
	history.replaceState(next, '', urlFromState(next));
}

function pushLibraryHistory(): void {
	if (suppressPush) return;
	cancelLibraryHistoryApply();
	const current = history.state;
	if (isLibraryHistoryState(current)) {
		const leaving = snapshotLibraryHistory(current.index);
		history.replaceState(
			{
				...current,
				scrollAnchor: leaving.scrollAnchor,
				albumOffset: leaving.albumOffset,
				songOffset: leaving.songOffset,
				searchCursor: leaving.searchCursor,
				searchLoadedCount: leaving.searchLoadedCount,
				expandedAlbumIds: leaving.expandedAlbumIds,
				query: leaving.query,
				sort: leaving.sort,
				section: leaving.section
			},
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

export function isLibraryWorkspacePath(pathname: string): boolean {
	return pathname === '/';
}

export function selectAlbumOverview(albumId: string): void {
	storeDeselectPlaylist();
	playerSelectAlbum(albumId);
	expandAlbum(albumId);
	setLibrarySurface('detail');
	closeSidebar();
	pushLibraryHistory();
}

export function deselectAlbum(): void {
	goBack();
}

export function backToAlbum(): void {
	const songId = get(selectedSongId);
	const song = songId ? get(songList).find((item) => item.id === songId) : undefined;
	const albumId = get(selectedAlbumId) ?? song?.album_id ?? null;
	suppressPush = true;
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	openTakesSurface();
	if (albumId) {
		playerSelectAlbum(albumId);
		setLibrarySurface('detail');
		void loadSongsForAlbum(albumId);
	} else {
		setLibrarySurface('browse');
	}
	suppressPush = false;
	replaceLibraryHistory();
}

export function openLibraryCreate(): void {
	setLibrarySurface('create');
	pushLibraryHistory();
}

export function selectSong(songId: string, knownSong?: SongItem): void {
	storeDeselectPlaylist();
	if (knownSong) hydrateSongIntoLibrary(knownSong);
	const song = get(songList).find((item) => item.id === songId) ?? knownSong;
	const albumId = song?.album_id ?? null;
	if (albumId) {
		selectedAlbumId.set(albumId);
		void loadSongsForAlbum(albumId);
	}
	playerSelectSong(songId);
	ensureGenerationsLoaded(songId);
	openTakesSurface();
	setLibrarySurface('detail');
	closeSidebar();
	const current = history.state;
	if (
		isLibraryHistoryState(current) &&
		albumId !== null &&
		current.albumId === albumId &&
		current.songId === null
	) {
		replaceLibraryHistory();
		return;
	}
	pushLibraryHistory();
}

function hydrateSongIntoLibrary(song: SongItem): void {
	if (!get(songList).some((item) => item.id === song.id)) {
		songList.update((list) => [...list, song]);
	}
	if (get(albumList).some((item) => item.id === song.album_id)) return;
	void fetchAlbum(song.album_id)
		.then((album) => {
			albumList.update((list) =>
				list.some((item) => item.id === album.id) ? list : [...list, album]
			);
		})
		.catch(() => undefined);
}

export function selectPlaylistView(playlistId: string): void {
	playerSelectAlbum(null);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	storeSelectPlaylist(playlistId);
	setLibrarySurface('detail');
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
	openTakesSurface();
	setLibrarySurface('detail');
	replaceLibraryHistory();
}

export function backToSong(): void {
	suppressPush = true;
	playerClearGeneration();
	openTakesSurface();
	setLibrarySurface('detail');
	suppressPush = false;
	replaceLibraryHistory();
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

export function openRecipeSurface(): void {
	detailTab.set('edit');
}

export function openTakesSurface(): void {
	detailTab.set('generations');
}

export async function revealPlayingSong(song: SongItem, generationId: string): Promise<void> {
	if (!isLibraryWorkspacePath(window.location.pathname)) {
		await goto(resolve('/'));
	}
	selectSong(song.id, song);
	selectedGenerationId.set(generationId);
	persistLibraryHistory();
}

export function goBack(): void {
	if (get(librarySurface) === 'create') {
		const createState = history.state;
		if (isLibraryHistoryState(createState) && createState.index > 0) {
			history.back();
			return;
		}
		setLibrarySurface('browse');
		replaceLibraryHistory();
		return;
	}
	if (get(librarySurface) === 'browse' && hasLibrarySelection()) {
		setLibrarySurface('detail');
		replaceLibraryHistory();
		return;
	}
	const state = history.state;
	if (isLibraryHistoryState(state) && state.index > 0) {
		history.back();
		return;
	}
	const current = isLibraryHistoryState(state) ? state : snapshotLibraryHistory(0);
	suppressPush = true;
	void applyLibraryHistory(libraryBrowseStateFrom(current));
	openTakesSurface();
	setLibrarySurface('browse');
	suppressPush = false;
	replaceLibraryHistory();
}

export function initNavigation(): () => void {
	const existing = history.state;
	if (!isLibraryHistoryState(existing)) {
		const params = new URLSearchParams(window.location.search);
		const songId = params.get('song');
		const genId = params.get('gen');

		if (songId) {
			suppressPush = true;
			playerSelectSong(songId);
			ensureGenerationsLoaded(songId);
			if (genId) {
				selectedGenerationId.set(genId);
				openTakesSurface();
			}
			setLibrarySurface('detail');
			suppressPush = false;
		}

		replaceLibraryHistory();
	} else if (existing.songId) {
		ensureGenerationsLoaded(existing.songId);
	}

	function onPopstate(e: PopStateEvent): void {
		const state = e.state;
		void (async () => {
			if (isLibraryHistoryState(state)) {
				const applied = await applyLibraryHistory(state);
				if (applied && state.songId) {
					await ensureGenerationsLoaded(state.songId);
				}
			} else {
				await applyLibraryHistory(libraryRootState());
			}
			openTakesSurface();
		})();
	}

	window.addEventListener('popstate', onPopstate);
	return () => window.removeEventListener('popstate', onPopstate);
}

export function resetNavigationForTests(): void {
	suppressPush = false;
	openTakesSurface();
}

export const canGoBack = derived(
	[selectedSongId, selectedGenerationId, selectedAlbumId, selectedPlaylistId, librarySurface],
	([$songId, $genId, $albumId, $playlistId, $surface]) =>
		$surface === 'create' ||
		$songId !== null ||
		$genId !== null ||
		$albumId !== null ||
		$playlistId !== null
);
