import { derived, get, writable } from 'svelte/store';
import type { AlbumItem, GenerationItem, PlaylistEntryItem, SongItem } from '#lib/api/types.ts';
import { audioPlayer, type PlaybackInfo } from '#lib/services/audioPlayer.svelte.ts';
import { type PlaybackSource } from '#lib/constants/now-playing.ts';
import { albumList, songList } from '#lib/stores/libraryData.ts';
import { isPlayableTake, pickedTake, songTakesLoaded } from '#lib/utils/playable.ts';
import { groupTakes, takesInGroupOrder } from '#lib/utils/takeGroups.ts';

// A playlist queue names the playlist it was built from. The queue is the
// only owner of that name: navigation may open, close, or replace the
// playlist detail while the queue keeps playing, so nothing downstream may
// read the open collection to label what is playing.
export interface PlaylistQueueSource {
	id: string;
	title: string;
}

// A take the deck could not fetch stays skipped for the life of its queue,
// and is named once, when playback reaches the place it would have started.
export interface SkipNotice {
	state: 'pending' | 'announced';
	index: number;
}

interface QueueSkips {
	skipped?: ReadonlyMap<PlaybackInfo, SkipNotice>;
}

// The takes of one song, in the take list's order, the tapped one in play.
export interface SongQueue {
	type: 'song';
	songId: string;
	songTitle: string;
	takes: PlaybackInfo[];
	// The same takes in the take list's order, which a shuffle toggle rebuilds
	// the queue from, so that it never depends on what the song list holds.
	inListOrder: PlaybackInfo[];
	index: number;
}

export type QueueContext = QueueSkips &
	(
		| { type: 'library'; takes?: PlaybackInfo[]; index?: number }
		| { type: 'album'; albumId: string; takes?: PlaybackInfo[]; index?: number }
		| SongQueue
		| {
				type: 'playlist';
				playlist: PlaylistQueueSource;
				entries: PlaylistEntryItem[];
				index: number;
		  }
	);

export const queueContext = writable<QueueContext>({ type: 'library' });

// One PlaybackInfo per playlist entry, handed out every time that entry is
// played or preloaded, so the take the player holds names its place in the
// queue even where a playlist holds one take twice.
const playbackInfoOfEntry = new WeakMap<PlaylistEntryItem, PlaybackInfo>();

// Curation mode (issue #228): whether the listener is walking an album's
// candidate takes one after another via curateAlbum. setQueueContext is the
// one writer of queueContext and owns turning this off — every fresh queue
// build clears it (a different album, a take clicked mid-curation that
// rebuilds a thin context, a playlist) unless the caller opts back in, which
// only curateAlbum's own write does. A bare index move within the queue
// that is already playing (Skip's playNextSong, a queue-row jump) never
// goes through this funnel — see playNativeIndex — so it carries curation
// forward instead of ending it on every single advance.
export const curationActive = writable(false);

export function setQueueContext(ctx: QueueContext, opts: { curating?: boolean } = {}): void {
	queueContext.set(ctx);
	curationActive.set(opts.curating ?? false);
}

export const libraryQueueSkippedComplete = writable(true);

// Where the playing music comes from, named by the queue itself — never by
// the collection the listener happens to have open, which they are free to
// leave mid-track. The mini player and Now Playing both read it here. A
// library queue has no source, and neither has an album queue whose album is
// not in the list to name it.
export const playbackSource = derived(
	[queueContext, albumList],
	([$ctx, $albums]): PlaybackSource | null => {
		if ($ctx.type === 'album') {
			const title = albumTitle($albums, $ctx.albumId);
			return title ? { kind: 'album', id: $ctx.albumId, title } : null;
		}
		if ($ctx.type === 'playlist') {
			return { kind: 'playlist', id: $ctx.playlist.id, title: $ctx.playlist.title };
		}
		if ($ctx.type === 'song') return { kind: 'song', id: $ctx.songId, title: $ctx.songTitle };
		return null;
	}
);

export function albumTitle(albums: AlbumItem[], albumId: string): string {
	return albums.find((album) => album.id === albumId)?.title ?? '';
}

export function nativeTakeIndex(
	ctx: Exclude<QueueContext, { type: 'playlist' }>,
	current: PlaybackInfo | null
): number {
	if (!ctx.takes || ctx.takes.length === 0) return -1;
	if (!current) return ctx.index ?? 0;
	return queuePositionOf(
		ctx.takes,
		ctx.index ?? 0,
		(take) => take === current,
		(take) => take.generation.id === current.generation.id
	);
}

// The place a take was handed out for is the queue's own answer, even where
// the queue holds that take twice. A take built elsewhere (a song row, a
// restored session) is looked for by what it plays, from the queue's own
// index on.
function queuePositionOf<T>(
	items: readonly T[],
	from: number,
	isPlaceOf: (item: T) => boolean,
	holds: (item: T) => boolean
): number {
	const place = items.findIndex(isPlaceOf);
	return place >= 0 ? place : queuePositionFrom(items, from, holds);
}

function queuePositionFrom<T>(
	items: readonly T[],
	from: number,
	holds: (item: T) => boolean
): number {
	for (let step = 0; step < items.length; step++) {
		const index = (from + step) % items.length;
		if (holds(items[index])) return index;
	}
	return -1;
}

// Whether the transport holds an entry's take: the same generation.
export function holdsEntryTake(current: PlaybackInfo, entry: PlaylistEntryItem): boolean {
	return current.generation.id === entry.generation_id;
}

export function currentPlaylistIndex(
	ctx: { entries: PlaylistEntryItem[]; index: number },
	current: PlaybackInfo | null = audioPlayer.current
): number {
	if (!current) return ctx.index;
	const idx = queuePositionOf(
		ctx.entries,
		ctx.index,
		(entry) => playbackInfoOfEntry.get(entry) === current,
		(entry) => holdsEntryTake(current, entry)
	);
	return idx >= 0 ? idx : ctx.index;
}

function playlistEntryToGeneration(entry: PlaylistEntryItem): GenerationItem {
	return {
		id: entry.generation_id,
		song_id: entry.song_id,
		version_id: null,
		version_number: entry.version_number,
		generation_number: entry.generation_number,
		mp3_path: entry.mp3_path,
		wav_path: null,
		seed: entry.seed,
		status: 'completed',
		audio_duration_sec: entry.audio_duration,
		is_archived: false,
		is_picked: false,
		is_kept: true,
		is_shared: false,
		model_mode: entry.model_mode,
		whisper_text: null,
		whisper_cues: null,
		version_lyrics: entry.lyrics,
		scores: null,
		generation_params: null,
		created_at: ''
	};
}

export function playlistEntryToPlaybackInfo(entry: PlaylistEntryItem): PlaybackInfo {
	const known = playbackInfoOfEntry.get(entry);
	if (known) return known;
	const info: PlaybackInfo = {
		generation: playlistEntryToGeneration(entry),
		songId: entry.song_id,
		songTitle: entry.song_title,
		artist: entry.artist,
		albumTitle: entry.album_title,
		lyrics: entry.lyrics
	};
	playbackInfoOfEntry.set(entry, info);
	return info;
}

export function toPlaybackInfo(gen: GenerationItem, song: SongItem): PlaybackInfo {
	return {
		generation: gen,
		songId: song.id,
		songTitle: song.title,
		artist: song.artist,
		albumTitle: song.album_title,
		lyrics: gen.version_lyrics
	};
}

// What a tap on one of a song's takes queues: the song's playable takes in the
// take list's order, from the tapped one on. adjacentQueueTake wraps them, so
// the take before the tapped one plays last. Null where the tapped take is not
// playable. With no current version named, the groups hold every version
// newest first, Imported last: the list's order with every fold open.
export function songTakeQueue(song: SongItem, startGenerationId: string): SongQueue | null {
	const takes = takesInGroupOrder(groupTakes(song.generations, null)).filter(isPlayableTake);
	const index = takes.findIndex((gen) => gen.id === startGenerationId);
	if (index < 0) return null;
	const queued = takes.map((gen) => toPlaybackInfo(gen, song));
	return {
		type: 'song',
		songId: song.id,
		songTitle: song.title,
		takes: queued,
		inListOrder: queued,
		index
	};
}

// A take of a song queue that was archived, lost its audio or was deleted since
// the queue was built is skipped when its turn comes, never replaced
// (REQ-LISTENING-06, REQ-LIBRARY-07).
export function songQueueTakeIsGone(ctx: SongQueue, take: PlaybackInfo): boolean {
	const song = get(songList).find((item) => item.id === ctx.songId);
	if (!song || !songTakesLoaded(song)) return false;
	const live = song.generations.find((gen) => gen.id === take.generation.id);
	return live === undefined || !isPlayableTake(live);
}

// The line after the last row promises a start over, which only a queue with
// at least two takes that can still play keeps: a lone one has no other to
// start over with.
function songQueueWraps(ctx: SongQueue): boolean {
	return ctx.takes.filter((take) => queueTakeCanPlay(ctx, take)).length >= 2;
}

export function albumQueueTake(song: SongItem, gen: GenerationItem): PlaybackInfo {
	return playlistEntryToPlaybackInfo(toAlbumQueueEntry(song, gen));
}

export function toAlbumQueueEntry(song: SongItem, gen: GenerationItem): PlaylistEntryItem {
	return {
		id: `album:${song.id}:${gen.id}`,
		position: 0,
		generation_id: gen.id,
		song_id: song.id,
		song_title: song.title,
		album_title: song.album_title,
		artist: song.artist,
		generation_number: gen.generation_number,
		version_number: gen.version_number,
		is_picked: gen.is_picked,
		audio_duration: gen.audio_duration_sec,
		mp3_path: gen.mp3_path,
		seed: gen.seed,
		model_mode: gen.model_mode,
		lyrics: gen.version_lyrics
	};
}

export type QueueDirection = -1 | 1;

type NextQueueTake =
	{ kind: 'take'; index: number; take: PlaybackInfo } | { kind: 'window-end' } | { kind: 'none' };

const NO_NEXT_TAKE: NextQueueTake = { kind: 'none' };

export function adjacentQueueTake(
	ctx: QueueContext,
	current: PlaybackInfo | null,
	direction: QueueDirection = 1
): NextQueueTake {
	if (ctx.type === 'playlist') {
		return firstPlayableInDirection(
			ctx,
			{
				index: currentPlaylistIndex(ctx, current),
				length: ctx.entries.length,
				takeAt: (index) => playlistEntryToPlaybackInfo(ctx.entries[index]),
				endsWithItsWindow: false
			},
			direction
		);
	}
	const index = nativeTakeIndex(ctx, current);
	const takes = ctx.takes;
	if (index < 0 || takes === undefined) return NO_NEXT_TAKE;
	return firstPlayableInDirection(
		ctx,
		{
			index,
			length: takes.length,
			takeAt: (place) => takes[place],
			endsWithItsWindow:
				direction === 1 && ctx.type === 'library' && !get(libraryQueueSkippedComplete)
		},
		direction
	);
}

function queueTakeCanPlay(ctx: QueueContext, take: PlaybackInfo): boolean {
	return !ctx.skipped?.has(take) && !(ctx.type === 'song' && songQueueTakeIsGone(ctx, take));
}

interface QueuePlace {
	index: number;
	length: number;
	takeAt: (index: number) => PlaybackInfo;
	endsWithItsWindow: boolean;
}

function firstPlayableInDirection(
	ctx: QueueContext,
	place: QueuePlace,
	direction: QueueDirection
): NextQueueTake {
	const windowEnd: NextQueueTake = place.endsWithItsWindow ? { kind: 'window-end' } : NO_NEXT_TAKE;
	for (let step = 1; step < place.length; step++) {
		if (place.endsWithItsWindow && place.index + step === place.length) return windowEnd;
		const index = (place.index + direction * step + place.length) % place.length;
		const take = place.takeAt(index);
		if (queueTakeCanPlay(ctx, take)) return { kind: 'take', index, take };
	}
	return windowEnd;
}

// An album queue plays each song's pick, so a take picked for a song still
// ahead takes that song's place in the queue. Songs already played keep the
// take they played, and a move within the queue keeps curation going, as
// playNativeIndex does. Returns whether the queue changed, so the caller can
// move the preload after it.
export function followPicksAheadInAlbumQueue(songs: SongItem[]): boolean {
	const ctx = get(queueContext);
	if (ctx.type !== 'album' || !ctx.takes) return false;
	const currentIndex = nativeTakeIndex(ctx, audioPlayer.current);
	if (currentIndex < 0) return false;
	const songsById = new Map(songs.map((song) => [song.id, song]));
	let repicked = false;
	const takes = ctx.takes.map((take, index) => {
		if (index <= currentIndex) return take;
		const song = songsById.get(take.songId);
		const picked = song && pickedTake(song);
		if (!song || !picked || picked.id === take.generation.id) return take;
		repicked = true;
		return albumQueueTake(song, picked);
	});
	if (!repicked) return false;
	queueContext.set({ ...ctx, takes, index: currentIndex });
	return true;
}

// --- Queue view model (Now Playing's queue panel) ---

export interface QueueRowItem {
	key: string;
	songId: string;
	songTitle: string;
	generationId: string;
	durationSec: number | null;
	versionNumber: number | null;
	generationNumber: number;
}

export interface QueueViewModel {
	items: QueueRowItem[];
	currentIndex: number;
	upNext: QueueRowItem | null;
	// The song a wrapping queue starts over with, named by one quiet line
	// after its last row.
	again?: string;
}

function upNextItem(
	items: QueueRowItem[],
	ctx: QueueContext,
	current: PlaybackInfo | null
): QueueRowItem | null {
	const next = adjacentQueueTake(ctx, current);
	return next.kind === 'take' ? (items[next.index] ?? null) : null;
}

// Every queue row reads its own measured length, never a stand-in --
// neither the "auto" (0) request parameter nor another row's estimate.
// Unmeasured is unmeasured: the row carries no duration until one exists.
function nativeQueueItem(take: PlaybackInfo): QueueRowItem {
	return {
		key: `${take.songId}:${take.generation.id}`,
		songId: take.songId,
		songTitle: take.songTitle,
		generationId: take.generation.id,
		durationSec: take.generation.audio_duration_sec ?? null,
		versionNumber: take.generation.version_number,
		generationNumber: take.generation.generation_number
	};
}

function playlistQueueItem(entry: PlaylistEntryItem): QueueRowItem {
	return {
		key: entry.id,
		songId: entry.song_id,
		songTitle: entry.song_title,
		generationId: entry.generation_id,
		durationSec: entry.audio_duration ?? null,
		versionNumber: entry.version_number,
		generationNumber: entry.generation_number
	};
}

// Pure projection of the playback queue for Now Playing's queue panel. A
// classic-mode context (library/album) whose native queue has not finished
// building yet carries no `takes` — that renders "current only, no up next"
// in the caller instead of an empty queue list, since the current take's
// title/duration still come from the caller's own `PlaybackInfo` prop.
export function buildQueueViewModel(
	ctx: QueueContext,
	current: PlaybackInfo | null
): QueueViewModel {
	if (ctx.type === 'playlist') {
		const items = ctx.entries.map((entry) => playlistQueueItem(entry));
		const currentIndex = currentPlaylistIndex(ctx, current);
		return { items, currentIndex, upNext: upNextItem(items, ctx, current) };
	}
	if (!ctx.takes || ctx.takes.length === 0) {
		return { items: [], currentIndex: -1, upNext: null };
	}
	const items = ctx.takes.map((take) => nativeQueueItem(take));
	const currentIndex = nativeTakeIndex(ctx, current);
	const queue = { items, currentIndex, upNext: upNextItem(items, ctx, current) };
	return ctx.type === 'song' && songQueueWraps(ctx) ? { ...queue, again: ctx.songTitle } : queue;
}
