import { derived, get, writable, type Readable } from 'svelte/store';
import { moveSong } from '#lib/api/songs.ts';
import { describeFailure } from '#lib/api/fetch.ts';
import type { AlbumItem, SongItem } from '#lib/api/types.ts';
import {
	COMPACT_LAYOUT_MEDIA,
	RAIL_LIBRARY_LOAD_ERROR,
	SONG_MOVE_FAILED,
	songMovedToastLabel
} from '#lib/constants.ts';
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
import { selectedSong } from '#lib/stores/player.ts';
import { matchesRailQuery, normalizeRailQuery } from '#lib/stores/librarySearch.ts';
import { libraryWallOrder } from '#lib/stores/ui.ts';
import { addToast } from '#lib/stores/toast.ts';

type OwnAlbumsLoad =
	| { status: 'closed' }
	| { status: 'loading' }
	| { status: 'failed'; message: string }
	| { status: 'ready'; albums: AlbumItem[] };

const load = writable<OwnAlbumsLoad>({ status: 'closed' });
export const songMoveFilter = writable('');

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
	[load, songMoveFilter, selectedSong, libraryPlaceOrder],
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

export async function openSongMovePicker(): Promise<void> {
	const mine = ++generation;
	songMoveFilter.set('');
	load.set({ status: 'loading' });
	try {
		if (get(libraryWallOrder) === 'played') await ensureLastPlayedRead();
		const albums = await fetchEveryAlbum({ owned: true });
		if (mine === generation) load.set({ status: 'ready', albums });
	} catch (err) {
		if (mine === generation) {
			load.set({ status: 'failed', message: describeFailure(err, RAIL_LIBRARY_LOAD_ERROR) });
		}
	}
}

export function closeSongMovePicker(): void {
	generation += 1;
	load.set({ status: 'closed' });
}

function onPhone(): boolean {
	return typeof window.matchMedia === 'function' && window.matchMedia(COMPACT_LAYOUT_MEDIA).matches;
}

/**
 * Moves the open song into `album` and keeps the person on it. The crumb names the new
 * album on a wide screen, where a phone has no crumb and gets a toast.
 */
export async function moveOpenSongTo(album: AlbumItem): Promise<void> {
	const song = get(selectedSong);
	if (!song || song.album_id === album.id) return;
	let moved: SongItem;
	try {
		moved = await moveSong(song.id, album.id);
	} catch (err) {
		addToast(describeFailure(err, SONG_MOVE_FAILED), 'error', err);
		return;
	}
	replaceSongInList(
		overlaySongList(get(songList), [{ ...moved, generations: moved.generations ?? [] }])[0]
	);
	updateAlbumInList(song.album_id, (previous) => ({
		...previous,
		song_count: Math.max(0, previous.song_count - 1)
	}));
	updateAlbumInList(album.id, (target) => ({ ...target, song_count: target.song_count + 1 }));
	await reselectMovedSong(moved);
	if (onPhone()) addToast(songMovedToastLabel(album.title));
}
