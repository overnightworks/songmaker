import { goto } from '$app/navigation';
import { resolve } from '$app/paths';
import { get, writable } from 'svelte/store';
import {
	dropLayersFrom,
	keepLayerHistory,
	layerSwitch,
	resetLayersForTests,
	stackedLayers,
	type Layer,
	type LayerHistory
} from '$lib/stores/layers';
import { fetchAlbum } from '$lib/api/albums';
import { describeFailure, isNotFound } from '$lib/api/fetch';
import { handleSave, isDirty } from '$lib/stores/editor';
import { hydrateActiveGeneration, hydrateGenerationFailure } from '$lib/stores/jobs';
import { addToast } from '$lib/stores/toast';
import { albumList, loadSongsForAlbum, songList } from '$lib/stores/libraryData';
import {
	selectedSongId,
	selectedGenerationId,
	selectedAlbumId,
	selectedSong,
	selectSong as playerSelectSong,
	clearGenerationSelection as playerClearGeneration,
	ensureGenerationsLoaded,
	escapeNowPlaying,
	nowPlayingFullChosen
} from '$lib/stores/player';
import {
	deselectPlaylist as storeDeselectPlaylist,
	ensurePlaylistsLoaded,
	loadPlaylistDetail,
	selectedPlaylist
} from '$lib/stores/playlists';
import { openCollection, setOpenCollection, type OpenCollection } from '$lib/stores/collection';
import { closeSidebar, sidebarOpen } from '$lib/stores/ui';
import type { PlaylistItem, SongItem } from '$lib/api/types';
import type { RailSearchTarget } from '$lib/stores/railSearch';
import {
	API_ERROR_GENERIC_MESSAGE,
	EDITOR_SAVE_FAILED,
	SONG_LINK_NOT_FOUND_TOAST
} from '$lib/constants';
import { isAlbumRoutePath, isPlaylistRoutePath, isSongRoutePath } from '$lib/routes/addresses';
import {
	applyLibraryHistory,
	backLibraryHistory,
	cancelLibraryHistoryApply,
	currentLibraryHistoryState,
	detailTab,
	holdLibraryRestoresUntil,
	isLibraryHistoryState,
	libraryHistoryEntry,
	libraryHistoryStepsLanded,
	libraryHistoryUrl,
	libraryRootState,
	libraryWallStateFrom,
	rememberedSongTab,
	setLibrarySurface,
	showSongTab,
	snapshotLibraryHistory,
	writeLibraryHistory,
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
	const state = currentLibraryHistoryState();
	return isLibraryHistoryState(state) ? state.index : 0;
}

// Every history write in this module goes through writeLibraryHistory, which
// owns the choice between shallow routing and a navigation; see the note on
// it in libraryContext.ts. The promise matters only to a caller that writes
// again straight afterwards -- a crossing write is asynchronous.
function replaceLibraryHistory(): Promise<void> {
	if (suppressPush) return Promise.resolve();
	cancelLibraryHistoryApply();
	const next = snapshotLibraryHistory(currentHistoryIndex());
	return writeLibraryHistory(next, urlFromState(next), 'replace');
}

function pushLibraryHistory(): Promise<void> {
	if (suppressPush) return Promise.resolve();
	cancelLibraryHistoryApply();
	const current = currentLibraryHistoryState();
	if (isLibraryHistoryState(current)) {
		const leaving = snapshotLibraryHistory(current.index);
		void writeLibraryHistory(
			{
				...current,
				scrollAnchor: leaving.scrollAnchor,
				albumOffset: leaving.albumOffset,
				songOffset: leaving.songOffset,
				searchCursor: leaving.searchCursor,
				searchLoadedCount: leaving.searchLoadedCount,
				query: leaving.query,
				sort: leaving.sort
			},
			urlFromState(current),
			'replace'
		);
	}
	const next = snapshotLibraryHistory(currentHistoryIndex() + 1);
	return writeLibraryHistory(next, urlFromState(next), 'push');
}

export function persistLibraryHistory(): void {
	void replaceLibraryHistory();
}

// The routes that mount the library workspace: the home path, an album
// address (issue #269) and, since issue #286, a playlist address. All three
// render the same workspace, so nothing has to be pushed off /album/<slug>
// or /playlist/<slug> to make a song, a playlist or the wall visible — the
// address a surface owns is written by libraryHistoryUrl. Used only by
// routes/+layout.svelte now (to decide whether to start the live event
// stream) — every entry point below used to route a stale-route precondition
// through this first (issue #264's ensureLibraryWorkspaceRoute), but since
// #269 gave every write its own address, writeLibraryHistory's own crossing
// check (libraryRouteShape in libraryContext.ts) already reaches the router
// for a write landing on any of these three paths from anywhere else,
// including a non-library one; a second, separate guard here would only ever
// duplicate that check, never catch something it misses (#265's S7 proved
// this per entry point rather than assuming it — see navigation.test.ts).
export function isLibraryWorkspacePath(pathname: string): boolean {
	return pathname === '/' || isAlbumRoutePath(pathname) || isPlaylistRoutePath(pathname);
}

// A dirty editor draft blocks a song switch or leave (rail row, prev/next,
// breadcrumb, Escape, Library, a collection opened anywhere, a rail page
// link, Logout) until the owner resolves it: the deferred navigation is
// parked here, and SongDetailView renders the Save / Discard / Cancel
// confirm and either runs the parked action (Discard, or Save then run it)
// or drops it (Cancel). Only the song's own surface can dirty a draft, and
// a way out that skips this guard unmounts that confirm while the draft
// stays dirty, so a later guarded tap would park with no one to ask
// (issue #1143).
export const pendingDirtyNavigation = writable<(() => void | Promise<void>) | null>(null);

// The single gatekeeper for every navigation that would drop the current
// editor draft: a dirty draft parks `action` in `pendingDirtyNavigation`
// instead of running it (see the comment above), a clean draft runs it
// immediately. Every song-switch/leave entry point must route through this
// — never re-implement the if/else inline. The phone drawer closes over a
// parked navigation: the question now belongs to the song behind it, and
// Keep editing must land on that draft, not on the drawer (issue #1143).
async function guardDirtyNavigation(action: () => void | Promise<void>): Promise<void> {
	if (get(isDirty)) {
		closeSidebar();
		pendingDirtyNavigation.set(action);
		return;
	}
	await action();
}

// The rail context (and every other "song open" entry point — search hits,
// history restore, and, since issue #284, a redirected legacy `?song=` link
// once its canonical route mounts) never leaves the rail empty: whenever
// the selected song's album is not the open collection, the collection
// follows the song. Opening a collection explicitly (openAlbum/openPlaylist)
// is unaffected — this only reacts to a *song* becoming current.
function ensureCollectionMatchesSong(song: SongItem): void {
	const current = get(openCollection);
	if (current?.kind === 'album' && current.id === song.album_id) return;
	setOpenCollection({ kind: 'album', id: song.album_id });
}

// The song address names its song by slug (issue #275), and a rename changes
// that slug server-side. The song's own view is what triggers the rename and
// already writes the renamed song back into songList, so this is the one
// place that can notice the slug moved on the currently open song and pull
// the address along -- it fires only on a slug change of the *same* song,
// never on an ordinary selection (that already writes its own entry) or on
// unrelated song edits (lyrics/prompt autosave), and only while the address
// bar is already a song address; a legacy `?song=` entry never reaches this
// function at all -- (library)/+page.svelte redirects it onto its canonical
// address first (issue #284) -- see the note on libraryHistoryUrl.
let addressedSong: { id: string; slug: string } | null = null;

function syncSongAddressToRename(song: SongItem): void {
	const previous = addressedSong;
	addressedSong = { id: song.id, slug: song.slug };
	if (!previous || previous.id !== song.id || previous.slug === song.slug) return;
	if (!isSongRoutePath(window.location.pathname)) return;
	void replaceLibraryHistory();
}

selectedSong.subscribe((song) => {
	if (!song) {
		addressedSong = null;
		return;
	}
	ensureCollectionMatchesSong(song);
	syncSongAddressToRename(song);
});

// The playlist address names its playlist by slug (issue #286), and a
// rename changes that slug server-side (unique_playlist_slug follows the
// title, mirroring unique_song_slug) — the same gap syncSongAddressToRename
// closes for songs above, mirrored here for the currently open playlist.
let addressedPlaylist: { id: string; slug: string } | null = null;

function syncPlaylistAddressToRename(playlist: PlaylistItem): void {
	const previous = addressedPlaylist;
	addressedPlaylist = { id: playlist.id, slug: playlist.slug };
	if (!previous || previous.id !== playlist.id || previous.slug === playlist.slug) return;
	if (!isPlaylistRoutePath(window.location.pathname)) return;
	void replaceLibraryHistory();
}

selectedPlaylist.subscribe((playlist) => {
	if (!playlist) {
		addressedPlaylist = null;
		return;
	}
	syncPlaylistAddressToRename(playlist);
});

export function openAlbum(albumId: string): Promise<void> {
	return guardDirtyNavigation(async () => {
		storeDeselectPlaylist();
		setOpenCollection({ kind: 'album', id: albumId });
		selectedSongId.set(null);
		selectedGenerationId.set(null);
		void loadSongsForAlbum(albumId);
		setLibrarySurface('detail');
		closeSidebar();
		await pushLibraryHistory();
	});
}

export function openPlaylist(playlistId: string): Promise<void> {
	return guardDirtyNavigation(async () => {
		selectedSongId.set(null);
		selectedGenerationId.set(null);
		void loadPlaylistDetail(playlistId);
		// A playlist can be opened before playlistList is populated (Shares
		// inventory, a deep link, mobile without the Rail mounted) --
		// PlaylistDetailView falls back to the detail fetch for its header
		// meanwhile, but this is awaited (not fire-and-forget) so the playlist's
		// slug is in hand before pushLibraryHistory below asks libraryHistoryUrl
		// to build the /playlist/<slug> address — without it, the write would
		// fall back to '/' for exactly the callers that need it most (issue
		// #286).
		await ensurePlaylistsLoaded();
		setLibrarySurface('detail');
		closeSidebar();
		await pushLibraryHistory();
	});
}

// The rail search has one selected result and therefore one destination. Its
// data owner only describes that destination; this navigation owner performs
// the transition and closes the compact drawer on every successful choice.
export async function openRailSearchTarget(target: RailSearchTarget): Promise<void> {
	if (target.kind === 'album') {
		await openAlbum(target.id);
		return;
	}
	if (target.kind === 'song') {
		await selectSong(target.id);
		return;
	}
	if (target.kind === 'playlist') {
		await openPlaylist(target.id);
		return;
	}
	if (target.href === '/') {
		await openLibraryWall();
		return;
	}
	await openAppPage(target.href);
}

// An app-page link (a Settings row, the account name or its menu, a search hit
// that names a page) leaves the song for an app page, so it asks the same
// dirty-draft question as every other way out before it navigates. The phone
// drawer closes first and its entry steps back, and the page is pushed only
// once that step has landed: SvelteKit keeps a replaced entry's navigation
// index, so a page written over the drawer's shallow entry would share its
// index with the library entry below, and Back onto it would move the address
// without loading the library (issue #1165). A step still in flight when the
// page starts loading would abort it, which is why the push waits.
type AppPageHref = Extract<RailSearchTarget, { kind: 'page' }>['href'];

export function openAppPage(href: AppPageHref): Promise<void> {
	return guardDirtyNavigation(async () => {
		closeSidebar();
		await libraryHistoryStepsLanded();
		await goto(resolve(href));
	});
}

// An app-page `<a href>` inside the shell or the song surface: a plain click
// goes through `openAppPage`, while a modified or non-primary click (a new
// tab or window) keeps the browser default, because it never leaves the song.
export function followAppPageLink(event: MouseEvent, href: AppPageHref): void {
	const opensElsewhere =
		event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
	if (opensElsewhere) return;
	event.preventDefault();
	void openAppPage(href);
}

// Logout drops the session and with it the draft, so it asks the same
// dirty-draft question first.
export function leaveForLogout(logout: () => void | Promise<void>): Promise<void> {
	return guardDirtyNavigation(logout);
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
		void replaceLibraryHistory();
	});
}

// The rail's "Library" link: leaves the open song (if any) but keeps the
// open collection in the rail context (GitLab-style — the context persists
// until another collection replaces it), and always pushes a fresh history
// entry so the browser back button returns to whatever was open before.
export async function openLibraryWall(): Promise<void> {
	await guardDirtyNavigation(async () => {
		selectedSongId.set(null);
		selectedGenerationId.set(null);
		setLibrarySurface('browse');
		closeSidebar();
		await pushLibraryHistory();
	});
}

interface AlbumTrackNeighbors {
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

// This module's single "a song is now open" hook, used by its three entry
// points: applySelectedSong (selectSong, selectNeighborSong,
// revealPlayingSong), the history-restore branch of initNavigation, and
// onPopstate. Loads the song's takes and, alongside
// that, recovers its failure banner from the last failed generate job so a
// reload or a later visit shows the same cause a live SSE stream would have
// (see hydrateGenerationFailure). A new entry point added to this module
// should route through this instead of calling ensureGenerationsLoaded
// directly; it does not cover song selection elsewhere (e.g. player.ts's
// own playback-driven selectSong).
//
// A dead songId (deleted between the link being shared/saved and it being
// opened, issue #237) is a permanent, expected condition, not a transient
// failure: it clears only the dead selection. Other failures leave the
// selection available for retry and surface through SongDetailView.refreshTakes.
function loadSongContext(songId: string): Promise<void> {
	void hydrateGenerationFailure(songId);
	void hydrateActiveGeneration(songId).catch((err: unknown) => {
		if (isNotFound(err)) return;
		addToast(describeFailure(err, API_ERROR_GENERIC_MESSAGE), 'error');
	});
	return ensureGenerationsLoaded(songId).catch(function acknowledgeOwnedFailure(err: unknown) {
		if (isNotFound(err)) {
			reportSongLinkNotFound(songId);
		}
		// refreshTakes owns the shared load's error and retry; this background
		// caller must consume its rejection without reporting it a second time.
	});
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
	void replaceLibraryHistory();
	addToast(SONG_LINK_NOT_FOUND_TOAST, 'error');
}

function applySelectedSong(
	songId: string,
	knownSong: SongItem | undefined,
	historyMode: 'stack' | 'replace',
	tab: 'keep' | 'remembered'
): Promise<void> {
	storeDeselectPlaylist();
	if (knownSong) hydrateSongIntoLibrary(knownSong);
	const song = get(songList).find((item) => item.id === songId) ?? knownSong;
	const albumId = song?.album_id ?? null;
	if (albumId) {
		selectedAlbumId.set(albumId);
		void loadSongsForAlbum(albumId);
	}
	playerSelectSong(songId);
	void loadSongContext(songId);
	showSongTab(songId, tab === 'keep' ? get(detailTab) : rememberedSongTab(songId));
	setLibrarySurface('detail');
	closeSidebar();
	if (historyMode === 'replace') return replaceLibraryHistory();
	return pushLibraryHistory();
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

// Returns a promise, though every current caller (rail/list clicks) is
// fire-and-forget: a caller that needs follow-up state set once the song is
// actually current must not await this and add the follow-up after it —
// guardDirtyNavigation resolves immediately once it parks a dirty draft,
// before applySelectedSong ever runs, so that follow-up would land against
// whichever song was open before (issue #265 review of #264, fixed for its
// one real caller by folding the follow-up into a single guarded action —
// see revealSharedTake below). A future such caller belongs the same way.
export function selectSong(songId: string, knownSong?: SongItem): Promise<void> {
	// Evaluated before the guard's own possible park: a dirty draft defers
	// `applySelectedSong` until the confirm resolves, so historyMode must read
	// selectedSongId/openCollection as they stand right now, not whatever they
	// become once that later run starts.
	const historyMode = selectSongHistoryMode(songId, knownSong);
	return guardDirtyNavigation(async () => {
		await applySelectedSong(songId, knownSong, historyMode, 'remembered');
	});
}

export function selectNeighborSong(song: SongItem): Promise<void> {
	return guardDirtyNavigation(async () => {
		await applySelectedSong(song.id, song, 'replace', 'keep');
	});
}

// LibraryWall's share-inventory row for a shared take (a song_id plus a
// generation id, not a full playable share of the song itself) needs the
// song switch and the generation pin to land as one guarded action, exactly
// like revealPlayingSong below: pinning the take is follow-up state that
// must run once the song is actually current, not once selectSong's promise
// resolves, since a dirty draft resolves that promise the moment it parks
// the switch (see the note on selectSong above). Unlike revealPlayingSong,
// the row carries only the song's id, not a hydrated SongItem, matching
// selectSong's own knownSong-optional shape.

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

export function clearGenerationSelection(): void {
	playerClearGeneration();
}

export function navigateToSongTab(tab: DetailTab): void {
	playerClearGeneration();
	chooseSongTab(tab);
}

export function openEditTab(): void {
	chooseSongTab('edit');
}

// The open entry carries the choice too, so a reload restores the tab the
// song was left on; the address itself does not change.
function chooseSongTab(tab: DetailTab): void {
	showSongTab(get(selectedSongId), tab);
	const current = currentLibraryHistoryState();
	if (!isLibraryHistoryState(current)) return;
	void writeLibraryHistory({ ...current, detailTab: tab }, urlFromState(current), 'replace');
}

function openTakesTab(): void {
	detailTab.set('takes');
}

// The dirty-draft guard runs before anything else moves, matching every
// other song-switch entry point (issue #265 S7; previously this navigated to
// the library workspace via ensureLibraryWorkspaceRoute *before*
// guardDirtyNavigation ran, so Cancel on the confirm still left the person
// pushed off wherever they were, e.g. Settings).
export async function revealPlayingSong(song: SongItem, generationId: string): Promise<void> {
	await guardDirtyNavigation(async () => {
		await applySelectedSong(song.id, song, 'stack', 'remembered');
		selectedGenerationId.set(generationId);
		persistLibraryHistory();
	});
}

export function goBack(): void {
	const state = currentLibraryHistoryState();
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
	void replaceLibraryHistory();
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
		addToast(describeFailure(e, EDITOR_SAVE_FAILED), 'error');
	}
}

async function saveDirtyDraftBeforePopstate(): Promise<void> {
	if (savingDraft !== null) {
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

// History layers (issues #1002, #1114): while the library history runs, every
// layer opened on the stack (stores/layers.ts) owns one history entry on top
// of the library it covers, at the same address. Back then closes the topmost
// layer and leaves that library exactly as it was -- no workspace re-apply, no
// dirty-draft save -- instead of applying whatever entry sits below it while
// the overlay stays on top. The entry is a copy of that library marked with
// the layer's id, and replace writes keep the mark (libraryContext.ts). A layer
// that leaves any other way (×, Done, Escape, a surface change) steps back off
// its entry, so no stale copy of the library is left for Back to land on. Off
// the library (Settings) a layer owns no entry: Back leaves the page as it
// always has.
//
// The library entry under each layer's own entry, for the layers that own one.
const libraryBelowLayer = new Map<Layer, LibraryHistoryState>();
// Step-backs issued here rather than by the browser: their popstates land on
// an entry whose library is already showing, so they apply nothing.
let ownLayerStepBacks = 0;

const libraryLayerHistory: LayerHistory = {
	held(layer) {
		const below = currentLibraryHistoryState();
		if (!isLibraryHistoryState(below)) return;
		libraryBelowLayer.set(layer, below);
		void writeLibraryHistory(
			{ ...below, index: below.index + 1, layer: layer.id },
			urlFromState(below),
			'push'
		);
	},
	left(layer) {
		const below = libraryBelowLayer.get(layer);
		libraryBelowLayer.delete(layer);
		if (below && ownsTopEntry(layer, below)) stepBackOnto(below);
	}
};

function ownsTopEntry(layer: Layer, below: LibraryHistoryState): boolean {
	const top = currentLibraryHistoryState();
	return isLibraryHistoryState(top) && top.layer === layer.id && top.index === below.index + 1;
}

function stepBackOnto(landing: LibraryHistoryState): void {
	ownLayerStepBacks += 1;
	void backLibraryHistory(landing, urlFromState(landing));
}

function leftByStepTo(layer: Layer, landing: number): boolean {
	const below = libraryBelowLayer.get(layer);
	return below === undefined || below.index >= landing;
}

// A popstate that leaves layer entries closes those layers, topmost first.
// A step onto the entry right below them keeps the library as it stands; a
// longer jump (several entries back at once) applies its own entry as usual.
function popsHistoryLayers(state: unknown): boolean {
	if (ownLayerStepBacks > 0) {
		ownLayerStepBacks -= 1;
		stepOffStackedStaleLayerEntry(state);
		return true;
	}
	const landing = isLibraryHistoryState(state) ? state.index : -1;
	const layers = stackedLayers();
	let depth = layers.length;
	while (depth > 0 && leftByStepTo(layers[depth - 1], landing)) depth -= 1;
	const left = dropLayersFrom(depth);
	const lowestLeftBelow = left.length > 0 ? libraryBelowLayer.get(left[0]) : undefined;
	for (const layer of left) libraryBelowLayer.delete(layer);
	const staleLanding = staleLayerEntryLanding(state);
	if (staleLanding) {
		// The copy may be out of date -- the entry below can be rewritten after
		// Back closed its layer -- so it applies nothing; the step's own
		// popstate applies the entry it lands on.
		void backLibraryHistory(staleLanding, urlFromState(staleLanding));
		return true;
	}
	return lowestLeftBelow?.index === landing;
}

// Layers stack (a menu over Now Playing), so the last of this module's own
// step-backs off a stale layer entry -- after a reload on the top one -- can
// land on the stale entry of the layer below, and steps on until it reaches
// the library. A write already queued past that entry (an album row in the
// drawer over the cover editor, which the new album closes) moves on from it
// by itself; stepping off as well would land behind that write, on the
// library it left.
function stepOffStackedStaleLayerEntry(state: unknown): void {
	if (ownLayerStepBacks > 0 || historyMovesOnFrom(state)) return;
	const staleLanding = staleLayerEntryLanding(state);
	if (staleLanding) stepBackOnto(staleLanding);
}

function historyMovesOnFrom(state: unknown): boolean {
	const planned = currentLibraryHistoryState();
	return (
		isLibraryHistoryState(state) && isLibraryHistoryState(planned) && planned.index !== state.index
	);
}

// An entry marked as a layer that no open layer owns -- left behind by a
// reload, or reached again with Forward after Back closed its layer -- is a
// copy of the library below it, where Back would visibly do nothing; the
// caller steps off it onto that library. Any open layer can own it, not only
// the top one: a sheet reopened over Now Playing before the step back off its
// old entry lands already sits above the Now Playing entry that step reaches.
function staleLayerEntryLanding(state: unknown): LibraryHistoryState | null {
	if (!isLibraryHistoryState(state) || state.layer === undefined) return null;
	const ownedByOpenLayer = Array.from(libraryBelowLayer).some(
		([layer, below]) => layer.id === state.layer && below.index === state.index - 1
	);
	if (ownedByOpenLayer) return null;
	return { ...state, index: state.index - 1, layer: undefined };
}

// The shell's own overlays -- full Now Playing and the phone drawer -- live in
// stores rather than in one component, so the app layout follows them here for
// as long as it is mounted, on every page.
export function followShellLayers(): () => void {
	const stopFollowingNowPlaying = nowPlayingFullChosen.subscribe(
		layerSwitch('now-playing', escapeNowPlaying)
	);
	const stopFollowingRailDrawer = sidebarOpen.subscribe(layerSwitch('rail-drawer', closeSidebar));
	return () => {
		stopFollowingNowPlaying();
		stopFollowingRailDrawer();
	};
}

// A cold tab's history entry carries no LibraryHistoryState until something
// writes one -- this seeds a fresh root entry for that case, but only on a
// plain `/` visit, which is the one library workspace path with no address
// route of its own to resolve one instead. Every other library path
// (`/album/<slug>` and every segment deeper, `/playlist/<slug>`) is owned by
// its own leaf page, whose `$effect` calls the matching openXAddress and
// writes the real entry once resolution lands -- found or, honestly, not.
// Racing this seed against that resolution used to cost more than a redundant
// write: found and not-yet-written are indistinguishable to
// isLibraryHistoryState, so on an *unknown* address (nothing else ever
// writes) this branch would unconditionally win the race once the live
// stream's own bootstrap finished, replacing the honest 404 overlay with a
// crossing `goto('/')` back to the wall -- discovered against a real stack
// (playlist-address.spec.ts, issue #286), not caught by jsdom, whose harness
// mounts only the `(library)` group layout and never exercises this one.
//
// A legacy `/?song=<uuid>` (or `&gen=<uuid>`) query used to be read and
// applied right here; since issue #284, (library)/+page.svelte owns that
// instead -- it resolves the ids and redirects onto the canonical song/take
// address before this ever runs, so there is nothing left for this branch to
// special-case.
export function initNavigation(): () => void {
	const existing = currentLibraryHistoryState();
	if (!isLibraryHistoryState(existing)) {
		if (window.location.pathname === '/') void replaceLibraryHistory();
	} else if (existing.songId) {
		void loadSongContext(existing.songId);
	}
	const staleLanding = staleLayerEntryLanding(existing);
	if (staleLanding) stepBackOnto(staleLanding);

	function onPopstate(e: PopStateEvent): void {
		const state = libraryHistoryEntry(e.state);
		if (popsHistoryLayers(state)) return;
		void (async () => {
			await holdLibraryRestoresUntil(saveDirtyDraftBeforePopstate());
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
	keepLayerHistory(libraryLayerHistory);
	return () => {
		window.removeEventListener('popstate', onPopstate);
		forgetLayerEntries();
	};
}

// The library history stops: the overlays still open keep their layers, which
// own no history entry any more.
export function forgetLayerEntries(): void {
	keepLayerHistory(null);
	libraryBelowLayer.clear();
	ownLayerStepBacks = 0;
}

export function resetNavigationForTests(): void {
	suppressPush = false;
	forgetLayerEntries();
	resetLayersForTests();
	pendingDirtyNavigation.set(null);
	openTakesTab();
	addressedSong = null;
}
