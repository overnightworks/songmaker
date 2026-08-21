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
	albumList,
	songList
} from '$lib/stores/player';
import {
	deselectPlaylist as storeDeselectPlaylist,
	selectPlaylist as storeSelectPlaylist,
	selectedPlaylistId
} from '$lib/stores/playlists';
import { closeSidebar } from '$lib/stores/ui';
import type { AlbumItem, GenerationItem, SongItem } from '$lib/api/types';
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
	detailTab.set('generations');
	if (albumId) {
		playerSelectAlbum(albumId);
		setLibrarySurface('detail');
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
	}
	playerSelectSong(songId);
	ensureGenerationsLoaded(songId);
	detailTab.set('generations');
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
	const album: AlbumItem = {
		id: song.album_id,
		title: song.album_title,
		artist: song.artist,
		subtitle: '',
		year: '',
		colors: {},
		song_count: 0,
		is_shared: false,
		share_slug: null,
		created_at: song.created_at
	};
	albumList.update((list) => [...list, album]);
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
	setLibrarySurface('detail');
	pushLibraryHistory();
}

export function backToSong(): void {
	const state = history.state;
	if (isLibraryHistoryState(state) && state.index > 0) {
		history.back();
		return;
	}
	suppressPush = true;
	playerClearGeneration();
	detailTab.set('generations');
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
	detailTab.set('generations');
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
			detailTab.set('generations');
		})();
	}

	window.addEventListener('popstate', onPopstate);
	return () => window.removeEventListener('popstate', onPopstate);
}

export function resetNavigationForTests(): void {
	suppressPush = false;
	detailTab.set('generations');
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
