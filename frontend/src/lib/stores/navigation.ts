import { derived, get } from 'svelte/store';
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
import {
	LIBRARY_BROWSE_WORKSPACE_AREAS,
	LIBRARY_DETAIL_WORKSPACE_AREAS,
	LIBRARY_KEEP_BROWSE_CLASS,
	LIBRARY_SONG_WORKSPACE_AREAS,
	type LibrarySection
} from '$lib/constants';
import {
	applyLibraryHistory,
	cancelLibraryHistoryApply,
	detailTab,
	expandAlbum,
	isLibraryHistoryState,
	libraryBrowseStateFrom,
	libraryHistoryUrl,
	libraryRootState,
	librarySection,
	librarySurface,
	setLibrarySection,
	setLibrarySurface,
	snapshotLibraryHistory,
	type DetailTab,
	type LibraryHistoryState,
	type LibrarySurface
} from '$lib/stores/libraryContext';

export type { DetailTab };
export { detailTab };

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
	const next = setLibrarySection(section);
	if (suppressPush) return;
	history.replaceState(next, '', urlFromState(next));
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

export function libraryKeepsBrowseColumn(input: {
	surface: LibrarySurface;
	section: LibrarySection;
	songSelected: boolean;
	sharesOpen: boolean;
}): boolean {
	return (
		input.surface === 'detail' &&
		input.section === 'albums' &&
		input.songSelected &&
		!input.sharesOpen
	);
}

export function libraryWorkspaceGrid(input: { hasDetail: boolean; keepBrowse: boolean }): {
	className: string;
	areas: string;
} {
	if (input.hasDetail && input.keepBrowse) {
		return { className: LIBRARY_KEEP_BROWSE_CLASS, areas: LIBRARY_SONG_WORKSPACE_AREAS };
	}
	if (input.hasDetail) {
		return { className: '', areas: LIBRARY_DETAIL_WORKSPACE_AREAS };
	}
	return { className: '', areas: LIBRARY_BROWSE_WORKSPACE_AREAS };
}

export interface AlbumTrackNeighbors {
	previous: SongItem | null;
	next: SongItem | null;
}

function compareAlbumTracks(a: SongItem, b: SongItem): number {
	if (a.track_number !== b.track_number) return a.track_number - b.track_number;
	return a.id.localeCompare(b.id);
}

export function albumTrackNeighbors(
	songId: string,
	songs: SongItem[] = get(songList)
): AlbumTrackNeighbors {
	const current = songs.find((item) => item.id === songId);
	if (!current) return { previous: null, next: null };
	const tracks = songs
		.filter((item) => item.album_id === current.album_id)
		.slice()
		.sort(compareAlbumTracks);
	const index = tracks.findIndex((item) => item.id === songId);
	if (index < 0) return { previous: null, next: null };
	return {
		previous: index > 0 ? tracks[index - 1] : null,
		next: index < tracks.length - 1 ? tracks[index + 1] : null
	};
}

function applySelectedSong(
	songId: string,
	knownSong: SongItem | undefined,
	historyMode: 'stack' | 'replace',
	tab: 'keep' | 'takes'
): void {
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
	if (tab === 'takes') openTakesSurface();
	setLibrarySurface('detail');
	closeSidebar();
	if (historyMode === 'replace') {
		replaceLibraryHistory();
		return;
	}
	pushLibraryHistory();
}

function selectedSongHistoryMode(): 'stack' | 'replace' {
	return get(librarySurface) === 'detail' && get(selectedSongId) !== null ? 'replace' : 'stack';
}

export function selectSong(songId: string, knownSong?: SongItem): void {
	const historyMode = selectedSongHistoryMode();
	applySelectedSong(songId, knownSong, historyMode, historyMode === 'replace' ? 'keep' : 'takes');
}

export function selectNeighborSong(song: SongItem): void {
	applySelectedSong(song.id, song, 'replace', 'keep');
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
	applySelectedSong(song.id, song, selectedSongHistoryMode(), 'takes');
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
	if (get(librarySurface) === 'browse' && browseSelectionFitsActiveMode()) {
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
	[
		selectedSongId,
		selectedGenerationId,
		selectedAlbumId,
		selectedPlaylistId,
		librarySurface,
		librarySection
	],
	([$songId, $genId, $albumId, $playlistId, $surface, $section]) => {
		if ($surface === 'create') return true;
		if ($section === 'playlists') return $playlistId !== null || $surface === 'detail';
		return $songId !== null || $genId !== null || $albumId !== null || $surface === 'detail';
	}
);

function browseSelectionFitsActiveMode(): boolean {
	if (get(librarySection) === 'playlists') {
		return get(selectedPlaylistId) !== null;
	}
	return (
		get(selectedAlbumId) !== null ||
		get(selectedSongId) !== null ||
		get(selectedGenerationId) !== null
	);
}
