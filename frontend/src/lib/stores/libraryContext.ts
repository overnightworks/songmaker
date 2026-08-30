import { get, writable } from 'svelte/store';
import { goto } from '$app/navigation';
import { fetchAlbum } from '$lib/api/albums';
import { isNotFound } from '$lib/api/fetch';
import type { LibrarySort } from '$lib/api/library';
import { fetchSong } from '$lib/api/songs';
import { LIBRARY_DEFAULT_FILTER, LIBRARY_HISTORY_KIND, type LibraryFilter } from '$lib/constants';
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
import { albumList, loadSongsForAlbum, songList } from '$lib/stores/libraryData';
import { selectedGenerationId, selectedSongId } from '$lib/stores/player';
import { deselectPlaylist, ensurePlaylistsLoaded, loadPlaylistDetail } from '$lib/stores/playlists';
import { CREATED_SORTS } from '$lib/utils/recency';

// 'browse' shows the library wall (the LibraryWall component); 'detail' shows
// whichever collection is currently open; 'create' shows the create form.
// Song detail always wins over all three (see routes/+page.svelte).
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

export function libraryHistoryUrl(state: LibraryHistoryState): string {
	if (state.songId && state.generationId) return `/?song=${state.songId}&gen=${state.generationId}`;
	if (state.songId) return `/?song=${state.songId}`;
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
// album addresses `/album/<slug>` (issue #269) a write can change the route
// pattern, and a raw one would leave the router mounting the route it last
// saw while the address names another: the next real navigation or
// Back/Forward that disagrees tears the workspace down mid-session, with an
// unsaved draft still in it. So a write that crosses the boundary goes through
// `goto`, which uses the same History API but keeps the router in step, while
// the frequent same-route churn (filter, sort, scroll, search cursor) keeps
// the cheap synchronous write.
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
	const crossesRoutes = isAlbumRoutePath(from) !== isAlbumRoutePath(pathname);
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
	return restoreLibraryBrowse(get(librarySort), 0, 0);
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
