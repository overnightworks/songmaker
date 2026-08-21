import { get, writable } from 'svelte/store';
import { fetchAlbum } from '$lib/api/albums';
import { ApiError } from '$lib/api/fetch';
import type { LibrarySort } from '$lib/api/library';
import { fetchSong } from '$lib/api/songs';
import {
	LIBRARY_DEFAULT_SECTION,
	LIBRARY_HISTORY_KIND,
	LIBRARY_SECTIONS,
	LIBRARY_SHARES_HISTORY_SECTION,
	type LibraryHistorySection,
	type LibrarySection
} from '$lib/constants';
import { closeSharesInventory, openSharesInventory, sharesViewOpen } from '$lib/stores/shares';
import { searchQuery } from '$lib/stores/filter';
import {
	libraryBrowse,
	librarySearch,
	librarySort,
	restoreLibraryBrowse,
	restoreLibrarySearch,
	syncLibrarySearch
} from '$lib/stores/librarySearch';
import {
	albumList,
	loadSongsForAlbum,
	selectedAlbumId,
	selectedGenerationId,
	selectedSongId,
	songList
} from '$lib/stores/player';
import {
	deselectPlaylist,
	ensurePlaylistsLoaded,
	loadPlaylistDetail,
	selectedPlaylistDetail,
	selectedPlaylistId
} from '$lib/stores/playlists';
import { CREATED_SORTS } from '$lib/utils/recency';

export type LibrarySurface = 'browse' | 'detail' | 'create';
export type DetailTab = 'generations' | 'edit' | 'chat';

export interface LibraryHistoryState {
	kind: typeof LIBRARY_HISTORY_KIND;
	index: number;
	section: LibraryHistorySection;
	surface: LibrarySurface;
	query: string;
	sort: LibrarySort;
	albumOffset: number;
	songOffset: number;
	searchCursor: string | null;
	searchLoadedCount: number;
	albumId: string | null;
	songId: string | null;
	generationId: string | null;
	playlistId: string | null;
	expandedAlbumIds: string[];
	scrollAnchor: number;
	detailTab?: DetailTab;
}

export const librarySection = writable<LibrarySection>(LIBRARY_DEFAULT_SECTION);
export const librarySurface = writable<LibrarySurface>('browse');
export const detailTab = writable<DetailTab>('generations');
export const expandedAlbumIds = writable<ReadonlySet<string>>(new Set());
export const libraryScrollAnchor = writable(0);

const SURFACES: ReadonlySet<LibrarySurface> = new Set(['browse', 'detail', 'create']);
const DETAIL_TABS: ReadonlySet<DetailTab> = new Set(['generations', 'edit', 'chat']);

const SORTS: ReadonlySet<string> = new Set(CREATED_SORTS);

let historyApplyGeneration = 0;

const EMPTY_MODE_BAGS: Record<LibrarySection, LibraryHistoryState | null> = {
	albums: null,
	playlists: null
};

let modeBags: Record<LibrarySection, LibraryHistoryState | null> = { ...EMPTY_MODE_BAGS };

export function isLibrarySection(value: unknown): value is LibrarySection {
	return LIBRARY_SECTIONS.some((section) => section === value);
}

export function isLibraryHistorySection(value: unknown): value is LibraryHistorySection {
	return isLibrarySection(value) || value === LIBRARY_SHARES_HISTORY_SECTION;
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
	if (!isLibraryHistorySection(state.section)) return false;
	if (!isLibrarySurface(state.surface)) return false;
	if (typeof state.query !== 'string') return false;
	if (!isLibrarySort(state.sort)) return false;
	if (typeof state.albumOffset !== 'number' || typeof state.songOffset !== 'number') return false;
	if (typeof state.searchLoadedCount !== 'number' || state.searchLoadedCount < 0) return false;
	if (typeof state.scrollAnchor !== 'number') return false;
	if (!isIdOrNull(state.searchCursor)) return false;
	if (!isIdOrNull(state.albumId)) return false;
	if (!isIdOrNull(state.songId)) return false;
	if (!isIdOrNull(state.generationId)) return false;
	if (!isIdOrNull(state.playlistId)) return false;
	if (!Array.isArray(state.expandedAlbumIds)) return false;
	if (!state.expandedAlbumIds.every((id) => typeof id === 'string')) return false;
	if (state.detailTab !== undefined && !isDetailTab(state.detailTab)) return false;
	return true;
}

export function libraryRootState(): LibraryHistoryState {
	return {
		kind: LIBRARY_HISTORY_KIND,
		index: 0,
		section: LIBRARY_DEFAULT_SECTION,
		surface: 'browse',
		query: '',
		sort: 'newest',
		albumOffset: 0,
		songOffset: 0,
		searchCursor: null,
		searchLoadedCount: 0,
		albumId: null,
		songId: null,
		generationId: null,
		playlistId: null,
		expandedAlbumIds: [],
		scrollAnchor: 0,
		detailTab: 'generations'
	};
}

export function libraryBrowseStateFrom(state: LibraryHistoryState): LibraryHistoryState {
	return {
		...state,
		index: 0,
		surface: 'browse',
		albumId: null,
		songId: null,
		generationId: null,
		playlistId: null
	};
}

export function libraryHistoryUrl(state: LibraryHistoryState): string {
	if (state.songId && state.generationId) return `/?song=${state.songId}&gen=${state.generationId}`;
	if (state.songId) return `/?song=${state.songId}`;
	return '/';
}

export function snapshotLibraryHistory(index: number): LibraryHistoryState {
	const browse = get(libraryBrowse);
	const search = get(librarySearch);
	const query = get(searchQuery);
	const searchMatchesQuery = search.q === query.trim();
	return {
		kind: LIBRARY_HISTORY_KIND,
		index,
		section: get(sharesViewOpen) ? LIBRARY_SHARES_HISTORY_SECTION : get(librarySection),
		surface: get(librarySurface),
		query,
		sort: get(librarySort),
		albumOffset: browse.albumOffset,
		songOffset: browse.songOffset,
		searchCursor: searchMatchesQuery ? search.nextCursor : null,
		searchLoadedCount: searchMatchesQuery ? search.items.length : 0,
		albumId: get(selectedAlbumId),
		songId: get(selectedSongId),
		generationId: get(selectedGenerationId),
		playlistId: get(selectedPlaylistId),
		expandedAlbumIds: [...get(expandedAlbumIds)],
		scrollAnchor: get(libraryScrollAnchor),
		detailTab: get(detailTab)
	};
}

export async function applyLibraryHistory(state: LibraryHistoryState): Promise<boolean> {
	const generation = ++historyApplyGeneration;
	if (state.section === LIBRARY_SHARES_HISTORY_SECTION) {
		openSharesView();
	} else {
		closeSharesView();
		librarySection.set(state.section);
	}
	if (state.section === 'playlists') {
		syncLibrarySearch('');
	}
	librarySurface.set(state.surface);
	librarySort.set(state.sort);
	searchQuery.set(state.query);
	detailTab.set(state.detailTab ?? 'generations');
	expandedAlbumIds.set(new Set(state.expandedAlbumIds));
	libraryScrollAnchor.set(state.scrollAnchor);
	selectedAlbumId.set(state.albumId);
	selectedSongId.set(state.songId);
	selectedGenerationId.set(state.generationId);
	if (state.playlistId) {
		try {
			await loadPlaylistDetail(state.playlistId);
		} catch (err) {
			if (generation !== historyApplyGeneration) return false;
			if (isNotFound(err)) deselectPlaylist();
			else if (get(selectedPlaylistDetail)?.id !== state.playlistId) {
				selectedPlaylistDetail.set(null);
			}
		}
	} else {
		deselectPlaylist();
	}
	if (generation !== historyApplyGeneration) return false;
	if (state.section === 'playlists') {
		void ensurePlaylistsLoaded();
	}
	await restoreLibraryBrowse(state.sort, state.albumOffset, state.songOffset);
	if (generation !== historyApplyGeneration) return false;
	if (state.query.trim() && state.section !== 'playlists') {
		await restoreLibrarySearch(state.query, state.sort, state.searchLoadedCount);
	}
	if (generation !== historyApplyGeneration) return false;
	await hydrateSelectedResources(state, generation);
	if (generation !== historyApplyGeneration) return false;
	const albumIds = [
		...new Set([...(state.albumId ? [state.albumId] : []), ...state.expandedAlbumIds])
	];
	if (albumIds.length > 0) {
		await Promise.all(albumIds.map((albumId) => loadSongsForAlbum(albumId)));
	}
	if (generation !== historyApplyGeneration) return false;
	fallbackBrowseIfDetailGone(state.surface);
	writeActiveModeBag(state);
	return true;
}

export function cancelLibraryHistoryApply(): void {
	historyApplyGeneration += 1;
}

async function hydrateSelectedResources(
	state: LibraryHistoryState,
	generation: number
): Promise<void> {
	if (state.albumId && !get(albumList).some((album) => album.id === state.albumId)) {
		try {
			const album = await fetchAlbum(state.albumId);
			if (generation !== historyApplyGeneration) return;
			albumList.update((list) => upsertReplace(list, album));
		} catch (err) {
			if (generation !== historyApplyGeneration) return;
			if (isNotFound(err)) selectedAlbumId.set(null);
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
	if (get(selectedAlbumId) !== null) return;
	if (get(selectedSongId) !== null) return;
	if (get(selectedPlaylistId) !== null) return;
	librarySurface.set('browse');
}

export async function hydrateLibraryFromHistory(): Promise<boolean> {
	const existing = history.state;
	if (isLibraryHistoryState(existing)) {
		const applied = await applyLibraryHistory(existing);
		if (applied) {
			const restored = snapshotLibraryHistory(existing.index);
			history.replaceState(restored, '', libraryHistoryUrl(restored));
		}
		if (existing.query.trim()) return get(librarySearch).status !== 'error';
		return get(libraryBrowse).status !== 'error';
	}
	return restoreLibraryBrowse(get(librarySort), 0, 0);
}

const EMPTY_SECTION_SCROLL: Record<LibraryHistorySection, number> = {
	albums: 0,
	playlists: 0,
	[LIBRARY_SHARES_HISTORY_SECTION]: 0
};

export const libraryScrollBySection = writable<Record<LibraryHistorySection, number>>({
	...EMPTY_SECTION_SCROLL
});

function currentScrollSlot(): LibraryHistorySection {
	return get(sharesViewOpen) ? LIBRARY_SHARES_HISTORY_SECTION : get(librarySection);
}

function rememberLibraryScroll(slot: LibraryHistorySection): void {
	libraryScrollBySection.update((anchors) => ({
		...anchors,
		[slot]: get(libraryScrollAnchor)
	}));
}

function restoreLibraryScroll(slot: LibraryHistorySection): void {
	libraryScrollAnchor.set(get(libraryScrollBySection)[slot] ?? 0);
}

function showSharesView(open: boolean): void {
	if (open === get(sharesViewOpen)) return;
	const leaving = currentScrollSlot();
	const entering = open ? LIBRARY_SHARES_HISTORY_SECTION : get(librarySection);
	rememberLibraryScroll(leaving);
	if (open) openSharesInventory();
	else closeSharesInventory();
	restoreLibraryScroll(entering);
}

export function openSharesView(): void {
	showSharesView(true);
}

export function closeSharesView(): void {
	showSharesView(false);
}

export function setLibrarySection(section: LibrarySection): LibraryHistoryState {
	closeSharesView();
	const previous = get(librarySection);
	const index = libraryHistoryIndex();
	rememberLibraryScroll(previous);
	if (previous === section) {
		restoreLibraryScroll(section);
		if (section === 'playlists') {
			void ensurePlaylistsLoaded();
		}
		return snapshotLibraryHistory(index);
	}
	rememberModeBag(previous);
	const bag = modeSwitchState(section, index);
	void applyLibraryHistory(bag);
	return bag;
}

export function setLibrarySurface(surface: LibrarySurface): void {
	librarySurface.set(surface);
}

export function hasLibrarySelection(): boolean {
	return (
		get(selectedAlbumId) !== null ||
		get(selectedSongId) !== null ||
		get(selectedGenerationId) !== null ||
		get(selectedPlaylistId) !== null
	);
}

export function toggleAlbumExpanded(albumId: string): void {
	expandedAlbumIds.update((current) => {
		const next = new Set(current);
		if (next.has(albumId)) next.delete(albumId);
		else next.add(albumId);
		return next;
	});
	if (get(expandedAlbumIds).has(albumId)) void loadSongsForAlbum(albumId);
}

export function expandAlbum(albumId: string): void {
	expandedAlbumIds.update((current) => {
		if (current.has(albumId)) return current;
		const next = new Set(current);
		next.add(albumId);
		return next;
	});
	void loadSongsForAlbum(albumId);
}

export function captureLibraryScroll(scrollTop: number): void {
	libraryScrollAnchor.set(scrollTop);
	rememberLibraryScroll(currentScrollSlot());
}

export function albumIsExpanded(
	albumId: string,
	expanded: ReadonlySet<string>,
	options: { selectedAlbumId: string | null; searching: boolean; songHits: number }
): boolean {
	if (options.searching) return options.songHits > 0 || expanded.has(albumId);
	if (options.selectedAlbumId === albumId) return true;
	return expanded.has(albumId);
}

export function resetLibraryContextForTests(): void {
	historyApplyGeneration += 1;
	librarySection.set(LIBRARY_DEFAULT_SECTION);
	librarySurface.set('browse');
	detailTab.set('generations');
	expandedAlbumIds.set(new Set());
	libraryScrollAnchor.set(0);
	libraryScrollBySection.set({ ...EMPTY_SECTION_SCROLL });
	modeBags = { ...EMPTY_MODE_BAGS };
}

function libraryHistoryIndex(): number {
	const state = history.state;
	return isLibraryHistoryState(state) ? state.index : 0;
}

function defaultModeBag(section: LibrarySection): LibraryHistoryState {
	return { ...libraryRootState(), section };
}

function rememberModeBag(section: LibrarySection): void {
	modeBags[section] = { ...snapshotLibraryHistory(libraryHistoryIndex()), section };
}

function modeSwitchState(section: LibrarySection, index: number): LibraryHistoryState {
	return { ...(modeBags[section] ?? defaultModeBag(section)), index, section };
}

function writeActiveModeBag(state: LibraryHistoryState): void {
	if (!isLibrarySection(state.section)) return;
	modeBags[state.section] = {
		...snapshotLibraryHistory(state.index),
		section: state.section
	};
}

function isLibrarySurface(value: unknown): value is LibrarySurface {
	return typeof value === 'string' && SURFACES.has(value as LibrarySurface);
}

function isDetailTab(value: unknown): value is DetailTab {
	return typeof value === 'string' && DETAIL_TABS.has(value as DetailTab);
}

function isIdOrNull(value: unknown): value is string | null {
	return value === null || typeof value === 'string';
}

function upsertReplace<T extends { id: string }>(items: T[], item: T): T[] {
	const index = items.findIndex((existing) => existing.id === item.id);
	if (index === -1) return [...items, item];
	return items.map((existing, i) => (i === index ? item : existing));
}

function isNotFound(err: unknown): boolean {
	return err instanceof ApiError && err.status === 404;
}
