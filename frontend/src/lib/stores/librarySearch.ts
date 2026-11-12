import { derived, get, writable } from 'svelte/store';
import { fetchAlbums } from '#lib/api/albums.ts';
import { searchLibrary, type LibrarySort } from '#lib/api/library.ts';
import { fetchSongs } from '#lib/api/songs.ts';
import type { LibrarySearchResponse, SongItem, SongSummaryResponse } from '#lib/api/types.ts';
import {
	LIBRARY_ALBUM_PAGE_SIZE,
	LIBRARY_SEARCH_PAGE_SIZE,
	LIBRARY_SONG_PAGE_SIZE
} from '#lib/constants/library.ts';
import {
	albumList,
	overlaySongList,
	resetAlbumList,
	removeSongFromList,
	songList,
	upsertSongInList
} from '#lib/stores/libraryData.ts';
import { selectedSongId } from '#lib/stores/player.ts';

// A reply to a search or browse that a newer one replaced is dropped, success
// or failure. A later page adds only hits and items not already shown, and a
// restore stops at the first page that fails. The loaded song ids name song
// hits and the selected song, never an album.

type LibrarySearchStatus = 'idle' | 'loading' | 'error' | 'ready';
export type LibrarySearchHit = LibrarySearchResponse['items'][number];

interface LibrarySearchState {
	q: string;
	status: LibrarySearchStatus;
	items: LibrarySearchHit[];
	hasMore: boolean;
	nextCursor: string | null;
}

interface LibraryBrowseState {
	status: LibrarySearchStatus;
	albumHasMore: boolean;
	songHasMore: boolean;
	albumOffset: number;
	songOffset: number;
}

const EMPTY_SEARCH: LibrarySearchState = {
	q: '',
	status: 'idle',
	items: [],
	hasMore: false,
	nextCursor: null
};

// The rail tree's filter and the rail search's own matching (playlists, pages)
// fold the query and each title through these two, so neither folds case its
// own way.
export function normalizeRailQuery(query: string): string {
	return query.trim().toLocaleLowerCase();
}

export function matchesRailQuery(text: string, normalizedQuery: string): boolean {
	return text.toLocaleLowerCase().includes(normalizedQuery);
}

export const railTreeQuery = writable('');
export const normalizedRailTreeQuery = derived(railTreeQuery, normalizeRailQuery);
export const searchQuery = writable('');

export const librarySort = writable<LibrarySort>('newest');
export const librarySearch = writable<LibrarySearchState>({ ...EMPTY_SEARCH });
export const libraryBrowse = writable<LibraryBrowseState>({
	status: 'idle',
	albumHasMore: false,
	songHasMore: false,
	albumOffset: 0,
	songOffset: 0
});

let searchGeneration = 0;
let browseGeneration = 0;

export async function restoreLibrarySearch(
	rawQuery: string,
	sort: LibrarySort,
	loadedCount: number
): Promise<void> {
	const q = rawQuery.trim();
	librarySort.set(sort);
	librarySearch.set({
		q,
		status: 'loading',
		items: [],
		hasMore: false,
		nextCursor: null
	});
	await runLibrarySearch(q, sort, { reset: true });
	const target = Math.max(0, loadedCount);
	while (
		get(librarySearch).q === q &&
		get(librarySearch).status === 'ready' &&
		get(librarySearch).hasMore &&
		get(librarySearch).items.length < target
	) {
		await runLibrarySearch(q, sort, { reset: false }); // NOSONAR(S9382) each page needs the cursor the previous page returned
	}
}

export async function restoreLibraryBrowse(
	sort: LibrarySort,
	targetAlbumOffset: number,
	targetSongOffset: number
): Promise<boolean> {
	librarySort.set(sort);
	const ok = await loadLibraryBrowse({ reset: true });
	if (!ok) return false;
	const albumTarget = Math.max(0, targetAlbumOffset);
	const songTarget = Math.max(0, targetSongOffset);
	while (get(libraryBrowse).status === 'ready') {
		const browse = get(libraryBrowse);
		const needAlbums = browse.albumOffset < albumTarget && browse.albumHasMore;
		const needSongs = browse.songOffset < songTarget && browse.songHasMore;
		if (!needAlbums && !needSongs) break;
		const more = await loadLibraryBrowse({ reset: false });
		if (!more) return false;
	}
	return true;
}

export async function loadLibraryBrowse(options: { reset: boolean }): Promise<boolean> {
	const generation = ++browseGeneration;
	const { reset } = options;
	const sort = get(librarySort);
	const browse = get(libraryBrowse);
	const albumOffset = reset ? 0 : browse.albumOffset;
	const songOffset = reset ? 0 : browse.songOffset;
	libraryBrowse.update((state) => ({ ...state, status: 'loading' }));
	try {
		const [albumPage, songPage] = await Promise.all([
			fetchAlbums(albumOffset, LIBRARY_ALBUM_PAGE_SIZE, { sort }),
			fetchSongs(undefined, songOffset, LIBRARY_SONG_PAGE_SIZE, { sort })
		]);
		if (generation !== browseGeneration) return false;
		if (reset) {
			resetAlbumList(albumPage.items);
			songList.set(overlaySongList(get(songList), songPage.items));
		} else {
			albumList.set(dedupeById([...get(albumList), ...albumPage.items]));
			songList.set(
				dedupeById([...get(songList), ...overlaySongList(get(songList), songPage.items)])
			);
		}
		libraryBrowse.set({
			status: 'ready',
			albumHasMore: albumPage.has_more,
			songHasMore: songPage.has_more,
			albumOffset: albumOffset + albumPage.items.length,
			songOffset: songOffset + songPage.items.length
		});
		return true;
	} catch {
		if (generation !== browseGeneration) return false;
		libraryBrowse.update((state) => ({
			...state,
			status: 'error'
		}));
		return false;
	}
}

export function forgetSyncedSong(songId: string): void {
	removeSongFromList(songId);
	librarySearch.update((state) => ({
		...state,
		items: state.items.filter((hit) => hit.type !== 'song' || hit.song.id !== songId)
	}));
}

export function applySyncedSong(song: SongItem): void {
	const selectedId = get(selectedSongId);
	const listed = get(songList).some((item) => item.id === song.id);
	if (selectedId === song.id || listed) {
		upsertSongInList(song);
	}
	librarySearch.update((state) => ({
		...state,
		items: state.items.map((hit) =>
			hit.type === 'song' && hit.song.id === song.id ? { ...hit, song: toSongSummary(song) } : hit
		)
	}));
}

function toSongSummary(song: SongItem): SongSummaryResponse {
	const { generations: _generations, ...summary } = song;
	return summary as SongSummaryResponse;
}

export function listLoadedSongIds(): string[] {
	const ids = new Set<string>();
	const selected = get(selectedSongId);
	if (selected) ids.add(selected);
	for (const song of get(songList)) ids.add(song.id);
	for (const hit of get(librarySearch).items) {
		if (hit.type === 'song') ids.add(hit.song.id);
	}
	return [...ids];
}

export function watchLoadedSongIds(onChange: () => void): () => void {
	const unsubscribers = [
		songList.subscribe(() => onChange()),
		librarySearch.subscribe(() => onChange()),
		selectedSongId.subscribe(() => onChange())
	];
	return () => {
		for (const unsubscribe of unsubscribers) unsubscribe();
	};
}

export function cancelLibraryDataLoads(): void {
	searchGeneration += 1;
	browseGeneration += 1;
}

export function resetLibrarySearchForTests(): void {
	cancelLibraryDataLoads();
	librarySort.set('newest');
	librarySearch.set({ ...EMPTY_SEARCH });
	libraryBrowse.set({
		status: 'idle',
		albumHasMore: false,
		songHasMore: false,
		albumOffset: 0,
		songOffset: 0
	});
}

async function runLibrarySearch(
	q: string,
	sort: LibrarySort,
	options: { reset: boolean }
): Promise<void> {
	const generation = ++searchGeneration;
	if (options.reset) {
		librarySearch.update((state) => ({ ...state, q, status: 'loading' }));
	} else {
		librarySearch.update((state) => ({ ...state, status: 'loading' }));
	}
	const cursor = options.reset ? null : get(librarySearch).nextCursor;
	try {
		const resp = await searchLibrary({
			q,
			sort,
			limit: LIBRARY_SEARCH_PAGE_SIZE,
			cursor
		});
		if (generation !== searchGeneration) return;
		librarySearch.update((state) => ({
			q,
			status: 'ready',
			items: options.reset ? resp.items : dedupeHits([...state.items, ...resp.items]),
			hasMore: resp.has_more,
			nextCursor: resp.next_cursor
		}));
	} catch {
		if (generation !== searchGeneration) return;
		librarySearch.update((state) => ({
			...state,
			q,
			status: 'error'
		}));
	}
}

function dedupeHits(hits: LibrarySearchHit[]): LibrarySearchHit[] {
	const seen = new Set<string>();
	const unique: LibrarySearchHit[] = [];
	for (const hit of hits) {
		const id = hit.type === 'album' ? hit.album.id : hit.song.id;
		const key = `${hit.type}:${id}`;
		if (seen.has(key)) continue;
		seen.add(key);
		unique.push(hit);
	}
	return unique;
}

function dedupeById<T extends { id: string }>(items: T[]): T[] {
	const seen = new Set<string>();
	const unique: T[] = [];
	for (const item of items) {
		if (seen.has(item.id)) continue;
		seen.add(item.id);
		unique.push(item);
	}
	return unique;
}
