import { get, writable } from 'svelte/store';
import type { LibrarySort } from '$lib/api/library';
import {
	LIBRARY_DEFAULT_SECTION,
	LIBRARY_HISTORY_KIND,
	LIBRARY_SECTIONS,
	type LibrarySection
} from '$lib/constants';
import { searchQuery } from '$lib/stores/filter';
import { libraryBrowse, librarySearch, librarySort } from '$lib/stores/librarySearch';
import { selectedAlbumId, selectedGenerationId, selectedSongId } from '$lib/stores/player';
import {
	deselectPlaylist,
	ensurePlaylistsLoaded,
	selectPlaylist,
	selectedPlaylistId
} from '$lib/stores/playlists';
import { CREATED_SORTS } from '$lib/utils/recency';

export interface LibraryHistoryState {
	kind: typeof LIBRARY_HISTORY_KIND;
	index: number;
	section: LibrarySection;
	query: string;
	sort: LibrarySort;
	albumOffset: number;
	songOffset: number;
	searchCursor: string | null;
	albumId: string | null;
	songId: string | null;
	generationId: string | null;
	playlistId: string | null;
	expandedAlbumIds: string[];
	scrollAnchor: number;
}

export const librarySection = writable<LibrarySection>(LIBRARY_DEFAULT_SECTION);
export const expandedAlbumIds = writable<ReadonlySet<string>>(new Set());
export const libraryScrollAnchor = writable(0);

const SORTS: ReadonlySet<string> = new Set(CREATED_SORTS);

export function isLibrarySection(value: unknown): value is LibrarySection {
	return LIBRARY_SECTIONS.some((section) => section === value);
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
	if (!isLibrarySection(state.section)) return false;
	if (typeof state.query !== 'string') return false;
	if (!isLibrarySort(state.sort)) return false;
	if (typeof state.albumOffset !== 'number' || typeof state.songOffset !== 'number') return false;
	if (typeof state.scrollAnchor !== 'number') return false;
	if (!isIdOrNull(state.searchCursor)) return false;
	if (!isIdOrNull(state.albumId)) return false;
	if (!isIdOrNull(state.songId)) return false;
	if (!isIdOrNull(state.generationId)) return false;
	if (!isIdOrNull(state.playlistId)) return false;
	if (!Array.isArray(state.expandedAlbumIds)) return false;
	return state.expandedAlbumIds.every((id) => typeof id === 'string');
}

export function libraryRootState(): LibraryHistoryState {
	return {
		kind: LIBRARY_HISTORY_KIND,
		index: 0,
		section: LIBRARY_DEFAULT_SECTION,
		query: '',
		sort: 'newest',
		albumOffset: 0,
		songOffset: 0,
		searchCursor: null,
		albumId: null,
		songId: null,
		generationId: null,
		playlistId: null,
		expandedAlbumIds: [],
		scrollAnchor: 0
	};
}

export function libraryBrowseStateFrom(state: LibraryHistoryState): LibraryHistoryState {
	return {
		...state,
		index: 0,
		albumId: null,
		songId: null,
		generationId: null,
		playlistId: null
	};
}

export function snapshotLibraryHistory(index: number): LibraryHistoryState {
	const browse = get(libraryBrowse);
	const search = get(librarySearch);
	return {
		kind: LIBRARY_HISTORY_KIND,
		index,
		section: get(librarySection),
		query: get(searchQuery),
		sort: get(librarySort),
		albumOffset: browse.albumOffset,
		songOffset: browse.songOffset,
		searchCursor: search.nextCursor,
		albumId: get(selectedAlbumId),
		songId: get(selectedSongId),
		generationId: get(selectedGenerationId),
		playlistId: get(selectedPlaylistId),
		expandedAlbumIds: [...get(expandedAlbumIds)],
		scrollAnchor: get(libraryScrollAnchor)
	};
}

export function applyLibraryHistory(state: LibraryHistoryState): void {
	librarySection.set(state.section);
	librarySort.set(state.sort);
	searchQuery.set(state.query);
	expandedAlbumIds.set(new Set(state.expandedAlbumIds));
	libraryScrollAnchor.set(state.scrollAnchor);
	selectedAlbumId.set(state.albumId);
	selectedSongId.set(state.songId);
	selectedGenerationId.set(state.generationId);
	if (state.playlistId) {
		selectPlaylist(state.playlistId);
	} else {
		deselectPlaylist();
	}
	libraryBrowse.update((browse) => ({
		...browse,
		albumOffset: state.albumOffset,
		songOffset: state.songOffset
	}));
	if (state.section === 'playlists' || state.section === 'shared') {
		void ensurePlaylistsLoaded();
	}
}

export function setLibrarySection(section: LibrarySection): void {
	librarySection.set(section);
	if (section === 'playlists' || section === 'shared') {
		void ensurePlaylistsLoaded();
	}
}

export function toggleAlbumExpanded(albumId: string): void {
	expandedAlbumIds.update((current) => {
		const next = new Set(current);
		if (next.has(albumId)) next.delete(albumId);
		else next.add(albumId);
		return next;
	});
}

export function expandAlbum(albumId: string): void {
	expandedAlbumIds.update((current) => {
		if (current.has(albumId)) return current;
		const next = new Set(current);
		next.add(albumId);
		return next;
	});
}

export function captureLibraryScroll(scrollTop: number): void {
	libraryScrollAnchor.set(scrollTop);
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
	librarySection.set(LIBRARY_DEFAULT_SECTION);
	expandedAlbumIds.set(new Set());
	libraryScrollAnchor.set(0);
}

function isIdOrNull(value: unknown): value is string | null {
	return value === null || typeof value === 'string';
}
