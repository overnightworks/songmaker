import { listOfPage, SETTINGS_HREF } from '$lib/routes/pageBack';
import { goto } from '$app/navigation';
import { resolve } from '$app/paths';
import { get, writable } from 'svelte/store';
import { layerSwitch, resetLayersForTests } from '$lib/stores/layers';
import { fetchAlbum } from '$lib/api/albums';
import {
	historyComesToRest,
	attachLandingHandler,
	releaseLayerEntriesForTests,
	stepBackOffStandingEntry,
	stepBackOr,
	stepBackOrGoTo,
	type Landing
} from '$lib/history/historyController';
import { describeFailure, isNotFound } from '$lib/api/fetch';
import { draftHasUnversionedChanges, pendingVersionLoad } from '$lib/stores/editor';
import { hydrateActiveGeneration, hydrateGenerationFailure } from '$lib/stores/jobs';
import { addToast } from '$lib/stores/toast';
import { albumList, loadSongsForAlbum, songList } from '$lib/stores/libraryData';
import {
	selectedSongId,
	selectedGenerationId,
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
import type { PlaylistItem, SongItem } from '$lib/api/types';
import type { RailSearchTarget } from '$lib/stores/railSearch';
import {
	ADMIN_WORKER_POOL_HREF,
	API_ERROR_GENERIC_MESSAGE,
	SONG_LINK_NOT_FOUND_TOAST
} from '$lib/constants';
import {
	isPlaylistRoutePath,
	isSongRoutePath,
	LIBRARY_ROUTE_PATH,
	libraryRouteShape,
	PLAYLISTS_ROUTE_PATH
} from '$lib/routes/addresses';
import {
	applyLibraryHistory,
	cancelLibraryHistoryApply,
	captureLibraryScroll,
	currentLibraryHistoryState,
	detailTab,
	enterAlbumOfSong,
	holdLibraryRestoresUntil,
	isLibraryHistoryState,
	keepLibraryPageAsLeft,
	libraryHistoryEntry,
	libraryHistoryUrl,
	libraryRootState,
	librarySurface,
	rememberedSongTab,
	setLibrarySurface,
	showSongTab,
	targetAlreadyShown,
	snapshotLibraryHistory,
	writeLibraryHistory,
	type DetailTab
} from '$lib/stores/libraryContext';

export type { DetailTab };
export { detailTab };

function currentHistoryIndex(): number {
	const state = currentLibraryHistoryState();
	return isLibraryHistoryState(state) ? state.index : 0;
}

// Every history write in this module goes through writeLibraryHistory, which
// owns the choice between shallow routing and a navigation; see the note on
// it in libraryContext.ts. Its promise settles once a crossing has mounted its
// route; the entry itself stands at once, unless history the controller has
// moving still holds it.
function replaceLibraryHistory(): Promise<void> {
	cancelLibraryHistoryApply();
	const next = snapshotLibraryHistory(currentHistoryIndex());
	return writeLibraryHistory(next, libraryHistoryUrl(next), 'replace');
}

// `enterPage` runs once the page being left has been kept and before the new
// entry is snapshotted, so a reset only the new entry should see cannot reach
// the entry left behind.
function pushLibraryHistory(enterPage: () => void = () => {}): Promise<void> {
	cancelLibraryHistoryApply();
	void keepLibraryPageAsLeft();
	enterPage();
	const next = snapshotLibraryHistory(currentHistoryIndex() + 1);
	return writeLibraryHistory(next, libraryHistoryUrl(next), 'push');
}

// A link to a take of the song on screen: one entry of the song at the take's
// anchor, so Back returns to the place the person clicked from. The browser's
// own hash jump would write an entry without the library state, and the
// library would read none. It does not leave the song, so it is not guarded,
// and it keeps no page as left: that replace would strip the anchor from a
// standing anchor entry.
export function jumpToTake(takeId: string): Promise<void> {
	const anchor = `#take-${takeId}`;
	if (location.hash === anchor) return Promise.resolve();
	cancelLibraryHistoryApply();
	const next = snapshotLibraryHistory(currentHistoryIndex() + 1);
	return writeLibraryHistory(next, libraryHistoryUrl(next) + anchor, 'push');
}

export function persistLibraryHistory(): void {
	void replaceLibraryHistory();
}

// The routes that mount the library workspace: every address
// `libraryRouteShape` gives a library shape -- the Home and Library paths, the
// Playlists page (#1402), and each album, song, take and playlist address. All
// render the same workspace, and the address a surface owns is written by
// libraryHistoryUrl. Used only by routes/+layout.svelte (to decide whether to
// start the live event stream): writeLibraryHistory's own crossing check
// reaches the router for a write landing on any of these addresses from
// anywhere else, so no entry point below asks this first (#265's S7 proved
// that per entry point -- see navigation.test.ts).
export function isLibraryWorkspacePath(pathname: string): boolean {
	return libraryRouteShape(pathname) !== 'external';
}

// A draft with changes no version holds blocks a song switch or leave (rail
// row, prev/next, breadcrumb, Escape, Library, a collection opened anywhere, a
// rail page link, Logout, browser or phone Back that leaves the song) until the owner resolves it:
// the deferred navigation is parked here, and SongDetailView renders the Save /
// Discard / Cancel confirm and either runs the parked action (Discard, or
// Save then run it) or drops it (Cancel). Only the song's own surface can dirty a draft, and
// a way out that skips this guard unmounts that confirm while the draft
// stays dirty, so a later guarded tap would park with no one to ask
// (issue #1143).
export const pendingDirtyNavigation = writable<(() => void | Promise<void>) | null>(null);

// The single gatekeeper for every navigation that would drop the current
// editor draft: a draft with changes no version holds parks `action` in
// `pendingDirtyNavigation` instead of running it (see the comment above); a
// draft equal to a saved version, such as an untouched load, loses nothing by
// leaving and runs it immediately (#1296). Every song-switch/leave entry
// point must route through this — never re-implement the if/else inline. A
// way out that has already moved history puts the song back first, through
// `beforeAsking`, so Keep editing stays on that draft (issue #1143).
async function guardDirtyNavigation(
	action: () => void | Promise<void>,
	beforeAsking: () => void = () => undefined
): Promise<void> {
	if (get(draftHasUnversionedChanges)) {
		beforeAsking();
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
		hydrateAlbumIntoLibrary(albumId);
		setLibrarySurface('detail');
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
		// fall back to the Library for exactly the callers that need it most
		// (issue #286).
		await ensurePlaylistsLoaded();
		setLibrarySurface('detail');
		await pushLibraryHistory();
	});
}

// The rail search has one selected result and therefore one destination. Its
// data owner only describes that destination; this navigation owner performs
// the transition. Phone tabs use the same page targets.
export async function openRailSearchTarget(target: RailSearchTarget): Promise<void> {
	if (targetAlreadyShown(target)) {
		await historyComesToRest();
		return;
	}
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
	if (target.href === LIBRARY_ROUTE_PATH) {
		await openLibraryWall();
		return;
	}
	if (target.href === PLAYLISTS_ROUTE_PATH) {
		await openPlaylistsWall();
		return;
	}
	await openAppPage(target.href);
}

// An app-page link (a Settings row, the account name or its menu, a search hit
// that names a page) leaves the song for an app page, so it asks the same
// dirty-draft question as every other way out before it navigates. Pending
// history-layer steps must land before pushing the page (#1165, #1289).
type AppPageHref =
	Extract<RailSearchTarget, { kind: 'page' }>['href'] | typeof ADMIN_WORKER_POOL_HREF;

export function openAppPage(href: AppPageHref): Promise<void> {
	return guardDirtyNavigation(async () => {
		await historyComesToRest();
		await keepLibraryPageAsLeft();
		const args: [AppPageHref] = [href];
		await goto(resolve(...(args as Parameters<typeof resolve>)));
	});
}

function isPlainPrimaryClick(event: MouseEvent): boolean {
	return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

export function followPlainClick(event: MouseEvent, open: () => void | Promise<void>): void {
	if (!isPlainPrimaryClick(event)) return;
	event.preventDefault();
	void open();
}

// An app-page `<a href>` inside the shell or the song surface: a plain click
// goes through `openAppPage`, while a modified or non-primary click (a new
// tab or window) keeps the browser default, because it never leaves the song.
export function followAppPageLink(event: MouseEvent, href: AppPageHref): void {
	followPlainClick(event, () => openAppPage(href));
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
		void backToCollection();
		return;
	}
	if (collection.kind === 'album') void openAlbum(collection.id);
	else void openPlaylist(collection.id);
}

export function backToCollection(): Promise<void> {
	return guardDirtyNavigation(() => {
		selectedSongId.set(null);
		selectedGenerationId.set(null);
		openTakesTab();
		setLibrarySurface(get(openCollection) ? 'detail' : 'browse');
		return replaceLibraryHistory();
	});
}

// The wall shows in place of the open song or collection, while the open
// collection stays in the rail context (GitLab-style — the context persists
// until another collection replaces it).
function showLibraryWall(): void {
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	setLibrarySurface('browse');
}

// The rail's "Library" link always pushes a fresh history entry, so the
// browser back button returns to whatever was open before.
export async function openLibraryWall(): Promise<void> {
	await guardDirtyNavigation(async () => {
		showLibraryWall();
		await pushLibraryHistory();
	});
}

// Home (#1506) and the Playlists page (#1402) in place of the open song or
// collection, which stays the rail context as it does behind the Library wall.
// Coming from another page they start at their top: the one scroll the library
// keeps is the Library wall's.
function showPageOverCollection(surface: 'home' | 'playlists'): () => void {
	const cameFromAnotherPage = get(librarySurface) !== surface;
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	setLibrarySurface(surface);
	return () => {
		if (cameFromAnotherPage) captureLibraryScroll(0);
	};
}

// The brand's destination. Like the Library, a fresh history entry, so Back
// returns to what was open.
export async function openHome(): Promise<void> {
	await guardDirtyNavigation(async () => {
		await pushLibraryHistory(showPageOverCollection('home'));
	});
}

// Like Home and the Library, a fresh history entry.
async function openPlaylistsWall(): Promise<void> {
	await guardDirtyNavigation(async () => {
		await pushLibraryHistory(showPageOverCollection('playlists'));
	});
}

type PageList = typeof LIBRARY_ROUTE_PATH | typeof PLAYLISTS_ROUTE_PATH;

// Library walls restore their stores as well as replacing the address.
function openListOverPage(list: PageList): Promise<void> {
	if (list === LIBRARY_ROUTE_PATH) showLibraryWall();
	else showPageOverCollection('playlists')();
	return replaceLibraryHistory();
}

// Only the domain fallback belongs here; the controller owns traversal.
export function stepBackFromPage(pathname: string): Promise<void> {
	if (isSongRoutePath(pathname)) return stepBackOr(backToCollection);
	const list = listOfPage(pathname);
	if (list === SETTINGS_HREF) return stepBackOrGoTo(list);
	return stepBackOr(() => openListOverPage(list));
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
		addToast(describeFailure(err, API_ERROR_GENERIC_MESSAGE), 'error', err);
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
	selectedSongId.set(null);
	selectedGenerationId.set(null);
	setLibrarySurface(get(openCollection) ? 'detail' : 'browse');
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
	if (song) enterAlbumOfSong(song);
	playerSelectSong(songId);
	void loadSongContext(songId);
	showSongTab(songId, tab === 'keep' ? get(detailTab) : rememberedSongTab(songId));
	setLibrarySurface('detail');
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
// one real caller by folding the follow-up into a single guarded action).
// A future such caller belongs the same way.
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
	hydrateAlbumIntoLibrary(song.album_id);
}

function hydrateAlbumIntoLibrary(albumId: string): void {
	if (get(albumList).some((item) => item.id === albumId)) return;
	void fetchAlbum(albumId)
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
	void writeLibraryHistory({ ...current, detailTab: tab }, libraryHistoryUrl(current), 'replace');
}

export function openTakesTab(): void {
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

// "Open vN" on a take in Now Playing: the take's song shows the version
// loaded. Over changes no version holds on that same song, its page asks
// before the load replaces them, so leaving and re-entering the song would ask
// about the draft twice.
export async function openTakeVersion(
	song: SongItem,
	generationId: string,
	versionId: string
): Promise<void> {
	pendingVersionLoad.set({ songId: song.id, versionId });
	if (get(selectedSongId) === song.id && get(draftHasUnversionedChanges)) return;
	await revealPlayingSong(song, generationId);
}

// Browser Back/Forward has already moved the address by the time `popstate`
// fires, so a dirty draft cannot hold it the way every other guarded way out
// does. The song's entry is written back on top of the one landed on before
// the question instead (issue #1143): Cancel stays on the song with its
// draft, Discard -- or Save, once it has saved -- steps back onto the entry
// the traversal reached, whose landing then applies it. Back never saves or
// discards a draft by itself. After a reload every traversal is a router
// navigation, so the address route of that entry may already be resolving: no
// library is applied until the song's entry is back, and an apply started
// meanwhile is dropped. Documented next to the dirty-guard paragraph in
// docs/architecture.md. A Back or Forward onto another entry of the song on
// screen never gets here: it keeps the draft where it is.
function putTheSongBackOverTheLanding(): void {
	const songEntry = snapshotLibraryHistory(currentHistoryIndex() + 1);
	const songEntryBack = writeLibraryHistory(songEntry, libraryHistoryUrl(songEntry), 'push');
	void holdLibraryRestoresUntil(songEntryBack.finally(cancelLibraryHistoryApply));
}

async function stepBackOntoTraversalLanding(): Promise<void> {
	await historyComesToRest();
	void stepBackOffStandingEntry();
}

async function applyLanding(state: unknown): Promise<void> {
	if (!isLibraryHistoryState(state)) {
		await applyLibraryHistory(libraryRootState());
		return;
	}
	const applied = await applyLibraryHistory(state);
	if (applied && state.songId) await loadSongContext(state.songId);
}

// Full Now Playing lives in a store, so the layout follows its history layer
// for as long as it is mounted, on every page.
export function followShellLayers(): () => void {
	return nowPlayingFullChosen.subscribe(layerSwitch('now-playing', escapeNowPlaying));
}

// The history controller's landing handler: by the time a landing reaches
// here the controller has closed the layers it left, so only a landing on
// another page entry is the library's to apply. A landing that keeps the song
// on screen loses no draft (the editor reloads only for another song), so it
// asks nothing; one that leaves the song asks as every other way out does.
function onLanding(landing: Landing, landedState: unknown): void {
	if (!landing.apply) return;
	const state = libraryHistoryEntry(landedState);
	if (isLibraryHistoryState(state) && state.songId && state.songId === get(selectedSongId)) {
		void applyLanding(state);
		return;
	}
	let songPutBack = false;
	void guardDirtyNavigation(
		() => (songPutBack ? stepBackOntoTraversalLanding() : applyLanding(state)),
		() => {
			putTheSongBackOverTheLanding();
			songPutBack = true;
		}
	);
}

// Each address page resolves its own initial Library entry. Navigation
// restores an existing song context and owns subsequent history landings.
export function initNavigation(): () => void {
	const existing = currentLibraryHistoryState();
	if (isLibraryHistoryState(existing) && existing.songId) {
		void loadSongContext(existing.songId);
	}

	return attachLandingHandler(onLanding);
}

export function resetNavigationForTests(): void {
	releaseLayerEntriesForTests();
	resetLayersForTests();
	pendingDirtyNavigation.set(null);
	openTakesTab();
	addressedSong = null;
}
