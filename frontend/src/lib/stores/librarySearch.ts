import { get, writable } from 'svelte/store';
import { ApiError } from '$lib/api/fetch';
import { fetchAlbums } from '$lib/api/albums';
import { searchLibrary, type LibrarySearchHit, type LibrarySort } from '$lib/api/library';
import { fetchSongs } from '$lib/api/songs';
import type { AlbumItem, SongItem } from '$lib/api/types';
import {
	LIBRARY_ALBUM_PAGE_SIZE,
	LIBRARY_QUERY_REQUIRED,
	LIBRARY_SEARCH_DEBOUNCE_MS,
	LIBRARY_SEARCH_PAGE_SIZE,
	LIBRARY_SONG_PAGE_SIZE
} from '$lib/constants';
import { albumList, selectedSongId, songList, upsertSongInList } from '$lib/stores/player';

export type LibrarySearchStatus = 'idle' | 'loading' | 'error' | 'ready';

export interface LibrarySearchState {
	q: string;
	status: LibrarySearchStatus;
	error: string | null;
	items: LibrarySearchHit[];
	hasMore: boolean;
	nextCursor: string | null;
}

export interface LibraryBrowseState {
	status: LibrarySearchStatus;
	error: string | null;
	albumHasMore: boolean;
	songHasMore: boolean;
	albumOffset: number;
	songOffset: number;
}

export interface LibraryAlbumGroup {
	album: AlbumItem;
	songs: SongItem[];
}

const EMPTY_SEARCH: LibrarySearchState = {
	q: '',
	status: 'idle',
	error: null,
	items: [],
	hasMore: false,
	nextCursor: null
};

export const librarySort = writable<LibrarySort>('newest');
export const librarySearch = writable<LibrarySearchState>({ ...EMPTY_SEARCH });
export const libraryBrowse = writable<LibraryBrowseState>({
	status: 'idle',
	error: null,
	albumHasMore: false,
	songHasMore: false,
	albumOffset: 0,
	songOffset: 0
});

let searchTimer: ReturnType<typeof setTimeout> | null = null;
let searchGeneration = 0;
let browseGeneration = 0;

export function groupSearchHits(hits: LibrarySearchHit[]): LibraryAlbumGroup[] {
	const groups = new Map<string, LibraryAlbumGroup>();
	for (const hit of hits) {
		if (hit.type === 'album') {
			const existing = groups.get(hit.album.id);
			if (existing) {
				existing.album = hit.album;
			} else {
				groups.set(hit.album.id, { album: hit.album, songs: [] });
			}
			continue;
		}
		let group = groups.get(hit.album_id);
		if (!group) {
			group = {
				album: {
					id: hit.album_id,
					title: hit.album_title,
					artist: hit.song.artist,
					subtitle: '',
					year: '',
					colors: {},
					song_count: 0,
					is_shared: false,
					share_slug: null,
					created_at: hit.song.created_at
				},
				songs: []
			};
			groups.set(hit.album_id, group);
		}
		group.songs.push(hit.song);
		if (group.album.song_count < group.songs.length) {
			group.album = { ...group.album, song_count: group.songs.length };
		}
	}
	return [...groups.values()];
}

export function syncLibrarySearch(rawQuery: string): void {
	const q = rawQuery.trim();
	if (!q) {
		if (searchTimer !== null) {
			clearTimeout(searchTimer);
			searchTimer = null;
		}
		searchGeneration += 1;
		librarySearch.set({ ...EMPTY_SEARCH });
		return;
	}
	const current = get(librarySearch);
	if (current.q === q && (current.status === 'loading' || current.status === 'ready')) {
		return;
	}
	if (searchTimer !== null) {
		clearTimeout(searchTimer);
		searchTimer = null;
	}
	librarySearch.set({
		q,
		status: 'loading',
		error: null,
		items: [],
		hasMore: false,
		nextCursor: null
	});
	const sort = get(librarySort);
	searchTimer = setTimeout(() => {
		searchTimer = null;
		void runLibrarySearch(q, sort, { reset: true });
	}, LIBRARY_SEARCH_DEBOUNCE_MS);
}

export function retryLibrarySearch(): void {
	const state = get(librarySearch);
	if (!state.q) return;
	void runLibrarySearch(state.q, get(librarySort), { reset: state.items.length === 0 });
}

export async function loadMoreLibrarySearch(): Promise<void> {
	const state = get(librarySearch);
	if (!state.q || !state.hasMore || state.status === 'loading') return;
	await runLibrarySearch(state.q, get(librarySort), { reset: false });
}

export async function restoreLibrarySearch(
	rawQuery: string,
	sort: LibrarySort,
	loadedCount: number
): Promise<void> {
	if (searchTimer !== null) {
		clearTimeout(searchTimer);
		searchTimer = null;
	}
	const q = rawQuery.trim();
	if (!q) {
		searchGeneration += 1;
		librarySearch.set({ ...EMPTY_SEARCH });
		return;
	}
	librarySort.set(sort);
	librarySearch.set({
		q,
		status: 'loading',
		error: null,
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
		await runLibrarySearch(q, sort, { reset: false });
	}
}

export function changeLibrarySort(sort: LibrarySort, searchRaw: string): void {
	librarySort.set(sort);
	const q = searchRaw.trim();
	if (!q) {
		void loadLibraryBrowse({ reset: true });
		return;
	}
	if (searchTimer !== null) {
		clearTimeout(searchTimer);
		searchTimer = null;
	}
	librarySearch.set({
		q,
		status: 'loading',
		error: null,
		items: [],
		hasMore: false,
		nextCursor: null
	});
	void runLibrarySearch(q, sort, { reset: true });
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

export async function loadLibraryBrowse(options?: { reset?: boolean }): Promise<boolean> {
	const generation = ++browseGeneration;
	const reset = options?.reset ?? true;
	const sort = get(librarySort);
	const browse = get(libraryBrowse);
	const albumOffset = reset ? 0 : browse.albumOffset;
	const songOffset = reset ? 0 : browse.songOffset;
	libraryBrowse.update((state) => ({ ...state, status: 'loading', error: null }));
	try {
		const [albumPage, songPage] = await Promise.all([
			fetchAlbums(albumOffset, LIBRARY_ALBUM_PAGE_SIZE, { sort }),
			fetchSongs(undefined, songOffset, LIBRARY_SONG_PAGE_SIZE, { sort })
		]);
		if (generation !== browseGeneration) return false;
		if (reset) {
			albumList.set(albumPage.items);
			songList.set(songPage.items);
		} else {
			albumList.set(dedupeById([...get(albumList), ...albumPage.items]));
			songList.set(dedupeById([...get(songList), ...songPage.items]));
		}
		libraryBrowse.set({
			status: 'ready',
			error: null,
			albumHasMore: albumPage.has_more,
			songHasMore: songPage.has_more,
			albumOffset: albumOffset + albumPage.items.length,
			songOffset: songOffset + songPage.items.length
		});
		return true;
	} catch (err) {
		if (generation !== browseGeneration) return false;
		libraryBrowse.update((state) => ({
			...state,
			status: 'error',
			error: errorMessage(err)
		}));
		return false;
	}
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
			hit.type === 'song' && hit.song.id === song.id ? { ...hit, song } : hit
		)
	}));
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

export function cancelLibraryDataLoads(): void {
	if (searchTimer !== null) {
		clearTimeout(searchTimer);
		searchTimer = null;
	}
	searchGeneration += 1;
	browseGeneration += 1;
}

export function resetLibrarySearchForTests(): void {
	cancelLibraryDataLoads();
	librarySort.set('newest');
	librarySearch.set({ ...EMPTY_SEARCH });
	libraryBrowse.set({
		status: 'idle',
		error: null,
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
	if (!q) {
		throw new Error(LIBRARY_QUERY_REQUIRED);
	}
	const generation = ++searchGeneration;
	if (options.reset) {
		librarySearch.update((state) => ({ ...state, q, status: 'loading', error: null }));
	} else {
		librarySearch.update((state) => ({ ...state, status: 'loading', error: null }));
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
			error: null,
			items: options.reset ? resp.items : dedupeHits([...state.items, ...resp.items]),
			hasMore: resp.has_more,
			nextCursor: resp.next_cursor
		}));
	} catch (err) {
		if (generation !== searchGeneration) return;
		librarySearch.update((state) => ({
			...state,
			q,
			status: 'error',
			error: errorMessage(err)
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

function errorMessage(err: unknown): string {
	if (err instanceof ApiError) return err.detail || err.message;
	if (err instanceof Error) return err.message;
	return 'Search failed';
}
