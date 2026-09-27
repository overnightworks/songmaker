import { derived, get, writable, type Readable } from 'svelte/store';
import { describeFailure } from '$lib/api/fetch';
import { fetchAlbums, fetchSongs } from '$lib/api/client';
import type { AlbumItem, GenerationItem, SongItem } from '$lib/api/types';
import {
	LIBRARY_ALBUM_PAGE_SIZE,
	LIBRARY_SONG_PAGE_SIZE,
	RAIL_LIBRARY_LOAD_ERROR
} from '$lib/constants';
import { offline, reloadWhileUnreachable } from './connectivity';

const ALBUM_SONGS_LOAD_ERROR = 'Failed to load songs';
const ALL_ALBUMS_LOAD_ERROR = 'Failed to load albums';

// The library's in-memory cache of every browsed album and song. Every
// surface that lists, filters, or mutates library data reads and writes
// through these two stores and the helpers below, so a take picked in one
// view is picked everywhere else without a refetch.
export const albumList = writable<AlbumItem[]>([]);
export const songList = writable<SongItem[]>([]);

function retainRicherSong(current: SongItem | undefined, incoming: SongItem): SongItem {
	if (!current) return incoming;
	const generations =
		current.generations.length >= incoming.generations.length
			? current.generations
			: incoming.generations;
	return {
		...incoming,
		generations,
		generation_count: Math.max(
			current.generation_count,
			incoming.generation_count,
			generations.length
		)
	};
}

export function overlaySongList(existing: SongItem[], incoming: SongItem[]): SongItem[] {
	const current = new Map(existing.map((song) => [song.id, song]));
	return incoming.map((song) => retainRicherSong(current.get(song.id), song));
}

export function replaceSongInList(song: SongItem): void {
	songList.update((list) => list.map((s) => (s.id === song.id ? song : s)));
}

// Replace the song if the list already holds it, otherwise append it. A song opened
// directly (playlist, search, shared URL) is not in the list yet — only opening its
// album fills the list — so replaceSongInList alone would silently drop it.
export function upsertSongInList(song: SongItem): void {
	songList.update((list) =>
		list.some((s) => s.id === song.id)
			? list.map((s) => (s.id === song.id ? song : s))
			: [...list, song]
	);
}

const albumSongLoads = new Map<string, Promise<void>>();
let albumSongsGeneration = 0;

export function cancelAlbumSongLoads(): void {
	albumSongsGeneration += 1;
	albumSongLoads.clear();
}

type AlbumSongsLoadStatus = 'idle' | 'loading' | 'error';

interface AlbumSongsLoadState {
	status: AlbumSongsLoadStatus;
	error: string | null;
}

export const albumSongsLoad = writable<Readonly<Record<string, AlbumSongsLoadState>>>({});

export async function loadSongsForAlbum(albumId: string): Promise<void> {
	const inflight = albumSongLoads.get(albumId);
	if (inflight !== undefined) return inflight;
	const generation = albumSongsGeneration;
	albumSongsLoad.update((state) => ({
		...state,
		[albumId]: { status: 'loading', error: null }
	}));
	const load = (async () => {
		let offset = 0;
		const collected: SongItem[] = [];
		for (;;) {
			const page = await fetchSongs(albumId, offset, LIBRARY_SONG_PAGE_SIZE);
			if (generation !== albumSongsGeneration) return;
			collected.push(...page.items);
			offset += page.items.length;
			if (!page.has_more || page.items.length === 0) break;
		}
		if (generation !== albumSongsGeneration) return;
		songList.update((list) => mergeAlbumSongs(list, collected));
	})();
	albumSongLoads.set(albumId, load);
	try {
		await load;
		if (generation !== albumSongsGeneration) return;
		albumSongsLoad.update((state) => ({
			...state,
			[albumId]: { status: 'idle', error: null }
		}));
	} catch (err) {
		if (generation !== albumSongsGeneration) return;
		albumSongsLoad.update((state) => ({
			...state,
			[albumId]: { status: 'error', error: albumSongsErrorMessage(err) }
		}));
	} finally {
		albumSongLoads.delete(albumId);
	}
}

export function albumSongsErrorMessage(err: unknown): string {
	return describeFailure(err, ALBUM_SONGS_LOAD_ERROR);
}

function mergeAlbumSongs(list: SongItem[], incoming: SongItem[]): SongItem[] {
	let next = list;
	for (const song of incoming) {
		const merged = retainRicherSong(
			next.find((item) => item.id === song.id),
			song
		);
		next = next.some((item) => item.id === merged.id)
			? next.map((item) => (item.id === merged.id ? merged : item))
			: [...next, merged];
	}
	return next;
}

export function updateSongInList(songId: string, updater: (s: SongItem) => SongItem): void {
	songList.update((list) => list.map((s) => (s.id === songId ? updater(s) : s)));
}

export function addSongToList(song: SongItem): void {
	songList.update((list) => [...list, song]);
}

export function removeSongFromList(songId: string): void {
	songList.update((list) => list.filter((s) => s.id !== songId));
}

export function removeSongsForAlbum(albumId: string): void {
	songList.update((list) => list.filter((s) => s.album_id !== albumId));
}

export function updateAlbumInList(albumId: string, updater: (a: AlbumItem) => AlbumItem): void {
	albumList.update((list) => list.map((a) => (a.id === albumId ? updater(a) : a)));
}

export function removeAlbumFromList(albumId: string): void {
	albumList.update((list) => list.filter((a) => a.id !== albumId));
}

export function addAlbumToList(album: AlbumItem): void {
	albumList.update((list) => {
		if (list.some((a) => a.id === album.id)) return list;
		return [...list, album].sort((a, b) => a.title.localeCompare(b.title));
	});
}

// 'unreachable' is a load the network swallowed: the albums already listed
// stay and the load runs again by itself (see reloadWhileUnreachable);
// `reloadsExhausted` says its bounded backoff is spent.
type AllAlbumsLoadState =
	| { status: 'idle' | 'loading' | 'ready'; error: null }
	| { status: 'error'; error: string }
	| { status: 'unreachable'; error: null; reloadsExhausted: boolean };

type CombineAlbums = (current: AlbumItem[], fetched: AlbumItem[]) => AlbumItem[];

// Tracks a route-independent full load of every album, for surfaces (the
// rail, the library wall) that need the complete list regardless of which
// library page is open. loadLibraryBrowse() keeps paginating and resetting
// albumList for the active browse view -- this loader never .set()s a single
// page, or the two would repeatedly kick each other's results out of the
// store: ensureAllAlbumsLoaded merges into the list, and only the gap re-read
// (rereadAllAlbums) replaces it, with the complete fetched set.
export const allAlbumsLoad = writable<AllAlbumsLoadState>({ status: 'idle', error: null });

/**
 * The failure a surface names about the full album load, or null while there
 * is none to name: a load the network swallowed stays quiet while it reloads
 * and while the offline strip says it; only a spent backoff is named (#1107).
 */
export const allAlbumsLoadFailure: Readable<string | null> = derived(
	[allAlbumsLoad, offline],
	([load, isOffline]) => {
		if (load.status === 'error') return load.error;
		if (load.status === 'unreachable' && load.reloadsExhausted && !isOffline) {
			return RAIL_LIBRARY_LOAD_ERROR;
		}
		return null;
	}
);

let allAlbumsInflight: Promise<boolean> | null = null;
// A reload repeats the load the network swallowed: a gap re-read reads every
// album again rather than merging into a list that may hold deleted ones.
let unreachableLoadCombine: CombineAlbums = mergeFetchedAlbums;
const allAlbumsReloads = reloadWhileUnreachable(() => {
	void loadAllAlbums(unreachableLoadCombine);
});

export async function ensureAllAlbumsLoaded(): Promise<boolean> {
	if (get(allAlbumsLoad).status === 'ready') return true;
	return loadAllAlbums(mergeFetchedAlbums);
}

// A browse reset never removes an album, so after a stream gap one deleted or
// archived on another device would stay. Once a surface asked for every
// album, the snapshot that follows a gap reads them all again and the fresh
// set replaces the list; a read already under way began before the gap, so
// it finishes first.
export async function rereadAllAlbums(): Promise<boolean> {
	if (get(allAlbumsLoad).status === 'idle') return true;
	if (allAlbumsInflight !== null) await allAlbumsInflight;
	return loadAllAlbums(replaceWithFetched);
}

// A browse reset reads only the first album page (history navigation and a
// stream reconnect run one). Once a surface asked for every album, that page
// refreshes the albums it holds and the rest stay, so neither the rail nor
// the wall shrinks to one page and no navigation reads every album again.
export function resetAlbumList(firstPage: AlbumItem[]): void {
	if (get(allAlbumsLoad).status === 'idle') {
		albumList.set(firstPage);
		return;
	}
	albumList.update((current) => refreshAlbums(current, firstPage));
}

function refreshAlbums(current: AlbumItem[], fresh: AlbumItem[]): AlbumItem[] {
	const freshById = new Map(fresh.map((album) => [album.id, album]));
	const currentIds = new Set(current.map((album) => album.id));
	return [
		...fresh.filter((album) => !currentIds.has(album.id)),
		...current.map((album) => freshById.get(album.id) ?? album)
	];
}

function loadAllAlbums(combine: CombineAlbums): Promise<boolean> {
	if (allAlbumsInflight !== null) return allAlbumsInflight;
	allAlbumsLoad.set({ status: 'loading', error: null });
	allAlbumsInflight = (async () => {
		try {
			let offset = 0;
			const collected: AlbumItem[] = [];
			for (;;) {
				const page = await fetchAlbums(offset, LIBRARY_ALBUM_PAGE_SIZE);
				collected.push(...page.items);
				offset += page.items.length;
				if (!page.has_more || page.items.length === 0) break;
			}
			albumList.update((current) => combine(current, collected));
			allAlbumsReloads.stop();
			allAlbumsLoad.set({ status: 'ready', error: null });
			return true;
		} catch (err) {
			allAlbumsLoad.set(allAlbumsFailure(err, combine));
			return false;
		} finally {
			allAlbumsInflight = null;
		}
	})();
	return allAlbumsInflight;
}

function allAlbumsFailure(err: unknown, combine: CombineAlbums): AllAlbumsLoadState {
	unreachableLoadCombine = combine;
	const reload = allAlbumsReloads.afterLoadFailure(err);
	if (reload === null) {
		return { status: 'error', error: describeFailure(err, ALL_ALBUMS_LOAD_ERROR) };
	}
	return { status: 'unreachable', error: null, reloadsExhausted: reload === 'exhausted' };
}

// Existing entries win on a conflicting id, matching loadLibraryBrowse's
// load-more merge -- an album added or refreshed elsewhere while this fetch
// was in flight (e.g. by the grid) must survive, not get overwritten by a
// page fetched before that update happened.
function mergeFetchedAlbums(current: AlbumItem[], fetched: AlbumItem[]): AlbumItem[] {
	const currentIds = new Set(current.map((album) => album.id));
	const newOnes = fetched.filter((album) => !currentIds.has(album.id));
	return [...current, ...newOnes];
}

function replaceWithFetched(_current: AlbumItem[], fetched: AlbumItem[]): AlbumItem[] {
	return fetched;
}

export function addSongsToList(songs: SongItem[]): void {
	if (songs.length === 0) return;
	songList.update((list) => {
		const existingIds = new Set(list.map((s) => s.id));
		const newOnes = songs.filter((s) => !existingIds.has(s.id));
		return [...list, ...newOnes];
	});
}

export function updateGenerationInList(
	genId: string,
	updater: (g: GenerationItem) => GenerationItem
): void {
	songList.update((songs) =>
		songs.map((song) => ({
			...song,
			generations: song.generations.map((g) => (g.id === genId ? updater(g) : g))
		}))
	);
}

export function removeGenerationFromSong(songId: string, genId: string): void {
	updateSongInList(songId, (s) => ({
		...s,
		generations: s.generations.filter((g) => g.id !== genId),
		generation_count: s.generation_count - 1
	}));
}

export function resetLibraryDataForTests(): void {
	allAlbumsReloads.stop();
	allAlbumsInflight = null;
	allAlbumsLoad.set({ status: 'idle', error: null });
}
