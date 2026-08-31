import { get, writable } from 'svelte/store';
import { goto } from '$app/navigation';
import { fetchAlbum } from '$lib/api/albums';
import { isNotFound } from '$lib/api/fetch';
import type { LibrarySort } from '$lib/api/library';
import { fetchSong, fetchSongs } from '$lib/api/songs';
import type { SongItem } from '$lib/api/types';
import {
	LIBRARY_DEFAULT_FILTER,
	LIBRARY_HISTORY_KIND,
	LIBRARY_SONG_PAGE_SIZE,
	type LibraryFilter
} from '$lib/constants';
import { type OpenCollection, openCollection, setOpenCollection } from '$lib/stores/collection';
import { closeSharesInventory, openSharesInventory } from '$lib/stores/shares';
import { searchQuery } from '$lib/stores/filter';
import {
	libraryBrowse,
	librarySearch,
	librarySort,
	restoreLibraryBrowse,
	restoreLibrarySearch,
	syncLibrarySearch
} from '$lib/stores/librarySearch';
import { albumList, loadSongsForAlbum, songList, upsertSongInList } from '$lib/stores/libraryData';
import { ensureGenerationsLoaded, selectedGenerationId, selectedSongId } from '$lib/stores/player';
import { deselectPlaylist, ensurePlaylistsLoaded, loadPlaylistDetail } from '$lib/stores/playlists';
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
	filter: LibraryFilter;
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

export const libraryFilter = writable<LibraryFilter>(LIBRARY_DEFAULT_FILTER);
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
const FILTERS: ReadonlySet<string> = new Set(['albums', 'playlists', 'shared']);

const SORTS: ReadonlySet<string> = new Set(CREATED_SORTS);

const ALBUM_ROUTE_PREFIX = '/album/';
const TAKE_ROUTE_SEGMENT = '/take/';

let historyApplyGeneration = 0;
let historyWrites: Promise<void> = Promise.resolve();
let queuedHistoryWrites = 0;
let plannedHistory: { pathname: string; state: LibraryHistoryState } | null = null;

export function isLibraryFilter(value: unknown): value is LibraryFilter {
	return typeof value === 'string' && FILTERS.has(value);
}

export function isLibrarySort(value: unknown): value is LibrarySort {
	return typeof value === 'string' && SORTS.has(value);
}

export function isLibraryHistoryState(value: unknown): value is LibraryHistoryState {
	if (typeof value !== 'object' || value === null) return false;
	const state = value as Record<string, unknown>;
	if (state.kind !== LIBRARY_HISTORY_KIND) return false;
	if (typeof state.index !== 'number' || !Number.isInteger(state.index) || state.index < 0) {
		return false;
	}
	if (!isLibraryFilter(state.filter)) return false;
	if (!isLibrarySurface(state.surface)) return false;
	if (typeof state.query !== 'string') return false;
	if (!isLibrarySort(state.sort)) return false;
	if (typeof state.albumOffset !== 'number' || typeof state.songOffset !== 'number') return false;
	if (typeof state.searchLoadedCount !== 'number' || state.searchLoadedCount < 0) return false;
	if (typeof state.scrollAnchor !== 'number') return false;
	if (!isIdOrNull(state.searchCursor)) return false;
	if (!isCollectionSnapshot(state.collection)) return false;
	if (!isIdOrNull(state.songId)) return false;
	if (!isIdOrNull(state.generationId)) return false;
	if (state.detailTab !== undefined && !isDetailTabToken(state.detailTab)) return false;
	return true;
}

export function libraryRootState(): LibraryHistoryState {
	return {
		kind: LIBRARY_HISTORY_KIND,
		index: 0,
		filter: LIBRARY_DEFAULT_FILTER,
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

export function albumRoutePath(albumId: string): string {
	return `${ALBUM_ROUTE_PREFIX}${encodeURIComponent(albumId)}`;
}

export function isAlbumRoutePath(pathname: string): boolean {
	return pathname.startsWith(ALBUM_ROUTE_PREFIX) && pathname.length > ALBUM_ROUTE_PREFIX.length;
}

// A song's own address (issue #275), one segment under its album's. The song
// is named by its slug, not its id — matching how the album segment already
// names the album by slug rather than a surrogate key.
export function songRoutePath(albumId: string, songSlug: string): string {
	return `${albumRoutePath(albumId)}/${encodeURIComponent(songSlug)}`;
}

// A take's own address (issue #281), one segment under its song's own. <n>
// is generation_number, not the generation's uuid -- see isTakeRoutePath.
export function takeRoutePath(albumId: string, songSlug: string, takeNumber: number): string {
	return `${songRoutePath(albumId, songSlug)}${TAKE_ROUTE_SEGMENT}${takeNumber}`;
}

export function isSongRoutePath(pathname: string): boolean {
	if (!isAlbumRoutePath(pathname)) return false;
	const rest = pathname.slice(ALBUM_ROUTE_PREFIX.length);
	const slashIndex = rest.indexOf('/');
	return slashIndex !== -1 && rest.length > slashIndex + 1;
}

// A take's own address (issue #281), one segment under its song's. <n> is
// generation_number -- the number the surface already shows the person
// ("Take 3"), not the generation's uuid, matching how the album and song
// segments already name their resource by the key a person recognizes rather
// than a surrogate one. isSongRoutePath is also true for a take address (it
// only asks "is there a second segment"), so this only narrows further; it
// never needs to be checked on its own.
export function isTakeRoutePath(pathname: string): boolean {
	if (!isSongRoutePath(pathname)) return false;
	const takeIndex = pathname.indexOf(TAKE_ROUTE_SEGMENT);
	return takeIndex !== -1 && pathname.length > takeIndex + TAKE_ROUTE_SEGMENT.length;
}

// The four shapes a library address can take. Distinct from the
// isAlbumRoutePath boolean below, which answers "is this under /album/" for
// isLibraryWorkspacePath — that boolean is deliberately true for 'album',
// 'album-song' and 'album-song-take' alike, since all three mount the
// workspace. This finer distinction is what writeLibraryHistory needs: it
// must treat album <-> album-song and album-song <-> album-song-take as route
// crossings too, not just root <-> album, or a track (or a take within it)
// opened from a shallower address would leave the router still believing it
// is on the shallower route file while the bar reads one segment deeper --
// see the note on writeLibraryHistory for what a stale router does on the
// next Back/Forward. A take opened from another take in the same song stays
// 'album-song-take' on both sides, so that move is the frequent-churn case,
// not a crossing -- it is still the same route file, /take/[n], with only the
// param changed.
type LibraryRouteShape = 'root' | 'album' | 'album-song' | 'album-song-take';

function libraryRouteShape(pathname: string): LibraryRouteShape {
	if (!isAlbumRoutePath(pathname)) return 'root';
	if (!isSongRoutePath(pathname)) return 'album';
	return isTakeRoutePath(pathname) ? 'album-song-take' : 'album-song';
}

// An open song's own address once its slug is known (issue #275). A selected
// take addresses onto its own path one segment deeper (issue #281), by its
// generation_number rather than its uuid -- but only once that take is among
// the song's loaded generations; a take selected before its number is known
// (the legacy `?gen=<uuid>` entry point, still only read, or a song whose
// generations have not loaded yet) keeps writing the query appendage until it
// is. A song not yet hydrated into songList (the legacy `?song=` entry point)
// keeps writing that older form for the same reason -- migrating live
// `?song=`/`?gen=` addresses to the new ones is S6, not this slice.
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
				: `${path}?gen=${state.generationId}`;
		}
		return state.generationId
			? `/?song=${state.songId}&gen=${state.generationId}`
			: `/?song=${state.songId}`;
	}
	if (state.surface === 'detail' && state.collection?.kind === 'album') {
		return albumRoutePath(state.collection.id);
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
		filter: get(libraryFilter),
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
	if (state.filter === 'shared') openSharesInventory();
	else closeSharesInventory();
	libraryFilter.set(state.filter);
	if (state.filter === 'playlists') syncLibrarySearch('');
	librarySurface.set(state.surface);
	librarySort.set(state.sort);
	searchQuery.set(state.query);
	detailTab.set(normalizeDetailTab(state.detailTab));
	libraryScrollAnchor.set(state.scrollAnchor);
	selectedSongId.set(state.songId);
	selectedGenerationId.set(state.generationId);
	await hydrateCollection(state.collection);
	if (generation !== historyApplyGeneration) return false;
	if (state.filter === 'playlists') {
		void ensurePlaylistsLoaded();
	}
	await restoreLibraryBrowse(state.sort, state.albumOffset, state.songOffset);
	if (generation !== historyApplyGeneration) return false;
	if (state.query.trim() && state.filter !== 'playlists') {
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
	if (
		state.collection?.kind === 'album' &&
		!get(albumList).some((album) => album.id === state.collection?.id)
	) {
		try {
			const album = await fetchAlbum(state.collection.id);
			if (generation !== historyApplyGeneration) return;
			albumList.update((list) => upsertReplace(list, album));
		} catch (err) {
			if (generation !== historyApplyGeneration) return;
			if (isNotFound(err)) setOpenCollection(null);
		}
	}
	if (!state.songId) return;
	const listed = get(songList).find((song) => song.id === state.songId);
	if (listed && listed.generations.length >= listed.generation_count) {
		await hydrateSongAlbum(listed.album_id, generation);
		return;
	}
	try {
		const song = await fetchSong(state.songId);
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

const EMPTY_FILTER_SCROLL: Record<LibraryFilter, number> = {
	albums: 0,
	playlists: 0,
	shared: 0
};

export const libraryScrollByFilter = writable<Record<LibraryFilter, number>>({
	...EMPTY_FILTER_SCROLL
});

function rememberLibraryScroll(filter: LibraryFilter): void {
	libraryScrollByFilter.update((anchors) => ({
		...anchors,
		[filter]: get(libraryScrollAnchor)
	}));
}

function restoreLibraryScroll(filter: LibraryFilter): void {
	libraryScrollAnchor.set(get(libraryScrollByFilter)[filter] ?? 0);
}

export function setLibraryFilter(filter: LibraryFilter): LibraryHistoryState {
	const previous = get(libraryFilter);
	const index = libraryHistoryIndex();
	if (previous === filter) {
		return snapshotLibraryHistory(index);
	}
	rememberLibraryScroll(previous);
	if (filter === 'shared') openSharesInventory();
	else closeSharesInventory();
	libraryFilter.set(filter);
	restoreLibraryScroll(filter);
	if (filter === 'playlists') void ensurePlaylistsLoaded();
	return snapshotLibraryHistory(index);
}

export function setLibrarySurface(surface: LibrarySurface): void {
	librarySurface.set(surface);
}

export function captureLibraryScroll(scrollTop: number): void {
	libraryScrollAnchor.set(scrollTop);
	rememberLibraryScroll(get(libraryFilter));
}

export function albumIsExpanded(options: { searching: boolean; songHits: number }): boolean {
	return options.searching && options.songHits > 0;
}

export function resetLibraryContextForTests(): void {
	historyApplyGeneration += 1;
	historyWrites = Promise.resolve();
	queuedHistoryWrites = 0;
	plannedHistory = null;
	libraryFilter.set(LIBRARY_DEFAULT_FILTER);
	librarySurface.set('browse');
	detailTab.set(DEFAULT_DETAIL_TAB);
	libraryScrollAnchor.set(0);
	libraryScrollByFilter.set({ ...EMPTY_FILTER_SCROLL });
	setOpenCollection(null);
}

function libraryHistoryIndex(): number {
	const state = currentLibraryHistoryState();
	return isLibraryHistoryState(state) ? state.index : 0;
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
