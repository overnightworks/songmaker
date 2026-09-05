import { get, writable } from 'svelte/store';
import { goto } from '$app/navigation';
import { fetchAlbum } from '$lib/api/albums';
import { fetchPlaylists } from '$lib/api/client';
import { isNotFound } from '$lib/api/fetch';
import type { LibrarySort } from '$lib/api/library';
import { fetchSong, fetchSongs } from '$lib/api/songs';
import type { PlaylistItem, SongItem } from '$lib/api/types';
import { LIBRARY_HISTORY_KIND, LIBRARY_SONG_PAGE_SIZE } from '$lib/constants';
import { type OpenCollection, openCollection, setOpenCollection } from '$lib/stores/collection';
import { searchQuery } from '$lib/stores/filter';
import {
	libraryBrowse,
	librarySearch,
	librarySort,
	restoreLibraryBrowse,
	restoreLibrarySearch
} from '$lib/stores/librarySearch';
import { albumList, loadSongsForAlbum, songList, upsertSongInList } from '$lib/stores/libraryData';
import { ensureGenerationsLoaded, selectedGenerationId, selectedSongId } from '$lib/stores/player';
import { deselectPlaylist, loadPlaylistDetail, playlistList } from '$lib/stores/playlists';
import {
	albumRoutePath,
	legacySongRoutePath,
	libraryRouteShape,
	pendingTakeRoutePath,
	playlistRoutePath,
	songRoutePath,
	takeRoutePath
} from '$lib/routes/addresses';
import { CREATED_SORTS } from '$lib/utils/recency';

// 'browse' shows the library wall (the LibraryWall component); 'detail' shows
// whichever collection is currently open; 'create' shows the create form.
// Song detail always wins over all three (see LibraryWorkspace.svelte).
export type LibrarySurface = 'browse' | 'detail' | 'create';
// Editor tabs (epic #98): 'write' hosts style/lyrics (and Co-Writer mode),
// 'takes' lists generations. Superseded the pre-#100 'generations'|'edit'|'chat'
// trio; LEGACY_DETAIL_TAB_MAP below keeps old persisted history entries valid.
export type DetailTab = 'write' | 'takes';

type CollectionSnapshot = OpenCollection | null;

export interface LibraryHistoryState {
	kind: typeof LIBRARY_HISTORY_KIND;
	index: number;
	surface: LibrarySurface;
	query: string;
	sort: LibrarySort;
	albumOffset: number;
	songOffset: number;
	searchCursor: string | null;
	searchLoadedCount: number;
	collection: CollectionSnapshot;
	songId: string | null;
	generationId: string | null;
	scrollAnchor: number;
	detailTab?: DetailTab;
}

// Opening a song lands on Write — on a compact layout the tabs are the only
// way in, and writing is what the editor is for (#141/13).
const DEFAULT_DETAIL_TAB: DetailTab = 'write';

export const librarySurface = writable<LibrarySurface>('browse');
export const detailTab = writable<DetailTab>(DEFAULT_DETAIL_TAB);
export const libraryScrollAnchor = writable(0);

const SURFACES: ReadonlySet<LibrarySurface> = new Set(['browse', 'detail', 'create']);
const DETAIL_TABS: ReadonlySet<DetailTab> = new Set(['write', 'takes']);
const LEGACY_DETAIL_TAB_MAP: Record<string, DetailTab> = {
	generations: 'takes',
	edit: 'write',
	chat: 'write'
};
const SORTS: ReadonlySet<string> = new Set(CREATED_SORTS);

let historyApplyGeneration = 0;
let historyWrites: Promise<void> = Promise.resolve();
let queuedHistoryWrites = 0;
let plannedHistory: { pathname: string; state: LibraryHistoryState } | null = null;

export function isLibrarySort(value: unknown): value is LibrarySort {
	return typeof value === 'string' && SORTS.has(value);
}

function isHistoryRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null;
}

function hasValidHistoryMetadata(state: Record<string, unknown>): boolean {
	if (state.kind !== LIBRARY_HISTORY_KIND) return false;
	if (typeof state.index !== 'number' || !Number.isInteger(state.index) || state.index < 0) {
		return false;
	}
	return true;
}

function hasValidHistoryBrowseState(state: Record<string, unknown>): boolean {
	if (!isLibrarySurface(state.surface)) return false;
	if (typeof state.query !== 'string') return false;
	if (!isLibrarySort(state.sort)) return false;
	if (typeof state.albumOffset !== 'number' || typeof state.songOffset !== 'number') return false;
	if (typeof state.searchLoadedCount !== 'number' || state.searchLoadedCount < 0) return false;
	if (typeof state.scrollAnchor !== 'number') return false;
	return true;
}

function hasValidHistorySelection(state: Record<string, unknown>): boolean {
	if (!isIdOrNull(state.searchCursor)) return false;
	if (!isCollectionSnapshot(state.collection)) return false;
	if (!isIdOrNull(state.songId)) return false;
	if (!isIdOrNull(state.generationId)) return false;
	if (state.detailTab !== undefined && !isDetailTabToken(state.detailTab)) return false;
	return true;
}

export function isLibraryHistoryState(value: unknown): value is LibraryHistoryState {
	if (!isHistoryRecord(value)) return false;
	return (
		hasValidHistoryMetadata(value) &&
		hasValidHistoryBrowseState(value) &&
		hasValidHistorySelection(value)
	);
}

export function libraryRootState(): LibraryHistoryState {
	return {
		kind: LIBRARY_HISTORY_KIND,
		index: 0,
		surface: 'browse',
		query: '',
		sort: 'newest',
		albumOffset: 0,
		songOffset: 0,
		searchCursor: null,
		searchLoadedCount: 0,
		collection: null,
		songId: null,
		generationId: null,
		scrollAnchor: 0,
		detailTab: DEFAULT_DETAIL_TAB
	};
}

export function libraryWallStateFrom(state: LibraryHistoryState): LibraryHistoryState {
	return {
		...state,
		index: 0,
		surface: 'browse',
		collection: null,
		songId: null,
		generationId: null
	};
}

// An open song's own address once its slug is known (issue #275). A selected
// take addresses onto its own path one segment deeper (issue #281), by its
// generation_number rather than its uuid -- but only once that take is among
// the song's loaded generations; a take selected before its number is known
// keeps writing the query appendage until it is. A song not yet hydrated
// into songList -- a search hit or a playlist row opened by id alone
// (PlaylistDetailView, LibraryWall), before its own upsert lands -- keeps
// writing the legacy `/?song=<uuid>`/`&gen=<uuid>` form for the same reason:
// there is no slug yet to build the canonical path from, and the very next
// write, once the song has loaded, replaces it. A stale bookmark that still
// carries that older form is a different case: it never reaches this
// function's songId branch at all -- (library)/+page.svelte resolves and
// redirects it onto the canonical address first (issue #284).
export function libraryHistoryUrl(state: LibraryHistoryState): string {
	if (state.songId) {
		const song = get(songList).find((item) => item.id === state.songId);
		if (song) {
			const path = songRoutePath(song.album_id, song.slug);
			if (!state.generationId) return path;
			const takeNumber = song.generations.find(
				(generation) => generation.id === state.generationId
			)?.generation_number;
			return takeNumber !== undefined
				? takeRoutePath(song.album_id, song.slug, takeNumber)
				: pendingTakeRoutePath(path, state.generationId);
		}
		return legacySongRoutePath(state.songId, state.generationId);
	}
	if (state.surface === 'detail' && state.collection?.kind === 'album') {
		return albumRoutePath(state.collection.id);
	}
	// A playlist is named by its slug (issue #286), matching every other
	// library address; playlistList carries it once ensurePlaylistsLoaded()
	// or openPlaylistAddress's own resolution has run, which every entry
	// point that opens a playlist already awaits before writing history. The
	// rare case where it genuinely hasn't yet (the collection was restored
	// from a stale history entry whose playlist has since vanished) falls
	// back to '/' rather than a broken address -- the wall is always a safe
	// landing, unlike a guessed path that names no playlist.
	if (state.surface === 'detail' && state.collection?.kind === 'playlist') {
		const playlist = get(playlistList).find((item) => item.id === state.collection?.id);
		if (playlist) return playlistRoutePath(playlist.slug);
	}
	return '/';
}

export type HistoryWriteMode = 'push' | 'replace';

// The one place that decides how a library history entry reaches the browser.
//
// SvelteKit reconciles its mounted route tree only on a real navigation, so a
// raw history write is invisible to the router. That was harmless while every
// library address was `/` or `/?song=…` — always the same route. Since an open
// album addresses `/album/<slug>` (issue #269), an open song addresses one
// segment deeper, `/album/<slug>/<song>` (issue #275), and a selected take one
// segment deeper still, `/album/<slug>/<song>/take/<n>` (issue #281), a write
// can change which of the four route files (`/`, `/album/[slug]`,
// `/album/[slug]/[song]`, `/album/[slug]/[song]/take/[n]`) the address names,
// and a raw one would leave the router mounting the file it last saw while the
// address names another: the next real navigation or Back/Forward that
// disagrees tears the workspace down mid-session, with an unsaved draft still
// in it. `libraryRouteShape` names which of the four a pathname is, and a
// write that changes it goes through `goto`, which uses the same History API
// but keeps the router in step, while the frequent same-shape churn (filter,
// sort, scroll, search cursor, switching to another song within the same open
// album since #275, and switching to another take of the same open song since
// #281) keeps the cheap synchronous write.
//
// `goto` puts its own `state` option in `page.state`, not in `history.state`,
// which is where every reader of the library's restore state looks — so the
// state is written onto the entry after the navigation lands, and `goto`'s
// state option is deliberately unused.
//
// Writes are serialized because a crossing one is asynchronous: a caller that
// writes twice in a row (open a song, then pin its take) must not have its
// second write overtake the first, and must see the entry the first one is
// going to install rather than the stale one it would still read from
// `history.state` — which is what `currentLibraryHistoryState` answers.
//
// The same-shape raw write is a permanent design choice, not scaffolding a
// later cleanup should finish by routing everything through `goto`: issue
// #276 measured what a `goto` costs per write (a real SvelteKit navigation,
// its own route resolution and reactive re-run) against how often the
// same-shape case actually fires — filter/sort/search-cursor/scroll on
// nearly every interaction with the wall, a song-to-song or take-to-take
// move on every list click and Previous/Next — and going through the router
// for all of it would turn the library's most frequent writes into its most
// expensive ones for a distinction (which route *file* is mounted) that
// same-shape churn never changes. `libraryRouteShape` is what makes "does
// this write cross" a real question instead of "is this a write" — treating
// every write as a crossing would be simpler code, but wrong on the
// frequency this store actually sees; see the `LibraryRouteShape` note above
// for what a wrongly-collapsed shape does when a crossing goes undetected
// instead. Issue #265's S7 (which removed `ensureLibraryWorkspaceRoute`,
// #264's now-redundant separate guard, once this shape-based check alone was
// proven to cover everything it did) confirmed the choice rather than
// revisiting it.
export function writeLibraryHistory(
	state: LibraryHistoryState,
	url: string,
	mode: HistoryWriteMode
): Promise<void> {
	const pathname = new URL(url, window.location.origin).pathname;
	const from = plannedHistory?.pathname ?? window.location.pathname;
	const crossesRoutes = libraryRouteShape(from) !== libraryRouteShape(pathname);
	if (!crossesRoutes && queuedHistoryWrites === 0) {
		applyHistoryWrite(state, url, mode);
		return Promise.resolve();
	}
	plannedHistory = { pathname, state };
	queuedHistoryWrites += 1;
	const write = historyWrites.then(async () => {
		if (crossesRoutes) {
			// eslint-disable-next-line svelte/no-navigation-without-resolve -- static SPA with no base path, and the URL is already a resolved library address built by libraryHistoryUrl
			await goto(url, { replaceState: mode === 'replace', noScroll: true, keepFocus: true });
			applyHistoryWrite(state, url, 'replace');
			return;
		}
		applyHistoryWrite(state, url, mode);
	});
	historyWrites = write
		.catch(() => undefined)
		.finally(() => {
			queuedHistoryWrites -= 1;
			if (queuedHistoryWrites === 0) plannedHistory = null;
		});
	return write;
}

// The library history entry as it will stand once every queued write has
// landed. Every reader of the restore state goes through this instead of
// `history.state`, which lags while a crossing write navigates.
export function currentLibraryHistoryState(): unknown {
	return plannedHistory ? plannedHistory.state : history.state;
}

function applyHistoryWrite(state: LibraryHistoryState, url: string, mode: HistoryWriteMode): void {
	if (mode === 'push') history.pushState(state, '', url);
	else history.replaceState(state, '', url);
}

export type AlbumAddress = 'found' | 'unknown';

// The entry point of the /album/<slug> route (issue #269). A pasted address is
// the only thing a cold tab knows, so the slug is checked against the API
// first — an unknown one is a verdict the route states, never a silent fall
// back to the wall — and a known one becomes the library's own restore state
// and is then applied through the very path every reload and Back take, unless
// the library already shows that album. Going through applyLibraryHistory
// rather than setting the stores by hand is what keeps the album present even
// when the browse listing that loads alongside it does not carry it, and it is
// applied here rather than left to the live stream's snapshot load because the
// two start independently: whichever runs second re-applies the same state, so
// the address wins either way.
//
// An existing restore state that already opens this album is richer than the
// address (it carries sort, scroll and offsets) and wins; the address only
// overrules a state that disagrees with it.
//
// The write goes through writeLibraryHistory like every other one, so that a
// write which changes the route pattern reaches the router instead of only the
// address bar — see the note there before turning any of these back into a
// bare history.replaceState.
export async function openAlbumAddress(albumId: string): Promise<AlbumAddress> {
	if (!(await albumIsKnown(albumId))) return 'unknown';
	const opened = historyAlreadyOpens(albumId);
	const state = opened
		? (currentLibraryHistoryState() as LibraryHistoryState)
		: albumAddressState(albumId);
	if (!opened) {
		await writeLibraryHistory(state, albumRoutePath(albumId), 'replace');
	}
	if (!albumAlreadyShown(albumId)) await applyLibraryHistory(state);
	return 'found';
}

// Both short circuits keep the address from re-asking what the library has
// already answered, which is what the in-app route to this album -- the wall,
// which loaded the album list and then opened the album before the address
// changed -- always has. A cold tab has neither and pays for both.
async function albumIsKnown(albumId: string): Promise<boolean> {
	if (get(albumList).some((album) => album.id === albumId)) return true;
	return albumExists(albumId);
}

function albumAlreadyShown(albumId: string): boolean {
	const collection = get(openCollection);
	return (
		get(librarySurface) === 'detail' && collection?.kind === 'album' && collection.id === albumId
	);
}

function historyAlreadyOpens(albumId: string): boolean {
	const state = currentLibraryHistoryState();
	return (
		isLibraryHistoryState(state) &&
		state.surface === 'detail' &&
		state.collection?.kind === 'album' &&
		state.collection.id === albumId
	);
}

function albumAddressState(albumId: string): LibraryHistoryState {
	return {
		...libraryRootState(),
		surface: 'detail',
		collection: { kind: 'album', id: albumId }
	};
}

async function albumExists(albumId: string): Promise<boolean> {
	try {
		await fetchAlbum(albumId);
		return true;
	} catch (err) {
		if (isNotFound(err)) return false;
		throw err;
	}
}

export type SongAddress = 'found' | 'unknown-song' | 'unknown-album';

// The entry point of the /album/<slug>/<song-slug> route (issue #275), one
// level under openAlbumAddress above -- same shape, same reasoning: an
// unknown album or an unknown song within a known one is a verdict the route
// states, never a silent fall back. The album and the song-in-album lookups
// run concurrently rather than the album gating the song fetch: a scoped
// `/api/songs?album_id=` for an album that turns out not to exist costs one
// wasted round trip, cheaper than the extra latency of running them in
// series on the one path with nothing cached yet -- a cold tab.
//
// `generationId` is the take query appendage (`?gen=…`), read from the
// address the same way the legacy `/?song=&gen=` entry point already reads
// it -- a cold paste of a song address that names a take must not silently
// drop it. It only seeds a fresh open; an address that already opens this
// song keeps whatever take the session already has selected.
export async function openSongAddress(
	albumId: string,
	songSlug: string,
	generationId: string | null = null
): Promise<SongAddress> {
	const [albumKnown, song] = await Promise.all([
		albumIsKnown(albumId),
		resolveSongInAlbum(albumId, songSlug)
	]);
	if (!albumKnown) return 'unknown-album';
	if (!song) return 'unknown-song';
	const opened = historyAlreadyOpensSong(song.id);
	const state = opened
		? (currentLibraryHistoryState() as LibraryHistoryState)
		: songAddressState(song, generationId);
	if (!opened) {
		await writeLibraryHistory(state, songRoutePath(albumId, songSlug), 'replace');
	}
	if (!songAlreadyShown(song.id)) await applyLibraryHistory(state);
	return 'found';
}

export type TakeAddress = 'found' | 'unknown-take' | 'unknown-song' | 'unknown-album';

// The entry point of the /album/<slug>/<song-slug>/take/<n> route (issue
// #281), one level under openSongAddress above -- same shape again: an
// unknown album, unknown song, or unknown take within a known song is a
// verdict the route states, never a silent fall back (and, per the issue's
// contract, an unknown take routes the person back to the song, not the
// album or the root -- that is the caller's job, this only reports it).
//
// `takeNumber` is generation_number, the number the surface already shows the
// person, not the generation's uuid -- resolving it needs every one of the
// song's takes loaded, not just whatever the album/song listing carried
// along (the same partial-retain gap ensureGenerationsLoaded already guards
// for player.ts's own callers), so this ensures that before it looks for the
// number.
export async function openTakeAddress(
	albumId: string,
	songSlug: string,
	takeNumber: number
): Promise<TakeAddress> {
	const [albumKnown, song] = await Promise.all([
		albumIsKnown(albumId),
		resolveSongInAlbum(albumId, songSlug)
	]);
	if (!albumKnown) return 'unknown-album';
	if (!song) return 'unknown-song';
	await ensureGenerationsLoaded(song.id);
	const loadedSong = get(songList).find((item) => item.id === song.id) ?? song;
	const generation = loadedSong.generations.find((item) => item.generation_number === takeNumber);
	if (!generation) return 'unknown-take';
	const opened = historyAlreadyOpensTake(song.id, generation.id);
	const state = opened
		? (currentLibraryHistoryState() as LibraryHistoryState)
		: songAddressState(song, generation.id);
	if (!opened) {
		await writeLibraryHistory(state, takeRoutePath(albumId, songSlug, takeNumber), 'replace');
	}
	if (!takeAlreadyShown(song.id, generation.id)) await applyLibraryHistory(state);
	return 'found';
}

export type PlaylistAddress = 'found' | 'unknown';

// The entry point of the /playlist/<slug> route (issue #286), the last new
// address of the chain -- same shape as openAlbumAddress: an unknown slug is
// a verdict the route states, never a silent fall back. A playlist has no
// album to nest inside, so unlike openSongAddress there is only the one
// resolution, not two run concurrently.
export async function openPlaylistAddress(slug: string): Promise<PlaylistAddress> {
	const playlist = await resolvePlaylistBySlug(slug);
	if (!playlist) return 'unknown';
	const opened = historyAlreadyOpensPlaylist(playlist.id);
	const state = opened
		? (currentLibraryHistoryState() as LibraryHistoryState)
		: playlistAddressState(playlist.id);
	if (!opened) {
		await writeLibraryHistory(state, playlistRoutePath(slug), 'replace');
	}
	if (!playlistAlreadyShown(playlist.id)) await applyLibraryHistory(state);
	return 'found';
}

// Checks the already-loaded playlists first -- the in-app route to a
// playlist (a Rail row, a shares-inventory link) already has the list
// loaded. A cold tab has neither and pays for the fetch: playlists have no
// pagination (unlike fetchSongBySlug's paged album scan), so the one list
// call either finds the slug or the address is unknown. Found is upserted
// into playlistList the same way resolveSongInAlbum upserts a slug-based
// song hit, so libraryHistoryUrl's own by-id lookup finds it without a
// second fetch.
async function resolvePlaylistBySlug(slug: string): Promise<PlaylistItem | null> {
	const known = get(playlistList).find((item) => item.slug === slug);
	if (known) return known;
	const items = await fetchPlaylists();
	const found = items.find((item) => item.slug === slug) ?? null;
	if (found) {
		playlistList.update((list) =>
			list.some((item) => item.id === found.id)
				? list.map((item) => (item.id === found.id ? found : item))
				: [...list, found]
		);
	}
	return found;
}

function playlistAlreadyShown(playlistId: string): boolean {
	const collection = get(openCollection);
	return (
		get(librarySurface) === 'detail' &&
		collection?.kind === 'playlist' &&
		collection.id === playlistId
	);
}

function historyAlreadyOpensPlaylist(playlistId: string): boolean {
	const state = currentLibraryHistoryState();
	return (
		isLibraryHistoryState(state) &&
		state.surface === 'detail' &&
		state.collection?.kind === 'playlist' &&
		state.collection.id === playlistId
	);
}

function playlistAddressState(playlistId: string): LibraryHistoryState {
	return {
		...libraryRootState(),
		surface: 'detail',
		collection: { kind: 'playlist', id: playlistId }
	};
}

export type LegacySongQueryAddress =
	{ kind: 'found'; path: string; droppedUnknownTake: boolean } | { kind: 'unknown-song' };

// The legacy `/?song=<uuid>` and `/?song=<uuid>&gen=<uuid>` entry points
// (issue #284): a bookmark or a link shared before S3/S4 (#275/#281) gave the
// library its own song and take addresses still carries only ids, not the
// slug/number those canonical addresses name a song or take by. fetchSong
// resolves both in the one call it already needs for its own id -- it
// returns the full generation list (see ensureGenerationsLoaded's own
// assumption of that), so no separate takes fetch is needed to find a
// requested generation's number -- and the song is upserted into songList
// the same way resolveSongInAlbum already does for a slug-based hit, so the
// canonical route's own resolution that (library)/+page.svelte hands the
// redirect to (openSongAddress / openTakeAddress) finds it there instead of
// fetching it again.
//
// This only resolves the address; it does not write history or apply it --
// (library)/+page.svelte's own `goto` does that by landing on the resolved
// path itself, the same route-file crossing writeLibraryHistory already
// carries a direct hit on that path through, replacing the query form in
// place rather than pushing a new entry over it. An unknown song id is the
// same honest verdict an unknown slug already gets; an unknown generation id
// on an otherwise known song is not -- the song still exists -- so it is
// dropped rather than reported, landing on the song's own address instead of
// a 404 for a page that is there -- but silently, per the operator's own
// standard, would hide a fact the surface knows: `droppedUnknownTake` tells
// the caller a take was requested and not found, so it can say so (a toast,
// after the redirect lands -- see (library)/+page.svelte).
export async function resolveLegacySongQueryAddress(
	songId: string,
	generationId: string | null
): Promise<LegacySongQueryAddress> {
	let resolvedSong: SongItem;
	try {
		resolvedSong = await fetchSong(songId);
	} catch (err) {
		if (isNotFound(err)) return { kind: 'unknown-song' };
		throw err;
	}
	upsertSongInList(resolvedSong);
	const takeNumber = generationId
		? resolvedSong.generations.find((generation) => generation.id === generationId)
				?.generation_number
		: undefined;
	const path =
		takeNumber !== undefined
			? takeRoutePath(resolvedSong.album_id, resolvedSong.slug, takeNumber)
			: songRoutePath(resolvedSong.album_id, resolvedSong.slug);
	return {
		kind: 'found',
		path,
		droppedUnknownTake: generationId !== null && takeNumber === undefined
	};
}

// Checks the already-loaded songs of this album first -- the in-app route to
// a song (a track click from an open album, a rail row) always has them. A
// cold tab has neither and pays for the fetch: a direct one, not
// loadSongsForAlbum, whose fetch the live stream's own first snapshot can
// cancel out from under it. A cold tab starts both at once (this resolution
// and the stream's own bootstrap, which calls cancelAlbumSongLoads as part
// of beginning its epoch) and loadSongsForAlbum silently drops a cancelled
// fetch's results instead of failing it, which read as an honest
// "unknown-song" verdict for a song that plainly exists -- discovered the
// hard way against a real stack (#275), not caught by jsdom, which has no
// live stream to race. Once found, the song is upserted into songList the
// same way a song opened directly from a search hit or a share link already
// is, so applyLibraryHistory's own loadSongsForAlbum call for the rest of the
// album does not have to carry it too.
async function resolveSongInAlbum(albumId: string, slug: string): Promise<SongItem | null> {
	const known = get(songList).find((song) => song.album_id === albumId && song.slug === slug);
	if (known) return known;
	const song = await fetchSongBySlug(albumId, slug);
	if (song) upsertSongInList(song);
	return song;
}

async function fetchSongBySlug(albumId: string, slug: string): Promise<SongItem | null> {
	let offset = 0;
	for (;;) {
		const page = await fetchSongs(albumId, offset, LIBRARY_SONG_PAGE_SIZE);
		const found = page.items.find((song) => song.slug === slug);
		if (found) return found;
		offset += page.items.length;
		if (!page.has_more || page.items.length === 0) return null;
	}
}

function songAlreadyShown(songId: string): boolean {
	return get(selectedSongId) === songId && get(librarySurface) === 'detail';
}

function historyAlreadyOpensSong(songId: string): boolean {
	const state = currentLibraryHistoryState();
	return isLibraryHistoryState(state) && state.songId === songId;
}

function takeAlreadyShown(songId: string, generationId: string): boolean {
	return songAlreadyShown(songId) && get(selectedGenerationId) === generationId;
}

function historyAlreadyOpensTake(songId: string, generationId: string): boolean {
	const state = currentLibraryHistoryState();
	return (
		isLibraryHistoryState(state) && state.songId === songId && state.generationId === generationId
	);
}

function songAddressState(song: SongItem, generationId: string | null): LibraryHistoryState {
	const base = libraryRootState();
	return {
		...base,
		surface: 'detail',
		collection: { kind: 'album', id: song.album_id },
		songId: song.id,
		generationId,
		detailTab: generationId ? 'takes' : base.detailTab
	};
}

export function snapshotLibraryHistory(index: number): LibraryHistoryState {
	const browse = get(libraryBrowse);
	const search = get(librarySearch);
	const query = get(searchQuery);
	const searchMatchesQuery = search.q === query.trim();
	return {
		kind: LIBRARY_HISTORY_KIND,
		index,
		surface: get(librarySurface),
		query,
		sort: get(librarySort),
		albumOffset: browse.albumOffset,
		songOffset: browse.songOffset,
		searchCursor: searchMatchesQuery ? search.nextCursor : null,
		searchLoadedCount: searchMatchesQuery ? search.items.length : 0,
		collection: get(openCollection),
		songId: get(selectedSongId),
		generationId: get(selectedGenerationId),
		scrollAnchor: get(libraryScrollAnchor),
		detailTab: get(detailTab)
	};
}

export async function applyLibraryHistory(state: LibraryHistoryState): Promise<boolean> {
	const generation = ++historyApplyGeneration;
	librarySurface.set(state.surface);
	librarySort.set(state.sort);
	searchQuery.set(state.query);
	detailTab.set(normalizeDetailTab(state.detailTab));
	libraryScrollAnchor.set(state.scrollAnchor);
	selectedSongId.set(state.songId);
	selectedGenerationId.set(state.generationId);
	await hydrateCollection(state.collection);
	if (generation !== historyApplyGeneration) return false;
	await restoreLibraryBrowse(state.sort, state.albumOffset, state.songOffset);
	if (generation !== historyApplyGeneration) return false;
	if (state.query.trim()) {
		await restoreLibrarySearch(state.query, state.sort, state.searchLoadedCount);
	}
	if (generation !== historyApplyGeneration) return false;
	await hydrateSelectedResources(state, generation);
	if (generation !== historyApplyGeneration) return false;
	if (state.collection?.kind === 'album') {
		await loadSongsForAlbum(state.collection.id);
	}
	if (generation !== historyApplyGeneration) return false;
	fallbackBrowseIfDetailGone(state.surface);
	return true;
}

export function cancelLibraryHistoryApply(): void {
	historyApplyGeneration += 1;
}

async function hydrateCollection(collection: CollectionSnapshot): Promise<void> {
	if (collection?.kind === 'playlist') {
		// loadPlaylistDetail owns the not-found policy (closes the collection
		// on a 404) and never rejects, so there is nothing left to catch here.
		await loadPlaylistDetail(collection.id);
		return;
	}
	deselectPlaylist();
	setOpenCollection(collection ?? null);
}

async function hydrateSelectedResources(
	state: LibraryHistoryState,
	generation: number
): Promise<void> {
	await hydrateMissingCollectionAlbum(state.collection, generation);
	if (state.songId) await hydrateSelectedSong(state.songId, generation);
}

async function hydrateMissingCollectionAlbum(
	collection: CollectionSnapshot,
	generation: number
): Promise<void> {
	if (collection?.kind !== 'album') return;
	if (get(albumList).some((album) => album.id === collection.id)) return;
	try {
		const album = await fetchAlbum(collection.id);
		if (generation !== historyApplyGeneration) return;
		albumList.update((list) => upsertReplace(list, album));
	} catch (err) {
		if (generation !== historyApplyGeneration) return;
		if (isNotFound(err)) setOpenCollection(null);
	}
}

async function hydrateSelectedSong(songId: string, generation: number): Promise<void> {
	const listed = get(songList).find((song) => song.id === songId);
	if (listed && listed.generations.length >= listed.generation_count) {
		await hydrateSongAlbum(listed.album_id, generation);
		return;
	}
	try {
		const song = await fetchSong(songId);
		if (generation !== historyApplyGeneration) return;
		songList.update((list) => upsertReplace(list, song));
		await hydrateSongAlbum(song.album_id, generation);
	} catch (err) {
		if (generation !== historyApplyGeneration) return;
		if (isNotFound(err)) {
			selectedSongId.set(null);
			selectedGenerationId.set(null);
		}
	}
}

async function hydrateSongAlbum(albumId: string, generation: number): Promise<void> {
	if (get(albumList).some((album) => album.id === albumId)) return;
	try {
		const album = await fetchAlbum(albumId);
		if (generation !== historyApplyGeneration) return;
		albumList.update((list) => upsertReplace(list, album));
	} catch (err) {
		if (generation !== historyApplyGeneration) return;
		if (isNotFound(err)) return;
	}
}

function fallbackBrowseIfDetailGone(intendedSurface: LibrarySurface): void {
	if (intendedSurface !== 'detail') return;
	if (get(openCollection) !== null) return;
	if (get(selectedSongId) !== null) return;
	librarySurface.set('browse');
}

// A cold tab's `history.state` is SvelteKit's own bookkeeping object, not yet
// a LibraryHistoryState, until whichever restores first writes one — the
// live stream's own bootstrap (this function, called as its loadSnapshot) and
// an address route's resolution (openAlbumAddress / openSongAddress /
// openTakeAddress) both start independently and may finish in either order.
// The fallback branch below must therefore tolerate its own
// `restoreLibraryBrowse` losing that race exactly the way the branch above
// already does for `applyLibraryHistory`: a loss only means a newer restore
// (the address) applied instead, which is not a bootstrap failure, so success
// is read off `libraryBrowse`'s own final status rather than off the
// superseded call's return value — discovered against a real stack (issue
// #281's take address, whose extra generations fetch before it reaches
// `applyLibraryHistory` reliably loses this race; the same race exists for
// every address, just usually won).
export async function hydrateLibraryFromHistory(): Promise<boolean> {
	const existing = currentLibraryHistoryState();
	if (isLibraryHistoryState(existing)) {
		const applied = await applyLibraryHistory(existing);
		if (applied) {
			const restored = snapshotLibraryHistory(existing.index);
			await writeLibraryHistory(restored, libraryHistoryUrl(restored), 'replace');
		}
		if (existing.query.trim()) return get(librarySearch).status !== 'error';
		return get(libraryBrowse).status !== 'error';
	}
	await restoreLibraryBrowse(get(librarySort), 0, 0);
	return get(libraryBrowse).status !== 'error';
}

export function setLibrarySurface(surface: LibrarySurface): void {
	librarySurface.set(surface);
}

export function captureLibraryScroll(scrollTop: number): void {
	libraryScrollAnchor.set(scrollTop);
}

export function albumIsExpanded(options: { searching: boolean; songHits: number }): boolean {
	return options.searching && options.songHits > 0;
}

export function resetLibraryContextForTests(): void {
	historyApplyGeneration += 1;
	historyWrites = Promise.resolve();
	queuedHistoryWrites = 0;
	plannedHistory = null;
	librarySurface.set('browse');
	detailTab.set(DEFAULT_DETAIL_TAB);
	libraryScrollAnchor.set(0);
	setOpenCollection(null);
}

function isLibrarySurface(value: unknown): value is LibrarySurface {
	return typeof value === 'string' && SURFACES.has(value as LibrarySurface);
}

function isDetailTab(value: unknown): value is DetailTab {
	return typeof value === 'string' && DETAIL_TABS.has(value as DetailTab);
}

function isDetailTabToken(value: unknown): boolean {
	return typeof value === 'string' && (isDetailTab(value) || value in LEGACY_DETAIL_TAB_MAP);
}

function normalizeDetailTab(value: unknown): DetailTab {
	if (isDetailTab(value)) return value;
	if (typeof value === 'string' && value in LEGACY_DETAIL_TAB_MAP) {
		return LEGACY_DETAIL_TAB_MAP[value];
	}
	return DEFAULT_DETAIL_TAB;
}

function isIdOrNull(value: unknown): value is string | null {
	return value === null || typeof value === 'string';
}

function isCollectionSnapshot(value: unknown): value is CollectionSnapshot {
	if (value === null) return true;
	if (typeof value !== 'object') return false;
	const collection = value as Record<string, unknown>;
	return (
		(collection.kind === 'album' || collection.kind === 'playlist') &&
		typeof collection.id === 'string'
	);
}

function upsertReplace<T extends { id: string }>(items: T[], item: T): T[] {
	const index = items.findIndex((existing) => existing.id === item.id);
	if (index === -1) return [...items, item];
	return items.map((existing, i) => (i === index ? item : existing));
}
