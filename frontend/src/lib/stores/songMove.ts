import { derived, get, writable, type Readable } from 'svelte/store';
import { moveSong } from '#lib/api/songs.ts';
import { ApiError, describeFailure } from '#lib/api/fetch.ts';
import type { AlbumItem, SongItem } from '#lib/api/types.ts';
import { COMPACT_LAYOUT_MEDIA } from '#lib/constants/media.ts';
import {
	fetchEveryAlbum,
	overlaySongList,
	replaceSongInList,
	songList,
	updateAlbumInList
} from '#lib/stores/libraryData.ts';
import {
	ensureLastPlayedRead,
	inLibraryOrder,
	libraryPlaceOrder
} from '#lib/stores/libraryOrder.ts';
import { reselectMovedSong } from '#lib/stores/navigation.ts';
import { selectedSongId } from '#lib/stores/player.ts';
import { matchesRailQuery, normalizeRailQuery } from '#lib/stores/librarySearch.ts';
import { libraryWallOrder } from '#lib/stores/ui.ts';
import { addToast } from '#lib/stores/toast.ts';
import { pageText } from '#lib/utils/page-words.ts';

type OwnAlbumsLoad =
	| { status: 'closed' }
	| { status: 'loading' }
	| { status: 'failed'; message: string }
	| { status: 'ready'; albums: AlbumItem[] };

const load = writable<OwnAlbumsLoad>({ status: 'closed' });
// The song the open picker moves; the picker marks its album as the one it is in.
const subject = writable<SongItem | null>(null);
export const songMoveFilter = writable('');

type SongMoveRun =
	| { status: 'idle' }
	| { status: 'busy'; songId: string; albumId: string }
	| { status: 'failed'; songId: string; albumId: string; line: string; retryable: boolean };

const IDLE: SongMoveRun = { status: 'idle' };
const NOT_FOUND = 404;

/** The move in flight or the one that was refused, for the picker to show. */
export const songMoveRun = writable<SongMoveRun>(IDLE);

/** The run, only while its song is the picker's song; any other song's picker shows nothing of it. */
export const songMoveRunHere: Readable<SongMoveRun> = derived(
	[songMoveRun, subject],
	([$run, $song]): SongMoveRun =>
		$run.status !== 'idle' && $run.songId === $song?.id ? $run : IDLE
);

/** The id of the song whose picker is open, so a menu shows its picker only for its own song. */
export const songMoveSubject: Readable<string | null> = derived(
	subject,
	($song) => $song?.id ?? null
);

let generation = 0;

export type SongMovePicker =
	| { status: 'closed' | 'loading' }
	| { status: 'failed'; message: string }
	| {
			status: 'ready';
			current: AlbumItem | null;
			others: AlbumItem[];
			// Whether the person owns an album besides the current one: with none, there is
			// nothing to filter and the picker says so.
			hasOthers: boolean;
	  };

export const songMovePicker: Readable<SongMovePicker> = derived(
	[load, songMoveFilter, subject, libraryPlaceOrder],
	([$load, $filter, $song, $order]): SongMovePicker => {
		if ($load.status !== 'ready') return $load;
		const ordered = inLibraryOrder('album', $load.albums, $order);
		if (ordered.length === 0 && $load.albums.length > 0) return { status: 'loading' };
		const currentId = $song?.album_id ?? null;
		const others = ordered.filter((album) => album.id !== currentId);
		return {
			status: 'ready',
			current: ordered.find((album) => album.id === currentId) ?? null,
			others: others.filter((album) => matchesRailQuery(album.title, normalizeRailQuery($filter))),
			hasOthers: others.length > 0
		};
	}
);

// A quiet load keeps the shown list in place until the new one arrives or fails.
async function loadOwnAlbums(quiet = false): Promise<void> {
	const mine = ++generation;
	if (!quiet) load.set({ status: 'loading' });
	try {
		if (get(libraryWallOrder) === 'played') await ensureLastPlayedRead();
		const albums = await fetchEveryAlbum({ owned: true });
		if (mine === generation) load.set({ status: 'ready', albums });
	} catch (err) {
		if (mine === generation && !quiet) {
			load.set({
				status: 'failed',
				message: describeFailure(err, pageText('songMove.libraryLoadError'))
			});
		}
	}
}

/** Opens `song`'s picker on a fresh list; a refused move keeps its red row across the reopen. */
export async function openSongMovePicker(song: SongItem): Promise<void> {
	subject.set(song);
	songMoveFilter.set('');
	await loadOwnAlbums();
}

export function closeSongMovePicker(): void {
	generation += 1;
	load.set({ status: 'closed' });
	subject.set(null);
	// A move in flight outlives the picker, so a reopened picker still shows it and starts no second one.
	if (get(songMoveRun).status !== 'busy') songMoveRun.set(IDLE);
}

function onPhone(): boolean {
	return typeof window.matchMedia === 'function' && window.matchMedia(COMPACT_LAYOUT_MEDIA).matches;
}

function refusal(err: unknown, songId: string, albumId: string): SongMoveRun {
	if (err instanceof ApiError && err.status === NOT_FOUND) {
		return {
			status: 'failed',
			songId,
			albumId,
			line: pageText('songMove.notMoved', { reason: pageText('songMove.albumGone') }),
			retryable: false
		};
	}
	const reason = describeFailure(err, pageText('songMove.failedReason'), {
		offline: pageText('songMove.noConnection')
	});
	return {
		status: 'failed',
		songId,
		albumId,
		line: pageText('songMove.notMoved', { reason }),
		retryable: true
	};
}

/**
 * Moves `song` into `album` and keeps the person on it, unless they opened another song
 * meanwhile. The crumb names the new album on a wide screen, where a phone has no crumb and gets a
 * toast. A refusal is kept in `songMoveRun`; the answer says whether the song moved. `onlanded`
 * runs once it moved, before the address changes.
 */
async function moveSongTo(
	song: SongItem,
	album: AlbumItem,
	onlanded: () => void = () => undefined
): Promise<boolean> {
	if (song.album_id === album.id || get(songMoveRun).status === 'busy') return false;
	songMoveRun.set({ status: 'busy', songId: song.id, albumId: album.id });
	let moved: SongItem;
	try {
		moved = await moveSong(song.id, album.id);
	} catch (err) {
		const failed = refusal(err, song.id, album.id);
		songMoveRun.set(failed);
		if (failed.status === 'failed' && !failed.retryable && get(load).status !== 'closed') {
			await loadOwnAlbums(true);
		}
		return false;
	}
	songMoveRun.set(IDLE);
	replaceSongInList(
		overlaySongList(get(songList), [{ ...moved, generations: moved.generations ?? [] }])[0]
	);
	updateAlbumInList(song.album_id, (previous) => ({
		...previous,
		song_count: Math.max(0, previous.song_count - 1)
	}));
	updateAlbumInList(album.id, (target) => ({ ...target, song_count: target.song_count + 1 }));
	// The menu's history layer leaves before the address is replaced, or its step back undoes the replace.
	onlanded();
	if (get(selectedSongId) === moved.id) await reselectMovedSong(moved);
	if (onPhone()) addToast(pageText('songMove.moved', { album: album.title }));
	return true;
}

export const songMoveConfirm = writable<{ song: SongItem; album: AlbumItem } | null>(null);

/** Moves `song` at once, except into an album with a public page, which asks first. */
export async function askToMoveSongTo(
	song: SongItem,
	album: AlbumItem,
	onlanded?: () => void
): Promise<boolean> {
	if (get(songMoveRun).status === 'busy') return false;
	if (!album.is_shared) return moveSongTo(song, album, onlanded);
	songMoveConfirm.set({ song, album });
	return false;
}

export async function confirmSongMove(): Promise<boolean> {
	const ask = get(songMoveConfirm);
	songMoveConfirm.set(null);
	return ask ? moveSongTo(ask.song, ask.album) : false;
}

/** Repeats the refused move of its own song, into the same album and without asking again. */
export async function retrySongMove(onlanded?: () => void): Promise<boolean> {
	const run = get(songMoveRun);
	const state = get(load);
	if (run.status !== 'failed' || !run.retryable || state.status !== 'ready') return false;
	const album = state.albums.find((candidate) => candidate.id === run.albumId);
	const song = get(songList).find((candidate) => candidate.id === run.songId);
	return album && song ? moveSongTo(song, album, onlanded) : false;
}

export function cancelSongMove(): void {
	songMoveConfirm.set(null);
}
