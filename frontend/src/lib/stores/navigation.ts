import { get, writable } from 'svelte/store';
import { goto } from '$app/navigation';
import { resolve } from '$app/paths';
import { fetchAlbum } from '$lib/api/albums';
import { handleSave, isDirty } from '$lib/stores/editor';
import { addToast } from '$lib/stores/toast';
import {
	selectedSongId,
	selectedGenerationId,
	selectedAlbumId,
	selectedSong,
	selectSong as playerSelectSong,
	selectGenerationInSidebar as playerSelectGeneration,
	clearGenerationSelection as playerClearGeneration,
	ensureGenerationsLoaded,
	loadSongsForAlbum,
	albumList,
	songList
} from '$lib/stores/player';
import {
	deselectPlaylist as storeDeselectPlaylist,
	loadPlaylistDetail
} from '$lib/stores/playlists';
import { openCollection, setOpenCollection, type OpenCollection } from '$lib/stores/collection';
import { closeSidebar } from '$lib/stores/ui';
import type { GenerationItem, SongItem } from '$lib/api/types';
import type { LibraryFilter } from '$lib/constants';
import {
	applyLibraryHistory,
	cancelLibraryHistoryApply,
	detailTab,
	isLibraryHistoryState,
	libraryHistoryUrl,
	librarySurface,
	libraryRootState,
	libraryWallStateFrom,
	setLibraryFilter,
	setLibrarySurface,
	snapshotLibraryHistory,
	type DetailTab,
	type LibraryHistoryState
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
				query: leaving.query,
				sort: leaving.sort,
				filter: leaving.filter
			},
			'',
			urlFromState(current)
		);
	}
	const next = snapshotLibraryHistory(currentHistoryIndex() + 1);
	history.pushState(next, '', urlFromState(next));
}

export function selectLibraryFilter(filter: LibraryFilter): void {
	const next = setLibraryFilter(filter);
	if (suppressPush) return;
	history.replaceState(next, '', urlFromState(next));
}

export function persistLibraryHistory(): void {
	replaceLibraryHistory();
}

export function isLibraryWorkspacePath(pathname: string): boolean {
	return pathname === '/';
}

// A dirty editor draft blocks a song switch or leave (rail row, prev/next,
// breadcrumb, Escape, Library) until the owner resolves it: the deferred
// navigation is parked here, and SongDetailView — the only surface where a
// draft can be dirty — renders the Save / Discard / Cancel confirm and
// either runs the parked action (Discard, or Save then run it) or drops it
// (Cancel).
export const pendingDirtyNavigation = writable<(() => void | Promise<void>) | null>(null);

// The single gatekeeper for every navigation that would drop the current
// editor draft: a dirty draft parks `action` in `pendingDirtyNavigation`
// instead of running it (see the comment above), a clean draft runs it
// immediately. Every song-switch/leave entry point must route through this
// — never re-implement the if/else inline.
async function guardDirtyNavigation(action: () => void | Promise<void>): Promise<void> {
	if (get(isDirty)) {
		pendingDirtyNavigation.set(action);
		return;
	}
	await action();
}

// The rail context (and every other "song open" entry point — search hits,
// ?song= deep links, history restore) never leaves the rail empty: whenever
// the selected song's album is not the open collection, the collection
// follows the song. Opening a collection explicitly (openAlbum/openPlaylist)
// is unaffected — this only reacts to a *song* becoming current.
function ensureCollectionMatchesSong(song: SongItem): void {
	const current = get(openCollection);
	if (current?.kind === 'album' && current.id === song.album_id) return;
	setOpenCollection({ kind: 'album', id: song.album_id });
}

selectedSong.subscribe((song) => {
	if (!song) return;
	ensureCollectionMatchesSong(song);
});

export function openAlbum(albumId: string): void {
	storeDeselectPlaylist();
	setOpenCollection({ kind: 'album', id: albumId });
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	void loadSongsForAlbum(albumId);
	setLibrarySurface('detail');
	closeSidebar();
	pushLibraryHistory();
}

export function openPlaylist(playlistId: string): void {
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	void loadPlaylistDetail(playlistId);
	setLibrarySurface('detail');
	closeSidebar();
	pushLibraryHistory();
}

// The rail context's header and the collection crumb in a song's breadcrumb
// share this: a song open inside the collection means "back to the
// collection"; otherwise the collection is already the destination, so
// re-opening it is a no-op that still refreshes its history entry.
export function openCollectionEntry(collection: OpenCollection): void {
	if (get(selectedSongId) !== null) {
		backToCollection();
		return;
	}
	if (collection.kind === 'album') openAlbum(collection.id);
	else openPlaylist(collection.id);
}

export function backToCollection(): void {
	guardDirtyNavigation(() => {
		suppressPush = true;
		selectedSongId.set(null);
		selectedGenerationId.set(null);
		openTakesTab();
		setLibrarySurface(get(openCollection) ? 'detail' : 'browse');
		suppressPush = false;
		replaceLibraryHistory();
	});
}

export function openLibraryCreate(): void {
	setLibrarySurface('create');
	closeSidebar();
	pushLibraryHistory();
}

// The rail's "Library" link: leaves the open song (if any) but keeps the
// open collection in the rail context (GitLab-style — the context persists
// until another collection replaces it), and always pushes a fresh history
// entry so the browser back button returns to whatever was open before.
export async function openLibraryWall(): Promise<void> {
	await guardDirtyNavigation(async () => {
		if (!isLibraryWorkspacePath(window.location.pathname)) {
			await goto(resolve('/'));
		}
		selectedSongId.set(null);
		selectedGenerationId.set(null);
		setLibrarySurface('browse');
		closeSidebar();
		pushLibraryHistory();
	});
}

export interface AlbumTrackNeighbors {
	previous: SongItem | null;
	next: SongItem | null;
}

export function compareAlbumTracks(a: SongItem, b: SongItem): number {
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
	if (tab === 'takes') openTakesTab();
	setLibrarySurface('detail');
	closeSidebar();
	if (historyMode === 'replace') {
		replaceLibraryHistory();
		return;
	}
	pushLibraryHistory();
}

// Opening a song from the album interior (no song selected yet) always
// pushes — it changes the visible surface from the track list to the song
// editor. Once a song is open, moving to another song already inside the
// same open collection (list clicks, previous/next) replaces the current
// history entry, like selectNeighborSong. Selecting a song outside the open
// collection (search hit, deep link, a different collection) pushes, since
// it changes the rail context.
function selectSongHistoryMode(
	songId: string,
	knownSong: SongItem | undefined
): 'stack' | 'replace' {
	if (get(selectedSongId) === null) return 'stack';
	const collection = get(openCollection);
	if (collection?.kind !== 'album') return 'stack';
	const song = get(songList).find((item) => item.id === songId) ?? knownSong;
	return song?.album_id === collection.id ? 'replace' : 'stack';
}

export function selectSong(songId: string, knownSong?: SongItem): void {
	guardDirtyNavigation(() =>
		applySelectedSong(songId, knownSong, selectSongHistoryMode(songId, knownSong), 'takes')
	);
}

export function selectNeighborSong(song: SongItem): void {
	guardDirtyNavigation(() => applySelectedSong(song.id, song, 'replace', 'keep'));
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

export function deselectSong(): void {
	goBack();
}

export function selectGeneration(gen: GenerationItem, song: SongItem): void {
	playerSelectGeneration(gen, song);
	openTakesTab();
	setLibrarySurface('detail');
	replaceLibraryHistory();
}

export function backToSong(): void {
	suppressPush = true;
	playerClearGeneration();
	openTakesTab();
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

export function openWriteTab(): void {
	detailTab.set('write');
}

export function openTakesTab(): void {
	detailTab.set('takes');
}

export async function revealPlayingSong(song: SongItem, generationId: string): Promise<void> {
	if (!isLibraryWorkspacePath(window.location.pathname)) {
		await goto(resolve('/'));
	}
	await guardDirtyNavigation(() => {
		applySelectedSong(song.id, song, 'stack', 'takes');
		selectedGenerationId.set(generationId);
		persistLibraryHistory();
	});
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
	const state = history.state;
	if (isLibraryHistoryState(state) && state.index > 0) {
		history.back();
		return;
	}
	const current = isLibraryHistoryState(state) ? state : snapshotLibraryHistory(0);
	suppressPush = true;
	void applyLibraryHistory(libraryWallStateFrom(current));
	openTakesTab();
	setLibrarySurface('browse');
	suppressPush = false;
	replaceLibraryHistory();
}

// Browser Back/Forward has already committed the history change by the time
// `popstate` fires — there is no pending entry left to park a cancellable
// navigation into, unlike every other guarded path (see
// `pendingDirtyNavigation` above). A dirty draft is saved instead; a failed
// save surfaces a toast but never blocks the already-committed navigation.
// Documented next to the dirty-guard paragraph in docs/architecture.md.
async function saveDirtyDraftBeforePopstate(): Promise<void> {
	const songId = get(selectedSongId);
	if (!get(isDirty) || !songId) return;
	try {
		await handleSave(songId);
	} catch (e) {
		addToast(e instanceof Error ? e.message : 'Save failed', 'error');
	}
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
				openTakesTab();
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
			await saveDirtyDraftBeforePopstate();
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
	pendingDirtyNavigation.set(null);
	openTakesTab();
}
