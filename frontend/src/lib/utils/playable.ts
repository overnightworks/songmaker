import type { AlbumItem, GenerationItem, SongItem } from '$lib/api/types';
import type { AlbumSongsLoadStatus } from '$lib/stores/libraryData';

/*
 * The one frontend owner of "something to hear", mirroring the backend's
 * is_playable_take. A false answer is always right; a true answer may be
 * refined once the takes load, so callers never need to re-decide.
 */

type SongPlayability = 'playable' | 'none' | 'unknown';

export function isPlayableTake(gen: GenerationItem): boolean {
	return !gen.is_archived && gen.mp3_path !== '';
}

function playableTakes(song: SongItem): GenerationItem[] {
	return song.generations.filter(isPlayableTake);
}

export function pickedTake(song: SongItem): GenerationItem | undefined {
	return playableTakes(song).find((gen) => gen.is_picked);
}

export function bestTake(song: SongItem): GenerationItem | undefined {
	return pickedTake(song) ?? playableTakes(song)[0];
}

export function songTakesLoaded(song: SongItem): boolean {
	return song.generations.length >= song.generation_count;
}

export function songPlayability(song: SongItem): SongPlayability {
	if (song.generation_count === 0) return 'none';
	if (!songTakesLoaded(song)) return 'unknown';
	return playableTakes(song).length > 0 ? 'playable' : 'none';
}

export function songHasPlayableTake(song: SongItem): boolean {
	return songPlayability(song) !== 'none';
}

// The songs speak for the album once they are all here; before that, or
// while their takes are unread, the server's answer stands.
export function albumHasPlayableTake(
	album: Pick<AlbumItem, 'has_playable_take'>,
	songs: SongItem[],
	{ songsComplete }: { songsComplete: boolean }
): boolean {
	const playabilities = songs.map(songPlayability);
	if (playabilities.includes('playable')) return true;
	if (songsComplete && playabilities.every((playability) => playability === 'none')) return false;
	return album.has_playable_take;
}

// An album's songs speak for it once their load has settled, which
// `albumSongsLoad` records as 'idle'.
export function albumSongsSettled(load: AlbumSongsLoadStatus | undefined): boolean {
	return load === 'idle';
}

// Whether an album's row offers ▶, for every list that shows album rows.
export function albumRowOffersPlay(
	album: Pick<AlbumItem, 'id' | 'has_playable_take'>,
	songs: SongItem[],
	songLoads: Readonly<Record<string, AlbumSongsLoadStatus>>
): boolean {
	return albumHasPlayableTake(album, songs, {
		songsComplete: albumSongsSettled(songLoads[album.id])
	});
}

// Whether Now Playing opens on This take: one queued take outside an album, or
// an album whose settled songs offer one take. An album starts with a one-take
// queue the rest joins a moment later, and its songs may still be loading, so
// an unsettled album is in doubt and opens Queue.
export function queueHoldsOneTake(
	queuedCount: number,
	album: { songs: SongItem[]; load: AlbumSongsLoadStatus | undefined } | null
): boolean {
	if (queuedCount !== 1) return false;
	if (album === null) return true;
	return albumSongsSettled(album.load) && album.songs.filter(songHasPlayableTake).length <= 1;
}
