import { get, writable } from 'svelte/store';
import { goto } from '$app/navigation';
import { resolve } from '$app/paths';
import { fetchAlbum } from '$lib/api/albums';
import { isNotFound } from '$lib/api/fetch';
import { handleSave, isDirty } from '$lib/stores/editor';
import { hydrateGenerationFailure } from '$lib/stores/jobs';
import { addToast } from '$lib/stores/toast';
import { albumList, loadSongsForAlbum, songList } from '$lib/stores/libraryData';
import {
	selectedSongId,
	selectedGenerationId,
	selectedAlbumId,
	selectedSong,
	selectSong as playerSelectSong,
	clearGenerationSelection as playerClearGeneration,
	ensureGenerationsLoaded
} from '$lib/stores/player';
import {
	deselectPlaylist as storeDeselectPlaylist,
	ensurePlaylistsLoaded,
	loadPlaylistDetail
} from '$lib/stores/playlists';
import { openCollection, setOpenCollection, type OpenCollection } from '$lib/stores/collection';
import { closeSidebar } from '$lib/stores/ui';
import type { SongItem } from '$lib/api/types';
import { SONG_LINK_NOT_FOUND_TOAST, type LibraryFilter } from '$lib/constants';
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

// Every entry point that opens a collection or a song onto the library
// workspace (openLibraryWall, openAlbum, openPlaylist, revealPlayingSong)
// needs this precondition first: the browser may be sitting on an unrelated
// route (e.g. Settings), and mutating the library stores without also
// switching the route leaves the change invisible behind whatever layout is
// still mounted (issue #264). Route through this instead of re-testing
// isLibraryWorkspacePath at each call site — a copy is exactly what got two
// of the four entry points forgotten in the first place.
async function ensureLibraryWorkspaceRoute(): Promise<void> {
	if (!isLibraryWorkspacePath(window.location.pathname)) {
		await goto(resolve('/'));
	}
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

export async function openAlbum(albumId: string): Promise<void> {
	await ensureLibraryWorkspaceRoute();
	storeDeselectPlaylist();
	setOpenCollection({ kind: 'album', id: albumId });
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	void loadSongsForAlbum(albumId);
	setLibrarySurface('detail');
	closeSidebar();
	pushLibraryHistory();
}

export async function openPlaylist(playlistId: string): Promise<void> {
	await ensureLibraryWorkspaceRoute();
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	void loadPlaylistDetail(playlistId);
	// A playlist can be opened before playlistList is populated (Shares
	// inventory, a deep link, mobile without the Rail mounted) --
	// PlaylistDetailView falls back to the detail fetch for its header
	// meanwhile, but this backfills the canonical list-backed entry too.
	void ensurePlaylistsLoaded();
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
	if (collection.kind === 'album') void openAlbum(collection.id);
	else void openPlaylist(collection.id);
}

export function backToCollection(): void {
	void guardDirtyNavigation(() => {
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
		await ensureLibraryWorkspaceRoute();
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

// This module's single "a song is now open" hook, used by its four entry
// points: applySelectedSong (selectSong, selectNeighborSong,
// revealPlayingSong), the ?song= deep link and history-restore branches of
// initNavigation, and onPopstate. Loads the song's takes and, alongside
// that, recovers its failure banner from the last failed generate job so a
// reload or a later visit shows the same cause a live SSE stream would have
// (see hydrateGenerationFailure). A new entry point added to this module
// should route through this instead of calling ensureGenerationsLoaded
// directly; it does not cover song selection elsewhere (e.g. player.ts's
// own playback-driven selectSong).
//
// A dead songId (deleted between the link being shared/saved and it being
// opened, issue #237) is a permanent, expected condition, not a transient
// failure: it is handled here, once, for every entry point, instead of each
// caller (none of which await this) leaking an unhandled rejection. Any
// other failure (network, 5xx) is not this function's to swallow and
// propagates to the caller.
export async function loadSongContext(songId: string): Promise<void> {
	void hydrateGenerationFailure(songId);
	try {
		await ensureGenerationsLoaded(songId);
	} catch (err) {
		if (!isNotFound(err)) throw err;
		reportSongLinkNotFound(songId);
	}
}

// Only clears the selection if it still names the dead song: a caller may
// have already navigated elsewhere while the fetch was in flight, and that
// newer selection must win over this late 404.
function reportSongLinkNotFound(songId: string): void {
	if (get(selectedSongId) !== songId) return;
	suppressPush = true;
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	setLibrarySurface(get(openCollection) ? 'detail' : 'browse');
	suppressPush = false;
	replaceLibraryHistory();
	addToast(SONG_LINK_NOT_FOUND_TOAST, 'error');
}

function applySelectedSong(
	songId: string,
	knownSong: SongItem | undefined,
	historyMode: 'stack' | 'replace',
	tab: 'keep' | 'write'
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
	loadSongContext(songId);
	if (tab === 'write') openWriteTab();
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

// Returns a promise instead of firing void: a caller that sets follow-up
// state after the selected song is current (e.g. LibraryWall's shared-take
// open, which needs the song in place before it can pin the generation) must
// await this. Most callers are fire-and-forget rail/list clicks and simply
// don't await it, which is fine for them.
export function selectSong(songId: string, knownSong?: SongItem): Promise<void> {
	// Evaluated before the guard's await: it reads selectedSongId/openCollection
	// as they stand right now, not after ensureLibraryWorkspaceRoute has (maybe)
	// already let applySelectedSong change them.
	const historyMode = selectSongHistoryMode(songId, knownSong);
	return guardDirtyNavigation(async () => {
		await ensureLibraryWorkspaceRoute();
		applySelectedSong(songId, knownSong, historyMode, 'write');
	});
}

export function selectNeighborSong(song: SongItem): Promise<void> {
	return guardDirtyNavigation(async () => {
		await ensureLibraryWorkspaceRoute();
		applySelectedSong(song.id, song, 'replace', 'keep');
	});
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
	await ensureLibraryWorkspaceRoute();
	await guardDirtyNavigation(() => {
		applySelectedSong(song.id, song, 'stack', 'write');
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
//
// `savingDraft` memoises the in-flight save: two popstates firing before the
// first save settles (e.g. rapid Back/Back) await the same promise instead
// of each POSTing the draft.
let savingDraft: Promise<void> | null = null;

async function saveDraft(songId: string): Promise<void> {
	try {
		await handleSave(songId);
	} catch (e) {
		addToast(e instanceof Error ? e.message : 'Save failed', 'error');
	}
}

async function saveDirtyDraftBeforePopstate(): Promise<void> {
	if (savingDraft) {
		await savingDraft;
		return;
	}
	const songId = get(selectedSongId);
	if (!get(isDirty) || !songId) return;
	savingDraft = saveDraft(songId).finally(() => {
		savingDraft = null;
	});
	await savingDraft;
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
			loadSongContext(songId);
			if (genId) {
				selectedGenerationId.set(genId);
				openTakesTab();
			}
			setLibrarySurface('detail');
			suppressPush = false;
		}

		replaceLibraryHistory();
	} else if (existing.songId) {
		loadSongContext(existing.songId);
	}

	function onPopstate(e: PopStateEvent): void {
		const state = e.state;
		void (async () => {
			await saveDirtyDraftBeforePopstate();
			if (isLibraryHistoryState(state)) {
				const applied = await applyLibraryHistory(state);
				if (applied && state.songId) {
					await loadSongContext(state.songId);
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
