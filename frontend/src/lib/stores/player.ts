import { writable, derived, get } from 'svelte/store';
import { ApiError } from '$lib/api/fetch';
import {
	createLibraryQueueStreamSnapshot,
	createQueueStreamSnapshot,
	fetchLibraryPoolQueue,
	fetchSong
} from '$lib/api/client';
import type {
	AlbumItem,
	GenerationItem,
	LibraryPoolTakeItem,
	PlaylistDetailItem,
	PlaylistEntryItem,
	QueueStreamManifest,
	QueueStreamSkipItem,
	SongItem
} from '$lib/api/types';
import {
	audioPlayer,
	type PlaybackInfo,
	type StreamFallbackState
} from '$lib/services/audioPlayer.svelte';
import { setupMediaSessionHandlers, updateMediaSessionMetadata } from '$lib/services/mediaSession';
import { type OpenCollection, openCollection } from '$lib/stores/collection';
import {
	albumList,
	albumSongsErrorMessage,
	loadSongsForAlbum,
	songList,
	upsertSongInList
} from '$lib/stores/libraryData';
import { addToast } from '$lib/stores/toast';
import {
	desktopNowPlayingSurface,
	LIBRARY_TAKE_POOL_LABELS,
	libraryTakePool,
	queuePlaybackMode,
	setDesktopNowPlayingSurface,
	setLibraryTakePool,
	shouldUseQueueStream,
	type LibraryTakePool
} from '$lib/stores/playbackSettings';
import { selectedPlaylistDetail } from '$lib/stores/playlists';
import { closeSidebar } from '$lib/stores/ui';
import {
	ALBUM_ROW_ARCHIVED_ONLY_TOAST,
	ALBUM_ROW_NO_TAKE_TOAST,
	LIBRARY_QUEUE_EMPTY_TITLE,
	QUEUE_STREAM_EMPTY_POOL_PREFIX,
	QUEUE_STREAM_UNPLAYABLE_START_DETAIL,
	QUEUE_TAKE_MISSING_TOAST,
	RAIL_LIBRARY_LABEL,
	SHUFFLE_SCOPE_ALBUM,
	SHUFFLE_SCOPE_LIBRARY,
	SHUFFLE_SCOPE_PLAYLIST
} from '$lib/constants';
import {
	NOW_PLAYING_SHUFFLE_DISABLE_PREFIX,
	NOW_PLAYING_SHUFFLE_LABEL_PREFIX,
	type NowPlayingSurfaceKind
} from '$lib/constants/now-playing';

// --- Browsing state ---
export const selectedAlbumId = writable<string | null>(null);
export const selectedSongId = writable<string | null>(null);
export const selectedGenerationId = writable<string | null>(null);

export const selectedSong = derived(
	[songList, selectedSongId],
	([$songs, $id]) => $songs.find((s) => s.id === $id) ?? null
);

export const selectedGeneration = derived(
	[selectedSong, selectedGenerationId],
	([$song, $genId]) => {
		if (!$song || !$genId) return null;
		return $song.generations.find((g) => g.id === $genId) ?? null;
	}
);

export const filteredSongs = derived([songList, selectedAlbumId], ([$songs, $albumId]) =>
	$albumId ? $songs.filter((s) => s.album_id === $albumId) : $songs
);

export function selectAlbum(albumId: string | null): void {
	selectedAlbumId.set(albumId);
	selectedSongId.set(null);
	selectedGenerationId.set(null);
}

export function selectSong(songId: string): void {
	selectedSongId.set(songId);
	selectedGenerationId.set(null);
}

const songGenerationLoads = new Map<string, Promise<void>>();

export async function ensureGenerationsLoaded(songId: string): Promise<void> {
	const songs = get(songList);
	const song = songs.find((s) => s.id === songId);
	// A song whose loaded takes already match generation_count needs no fetch. A
	// partial retain (fewer takes than the count) or a song not yet in the list
	// must be fetched; otherwise a later snapshot can hide a take created while
	// sync was stopped.
	if (song && song.generations.length >= song.generation_count) return;
	const inflight = songGenerationLoads.get(songId);
	if (inflight) return inflight;
	const load = (async () => {
		try {
			const full = await fetchSong(songId);
			upsertSongInList(full);
		} finally {
			songGenerationLoads.delete(songId);
		}
	})();
	songGenerationLoads.set(songId, load);
	await load;
}

export function clearGenerationSelection(): void {
	selectedGenerationId.set(null);
}

// --- Playback queue context ---

// A playlist queue names the playlist it was built from. The queue is the
// only owner of that name: navigation may open, close, or replace the
// playlist detail while the queue keeps playing, so nothing downstream may
// read the open collection to label what is playing.
export interface PlaylistQueueSource {
	id: string;
	title: string;
}

export type QueueContext =
	| { type: 'library'; takes?: PlaybackInfo[]; index?: number }
	| { type: 'album'; albumId: string; takes?: PlaybackInfo[]; index?: number }
	| {
			type: 'playlist';
			playlist: PlaylistQueueSource;
			entries: PlaylistEntryItem[];
			index: number;
	  };

export const queueContext = writable<QueueContext>({ type: 'library' });

const SHUFFLE_STORAGE_KEY = 'queueShuffleEnabled';

function readStoredShuffle(): boolean {
	if (typeof window === 'undefined') return false;
	return localStorage.getItem(SHUFFLE_STORAGE_KEY) === 'true';
}

export const shuffleEnabled = writable(readStoredShuffle());

export function setShuffle(enabled: boolean): void {
	shuffleEnabled.set(enabled);
	if (typeof window !== 'undefined') {
		localStorage.setItem(SHUFFLE_STORAGE_KEY, String(enabled));
	}
}

export async function toggleShuffle(): Promise<void> {
	setShuffle(!get(shuffleEnabled));
	await rebuildQueueAfterShuffleToggle();
}

function shuffleScopeLabel(ctx: QueueContext): string {
	if (ctx.type === 'playlist') return SHUFFLE_SCOPE_PLAYLIST;
	if (ctx.type === 'album') return SHUFFLE_SCOPE_ALBUM;
	return SHUFFLE_SCOPE_LIBRARY;
}

// Every shuffle control (transport bar, Now Playing) names the same scope
// from the same place, so the two can never disagree about what a toggle
// would shuffle.
export const shuffleLabel = derived([shuffleEnabled, queueContext], ([$enabled, $ctx]) =>
	$enabled
		? `${NOW_PLAYING_SHUFFLE_DISABLE_PREFIX} (${shuffleScopeLabel($ctx)})`
		: `${NOW_PLAYING_SHUFFLE_LABEL_PREFIX} ${shuffleScopeLabel($ctx)}`
);

export type PlayStartNotice = 'idle' | 'building' | 'empty' | 'error';
export const playStartNotice = writable<PlayStartNotice>('idle');
export const libraryQueueSkipped = writable<QueueStreamSkipItem[]>([]);
export const libraryQueueSkippedComplete = writable(true);
export const windowEnded = writable(false);

function clearWindowEnd(): void {
	windowEnded.set(false);
}

function clearLibraryQueueSkipFeedback(): void {
	libraryQueueSkipped.set([]);
	libraryQueueSkippedComplete.set(true);
}

export async function chooseLibraryTakePool(pool: LibraryTakePool): Promise<void> {
	setLibraryTakePool(pool);
	await rebuildLibraryQueueKeepingPlace();
}

function librarySnapshotOpts(): { shuffle: boolean; pool: LibraryTakePool } {
	return { shuffle: get(shuffleEnabled), pool: get(libraryTakePool) };
}

function poolLabel(): string {
	return LIBRARY_TAKE_POOL_LABELS[get(libraryTakePool)];
}

function isEmptyPoolError(err: unknown): boolean {
	return (
		err instanceof ApiError &&
		err.status === 422 &&
		err.message.startsWith(QUEUE_STREAM_EMPTY_POOL_PREFIX)
	);
}

function isUnplayableStartError(err: unknown): boolean {
	return (
		err instanceof ApiError &&
		err.status === 422 &&
		err.message === QUEUE_STREAM_UNPLAYABLE_START_DETAIL
	);
}

function reportNothingPlayable(label: string, retry: () => Promise<void>): void {
	retryPlayIntent = retry;
	playStartNotice.set('empty');
	clearLibraryQueueSkipFeedback();
	addToast(`${LIBRARY_QUEUE_EMPTY_TITLE} (${label})`, 'error');
}

function albumTitle(albums: AlbumItem[], albumId: string): string {
	return albums.find((album) => album.id === albumId)?.title ?? '';
}

function libraryStreamFailureToast(err: unknown): string {
	if (isEmptyPoolError(err)) return `${LIBRARY_QUEUE_EMPTY_TITLE} (${poolLabel()})`;
	if (isUnplayableStartError(err)) return QUEUE_STREAM_UNPLAYABLE_START_DETAIL;
	return `${poolLabel()} queue failed. Press play to retry.`;
}

// --- Playback dispatch ---

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

export function playGeneration(
	gen: GenerationItem,
	song: SongItem,
	opts: { restart?: boolean } = {}
): void {
	clearWindowEnd();
	clearLibraryQueueSkipFeedback();
	const info = toPlaybackInfo(gen, song);
	if (opts.restart) audioPlayer.load(info, { restart: true });
	else audioPlayer.load(info);
}

function shuffledWithStart<T>(items: T[], startIndex: number): { items: T[]; startIndex: number } {
	if (!get(shuffleEnabled) || items.length <= 1) return { items, startIndex };
	const start = items[startIndex] ?? items[0];
	const rest = items.filter((_, index) => index !== startIndex);
	for (let i = rest.length - 1; i > 0; i--) {
		const j = Math.floor(Math.random() * (i + 1));
		[rest[i], rest[j]] = [rest[j], rest[i]];
	}
	return { items: [start, ...rest], startIndex: 0 };
}

// A failed stream start remembers what the listener actually asked for, so the
// "press play to retry" affordance replays that exact intent instead of falling
// back to an unrotated default queue (which starts at library track 1).
let retryPlayIntent: (() => Promise<void>) | null = null;

export async function retryLastPlayIntent(): Promise<boolean> {
	const intent = retryPlayIntent;
	if (!intent) return false;
	await intent();
	return true;
}

let playStartSeq = 0;
let playStartAbort: AbortController | null = null;

function beginPlayStart(): { seq: number; signal: AbortSignal } {
	playStartAbort?.abort();
	playStartAbort = new AbortController();
	playStartSeq += 1;
	retryPlayIntent = null;
	return { seq: playStartSeq, signal: playStartAbort.signal };
}

function playStartIsCurrent(seq: number): boolean {
	return seq === playStartSeq;
}

function poolTakeToPlaybackInfo(take: LibraryPoolTakeItem): PlaybackInfo {
	return {
		generation: {
			id: take.generation_id,
			song_id: take.song_id,
			version_id: null,
			version_number: null,
			generation_number: take.generation_number,
			mp3_path: take.mp3_path,
			wav_path: null,
			seed: take.seed,
			status: 'completed',
			is_archived: false,
			is_picked: take.is_picked,
			is_kept: take.is_kept,
			is_shared: false,
			model_mode: take.model_mode,
			whisper_text: null,
			whisper_cues: null,
			version_lyrics: take.lyrics,
			scores: null,
			generation_params: null,
			created_at: ''
		},
		songId: take.song_id,
		songTitle: take.song_title,
		artist: take.artist,
		albumTitle: take.album_title,
		lyrics: take.lyrics
	};
}

function loadNativeTake(
	info: PlaybackInfo,
	opts: { restart?: boolean; startAt?: number } = {}
): void {
	clearWindowEnd();
	if (opts.startAt !== undefined) {
		audioPlayer.load(info, { restart: opts.restart ?? true, startAt: opts.startAt });
		return;
	}
	if (opts.restart) {
		audioPlayer.load(info, { restart: true });
		return;
	}
	audioPlayer.load(info);
}

function playNativeLibraryTakes(
	takes: PlaybackInfo[],
	index: number,
	resumeAtTrackTime?: number
): void {
	queueContext.set({ type: 'library', takes, index });
	loadNativeTake(takes[index], { restart: true, startAt: resumeAtTrackTime });
}

function playNativeAlbumTakes(
	albumId: string,
	takes: PlaybackInfo[],
	index: number,
	resumeAtTrackTime?: number
): void {
	queueContext.set({ type: 'album', albumId, takes, index });
	loadNativeTake(takes[index], { restart: true, startAt: resumeAtTrackTime });
}

function nativeTakeIndex(
	ctx: Exclude<QueueContext, { type: 'playlist' }>,
	current: PlaybackInfo | null
): number {
	if (!ctx.takes || ctx.takes.length === 0) return -1;
	if (typeof ctx.index === 'number' && current) {
		const indexed = ctx.takes[ctx.index];
		if (
			indexed?.generation.id === current.generation.id &&
			indexed.generation.mp3_path === current.generation.mp3_path
		) {
			return ctx.index;
		}
	}
	if (!current) return ctx.index ?? 0;
	return ctx.takes.findIndex(
		(take) =>
			take.generation.id === current.generation.id &&
			take.generation.mp3_path === current.generation.mp3_path
	);
}

function playNativeIndex(ctx: Exclude<QueueContext, { type: 'playlist' }>, index: number): void {
	const takes = ctx.takes;
	if (!takes || index < 0 || index >= takes.length) return;
	if (ctx.type === 'library') {
		queueContext.set({ type: 'library', takes, index });
	} else if (ctx.type === 'album') {
		queueContext.set({ type: 'album', albumId: ctx.albumId, takes, index });
	}
	loadNativeTake(takes[index]);
}

export async function playLibraryFromGeneration(
	gen: GenerationItem,
	opts: { resumeAtTrackTime?: number } = {}
): Promise<void> {
	const { seq, signal } = beginPlayStart();
	queueContext.set({ type: 'library' });
	playStartNotice.set('building');
	clearLibraryQueueSkipFeedback();
	clearWindowEnd();
	let queue;
	try {
		queue = await fetchLibraryPoolQueue({
			startGenerationId: gen.id,
			...librarySnapshotOpts(),
			signal
		});
	} catch (err) {
		if (!playStartIsCurrent(seq)) return;
		retryPlayIntent = () => playLibraryFromGeneration(gen, opts);
		playStartNotice.set(isEmptyPoolError(err) ? 'empty' : 'error');
		clearLibraryQueueSkipFeedback();
		addToast(libraryStreamFailureToast(err), 'error');
		return;
	}
	if (!playStartIsCurrent(seq)) return;
	const takes = queue.takes.map(poolTakeToPlaybackInfo);
	const startIndex = takes.findIndex((take) => take.generation.id === gen.id);
	if (startIndex < 0) {
		retryPlayIntent = () => playLibraryFromGeneration(gen, opts);
		playStartNotice.set('error');
		clearLibraryQueueSkipFeedback();
		addToast(QUEUE_TAKE_MISSING_TOAST, 'error');
		return;
	}
	playStartNotice.set('idle');
	libraryQueueSkipped.set(queue.skipped ?? []);
	libraryQueueSkippedComplete.set(queue.skipped_complete ?? true);
	playNativeLibraryTakes(takes, startIndex, opts.resumeAtTrackTime);
}

export async function playLibrary(opts: { resumeAtTrackTime?: number } = {}): Promise<void> {
	const { seq, signal } = beginPlayStart();
	queueContext.set({ type: 'library' });
	playStartNotice.set('building');
	clearLibraryQueueSkipFeedback();
	clearWindowEnd();
	let queue;
	try {
		queue = await fetchLibraryPoolQueue({
			startGenerationId: null,
			...librarySnapshotOpts(),
			signal
		});
	} catch (err) {
		if (!playStartIsCurrent(seq)) return;
		retryPlayIntent = () => playLibrary(opts);
		playStartNotice.set(isEmptyPoolError(err) ? 'empty' : 'error');
		clearLibraryQueueSkipFeedback();
		addToast(libraryStreamFailureToast(err), 'error');
		return;
	}
	if (!playStartIsCurrent(seq)) return;
	if (queue.takes.length === 0) {
		reportNothingPlayable(poolLabel(), () => playLibrary(opts));
		return;
	}
	playStartNotice.set('idle');
	libraryQueueSkipped.set(queue.skipped ?? []);
	libraryQueueSkippedComplete.set(queue.skipped_complete ?? true);
	playNativeLibraryTakes(queue.takes.map(poolTakeToPlaybackInfo), 0, opts.resumeAtTrackTime);
}

export type IdlePlayTarget =
	| { type: 'playlist'; label: string }
	| { type: 'album'; label: string; albumId: string }
	| { type: 'library'; label: string };

// The idle target follows the single navigation collection (stores/collection.ts)
// rather than the album/song selection tuple it used to: a song open inside an
// album keeps that album as the idle target instead of falling back to the
// library pool, because the open collection stays the album the whole time a
// song within it is open (see navigation.ts's ensureCollectionMatchesSong).
export function idlePlayTarget(input: {
	collection: OpenCollection | null;
	playlist: PlaylistDetailItem | null;
	albums: AlbumItem[];
}): IdlePlayTarget {
	if (input.collection?.kind === 'playlist') {
		// A playlist whose detail failed to load (or hasn't loaded yet) has no
		// title to show and nothing to natively play — fall back to the named
		// library target instead of an empty label and a dead Play button.
		if (!input.playlist) return { type: 'library', label: RAIL_LIBRARY_LABEL };
		return { type: 'playlist', label: input.playlist.title };
	}
	if (input.collection?.kind === 'album') {
		return {
			type: 'album',
			label: albumTitle(input.albums, input.collection.id),
			albumId: input.collection.id
		};
	}
	return { type: 'library', label: RAIL_LIBRARY_LABEL };
}

export async function playIdleStart(): Promise<void> {
	const target = idlePlayTarget({
		collection: get(openCollection),
		playlist: get(selectedPlaylistDetail),
		albums: get(albumList)
	});
	if (target.type === 'playlist') {
		const playlist = get(selectedPlaylistDetail);
		if (!playlist) return;
		playPlaylist(playlist);
		return;
	}
	if (target.type === 'album') {
		await playAlbum(target.albumId);
		return;
	}
	await playLibrary();
}

async function rebuildLibraryQueueKeepingPlace(): Promise<void> {
	if (!audioPlayer.current) return;
	if (get(queueContext).type !== 'library') return;
	await playLibraryFromGeneration(audioPlayer.current.generation, {
		resumeAtTrackTime: audioPlayer.currentTime
	});
}

async function rebuildQueueAfterShuffleToggle(): Promise<void> {
	if (!audioPlayer.current) return;
	const current = audioPlayer.current;
	const trackTime = audioPlayer.currentTime;
	const ctx = get(queueContext);
	if (ctx.type === 'library') {
		await playLibraryFromGeneration(current.generation, { resumeAtTrackTime: trackTime });
		return;
	}
	if (ctx.type === 'album') {
		const song = get(songList).find((item) => item.id === current.songId);
		if (!song) return;
		await playAlbumFromGeneration(ctx.albumId, song, current.generation, {
			resumeAtTrackTime: trackTime
		});
		return;
	}
	startPlaylistQueue(ctx.playlist, ctx.entries, currentPlaylistIndex(ctx, current), {
		restart: true,
		resumeAtTrackTime: trackTime
	});
}

function queueSongs(): SongItem[] {
	const ctx = get(queueContext);
	const songs = get(songList);
	if (ctx.type === 'album') return songs.filter((s) => s.album_id === ctx.albumId);
	return songs;
}

export function canPlayPrevSong(
	current: PlaybackInfo | null,
	songs: SongItem[],
	ctx: QueueContext
): boolean {
	if (audioPlayer.mode === 'stream') return audioPlayer.canPrevStreamTrack;
	if (!current) return false;
	if (ctx.type === 'playlist') return ctx.entries.length > 1;
	if (ctx.takes && ctx.takes.length > 0) return ctx.takes.length > 1;
	if (ctx.type === 'library') return false;
	const pool = songs.filter((s) => s.album_id === ctx.albumId);
	return pool.filter((s) => s.generation_count > 0).length > 1;
}

export function canPlayNextSong(
	current: PlaybackInfo | null,
	songs: SongItem[],
	ctx: QueueContext,
	_shuffle = false
): boolean {
	if (audioPlayer.mode === 'stream') return audioPlayer.canNextStreamTrack;
	if (!current) return false;
	if (ctx.type === 'playlist') {
		return ctx.entries.length > 1;
	}
	if (ctx.type === 'library' && ctx.takes && ctx.takes.length > 0) {
		if (!get(libraryQueueSkippedComplete)) {
			const index = nativeTakeIndex(ctx, current);
			return index >= 0 && index < ctx.takes.length - 1;
		}
		return ctx.takes.length > 1;
	}
	if (ctx.takes && ctx.takes.length > 0) return ctx.takes.length > 1;
	if (ctx.type === 'library') return false;
	const pool = songs.filter((s) => s.album_id === ctx.albumId);
	return pool.filter((s) => s.id !== current.songId && s.generation_count > 0).length > 0;
}

// Archived takes are not playable (their rows offer no play affordance), so
// they never stand in as a song's take in a queue either.
function bestGen(song: SongItem): GenerationItem | undefined {
	const playable = song.generations.filter((gen) => !gen.is_archived);
	return playable.find((gen) => gen.is_picked) ?? playable[0];
}

function toAlbumQueueEntry(song: SongItem, gen: GenerationItem): PlaylistEntryItem {
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
		audio_duration: song.audio_duration ?? null,
		mp3_path: gen.mp3_path,
		seed: gen.seed,
		model_mode: gen.model_mode,
		lyrics: gen.version_lyrics
	};
}

function albumSongsInOrder(albumId: string): SongItem[] {
	return get(songList)
		.filter((s) => s.album_id === albumId)
		.sort((a, b) => a.track_number - b.track_number);
}

async function collectAlbumEntries(
	albumId: string,
	seq: number,
	start?: { song: SongItem; gen: GenerationItem }
): Promise<PlaylistEntryItem[] | null> {
	const entries: PlaylistEntryItem[] = [];
	for (const song of albumSongsInOrder(albumId)) {
		if (!playStartIsCurrent(seq)) return null;
		if (song.generation_count === 0) continue;
		await ensureGenerationsLoaded(song.id);
		if (!playStartIsCurrent(seq)) return null;
		const fresh = get(songList).find((s) => s.id === song.id);
		if (!fresh) continue;
		const gen =
			start && fresh.id === start.song.id
				? (fresh.generations.find((g) => g.id === start.gen.id) ?? start.gen)
				: bestGen(fresh);
		if (!gen) continue;
		entries.push({ ...toAlbumQueueEntry(fresh, gen), position: entries.length });
	}
	return entries;
}

function setAlbumQueueTakes(
	albumId: string,
	entries: PlaylistEntryItem[],
	startGenerationId: string | undefined
): void {
	if (entries.length === 0) return;
	const startIndex = startGenerationId
		? Math.max(
				0,
				entries.findIndex((entry) => entry.generation_id === startGenerationId)
			)
		: 0;
	const ordered = shuffledWithStart(entries, startIndex);
	queueContext.set({
		type: 'album',
		albumId,
		takes: ordered.items.map(playlistEntryToPlaybackInfo),
		index: ordered.startIndex
	});
}

export function currentPlaylistIndex(
	ctx: { entries: PlaylistEntryItem[]; index: number },
	current: PlaybackInfo | null = audioPlayer.current
): number {
	if (!current) return ctx.index;
	const indexedEntry = ctx.entries[ctx.index];
	if (
		indexedEntry?.generation_id === current.generation.id &&
		indexedEntry.mp3_path === current.generation.mp3_path
	) {
		return ctx.index;
	}
	const idx = ctx.entries.findIndex(
		(entry) =>
			entry.generation_id === current.generation.id &&
			entry.mp3_path === current.generation.mp3_path
	);
	return idx >= 0 ? idx : ctx.index;
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
}

function nextQueueItem(items: QueueRowItem[], currentIndex: number): QueueRowItem | null {
	if (items.length <= 1 || currentIndex < 0) return null;
	return items[(currentIndex + 1) % items.length] ?? null;
}

// Every queue row reads its length from the same place: the take's own
// duration when the row carries one, and the song's latest-version duration
// as the fallback for rows that do not (library-pool takes, and album rows
// built before the take's params were loaded).
function queueRowDurationSec(
	takeDurationSec: number | null | undefined,
	songs: SongItem[],
	songId: string
): number | null {
	return takeDurationSec ?? songs.find((s) => s.id === songId)?.audio_duration ?? null;
}

function nativeQueueItem(take: PlaybackInfo, songs: SongItem[]): QueueRowItem {
	return {
		key: `${take.songId}:${take.generation.id}`,
		songId: take.songId,
		songTitle: take.songTitle,
		generationId: take.generation.id,
		durationSec: queueRowDurationSec(
			take.generation.generation_params?.audio_duration,
			songs,
			take.songId
		),
		versionNumber: take.generation.version_number,
		generationNumber: take.generation.generation_number
	};
}

function playlistQueueItem(entry: PlaylistEntryItem, songs: SongItem[]): QueueRowItem {
	return {
		key: entry.id,
		songId: entry.song_id,
		songTitle: entry.song_title,
		generationId: entry.generation_id,
		durationSec: queueRowDurationSec(entry.audio_duration, songs, entry.song_id),
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
	current: PlaybackInfo | null,
	songs: SongItem[]
): QueueViewModel {
	if (ctx.type === 'playlist') {
		const items = ctx.entries.map((entry) => playlistQueueItem(entry, songs));
		const currentIndex = currentPlaylistIndex(ctx, current);
		return { items, currentIndex, upNext: nextQueueItem(items, currentIndex) };
	}
	if (!ctx.takes || ctx.takes.length === 0) {
		return { items: [], currentIndex: -1, upNext: null };
	}
	const items = ctx.takes.map((take) => nativeQueueItem(take, songs));
	const currentIndex = nativeTakeIndex(ctx, current);
	return { items, currentIndex, upNext: nextQueueItem(items, currentIndex) };
}

// Plays the queue row at `index` in whatever queue context is active. A
// shared-link stream, native (library/album), and playlist contexts each
// keep their own index semantics, so this dispatches to the matching
// internal player rather than duplicating that logic at the call site.
export function jumpToQueueIndex(index: number): void {
	if (audioPlayer.mode === 'stream') {
		audioPlayer.seekToStreamTrack(index);
		return;
	}
	const ctx = get(queueContext);
	if (ctx.type === 'playlist') {
		playPlaylistIndex(ctx, index, { restart: true });
		return;
	}
	playNativeIndex(ctx, index);
}

// Which Now Playing surface is showing, and which of its right-panel tabs it
// opens on. Owned here (not by PlayerBar or the layout, which only read them)
// so any surface — a take row, a deep link — can open Now Playing straight to
// the judging panel without routing through PlayerBar's own click handlers.
export type NowPlayingSurface = 'closed' | NowPlayingSurfaceKind;
export const nowPlayingSurface = writable<NowPlayingSurface>('closed');
export const nowPlayingOpen = derived(nowPlayingSurface, (surface) => surface !== 'closed');
export type NowPlayingPanel = 'queue' | 'take';
export const nowPlayingPanel = writable<NowPlayingPanel>('queue');

// Whether the viewport has room for the docked panel beside the workspace.
// The layout owns that media query — the same width/pointer switch the frame
// stacks on — and reports it here, so opening and Escape resolve the surface
// from one fact instead of each re-reading the breakpoint.
export const nowPlayingDockable = writable(false);

nowPlayingDockable.subscribe((dockable) => {
	if (!dockable && get(nowPlayingSurface) === 'docked') nowPlayingSurface.set('full');
});

// The element to return focus to when Now Playing closes. PlayerBar
// registers its own "Now Playing" button here once on mount — every opener
// (PlayerBar's button, a TakesList row, NowPlayingTake's "Use as reference")
// shares that single restore target instead of each tracking its own.
let nowPlayingFocusTrigger: HTMLElement | null = null;
let restoreFocusOnRegister = false;

export function registerNowPlayingTrigger(el: HTMLElement | null): void {
	nowPlayingFocusTrigger = el;
	if (!el || !restoreFocusOnRegister) return;
	restoreFocusOnRegister = false;
	el.focus();
}

// Leaving the full surface remounts the transport bar it hides, so the button
// to hand focus back to does not exist yet at the moment of closing; it
// arrives with the bar and registerNowPlayingTrigger delivers the focus then.
function restoreNowPlayingTriggerFocus(closedFromFullSurface: boolean): void {
	const trigger = nowPlayingFocusTrigger;
	if (trigger) {
		queueMicrotask(() => trigger.focus());
		return;
	}
	restoreFocusOnRegister = closedFromFullSurface;
}

// The single open/close owner for Now Playing: every surface that opens or
// closes it (PlayerBar's button, a TakesList row via playTakeAndShowNowPlaying,
// NowPlayingTake's "Use as reference") routes through these two functions
// instead of poking `nowPlayingSurface`/`nowPlayingPanel` directly, so closing
// the mobile rail drawer on open and restoring focus on close happen exactly
// once, the same way, regardless of entry point.
export function openNowPlaying(panel: NowPlayingPanel): void {
	closeSidebar();
	nowPlayingPanel.set(panel);
	nowPlayingSurface.set(get(nowPlayingDockable) ? get(desktopNowPlayingSurface) : 'full');
}

export function closeNowPlaying(): void {
	const surface = get(nowPlayingSurface);
	if (surface === 'closed') return;
	nowPlayingSurface.set('closed');
	restoreNowPlayingTriggerFocus(surface === 'full');
}

// Docked versus full is a surface choice, not an open or close, and the
// choice is remembered so the next open lands where the listener last was.
export function expandNowPlaying(): void {
	chooseDesktopSurface('full');
}

export function dockNowPlaying(): void {
	chooseDesktopSurface('docked');
}

function chooseDesktopSurface(surface: NowPlayingSurfaceKind): void {
	setDesktopNowPlayingSurface(surface);
	nowPlayingSurface.set(surface);
}

// Escape leaves Now Playing one level at a time: the full surface falls back
// to the docked panel wherever there is room for one, and the docked panel —
// like a full surface on a compact viewport — closes.
export function escapeNowPlaying(): void {
	if (get(nowPlayingSurface) === 'full' && get(nowPlayingDockable)) {
		dockNowPlaying();
		return;
	}
	closeNowPlaying();
}

// The single playback entry point for a take row (TakesList, TakeStrip):
// toggles pause if the row's take is already playing, otherwise starts it
// through the active queue-playback mode (stream or classic), reporting any
// failure as a toast instead of throwing into the caller.
export async function playTake(gen: GenerationItem, song: SongItem): Promise<void> {
	if (audioPlayer.current?.generation.id === gen.id && audioPlayer.status === 'playing') {
		audioPlayer.toggle();
		return;
	}
	try {
		const albumId = get(selectedAlbumId);
		if (shouldUseQueueStream(get(queuePlaybackMode))) {
			if (albumId) {
				await playAlbumFromGeneration(albumId, song, gen);
				return;
			}
			await playLibraryFromGeneration(gen);
			return;
		}
		queueContext.set(albumId ? { type: 'album', albumId } : { type: 'library' });
		playGeneration(gen, song, { restart: true });
	} catch (e) {
		addToast(e instanceof Error ? e.message : 'Playback failed', 'error');
	}
}

// What a click on a take row means, wherever that row lives (the click rule
// of issue #140): play the take and surface Now Playing straight on its
// judging panel. The editor's takes list and a playlist's rows differ only in
// how playback starts, so both hand that start to this one action.
//
// A row body never stops the music. The take a row stands for is left
// running, and a paused one picks up where it stands rather than starting
// over, so clicking the row that is already loaded only brings up the panel.
// Pausing belongs to the row's own ▶ and to the transport.
async function playTakeRow(row: {
	alreadyLoaded: boolean;
	start: () => void | Promise<void>;
}): Promise<void> {
	if (row.alreadyLoaded) audioPlayer.play();
	else await row.start();
	openNowPlaying('take');
}

// Whether a take is the one the transport holds. The generation's id settles
// it: a take row hands over the generation itself, unlike a playlist entry,
// which names a file that a re-import can change under the same id.
function isTakeCurrent(gen: GenerationItem): boolean {
	return audioPlayer.current?.generation.id === gen.id;
}

export async function playTakeAndShowNowPlaying(
	gen: GenerationItem,
	song: SongItem
): Promise<void> {
	await playTakeRow({ alreadyLoaded: isTakeCurrent(gen), start: () => playTake(gen, song) });
}

export async function playPlaylistEntryAndShowNowPlaying(
	playlist: PlaylistDetailItem,
	index: number
): Promise<void> {
	const entry = playlist.entries[index];
	await playTakeRow({
		alreadyLoaded: entry !== undefined && isPlaylistEntryCurrent(entry),
		start: () => playPlaylistEntry(playlist, index)
	});
}

export async function playNextSong(): Promise<void> {
	if (audioPlayer.mode === 'stream') {
		audioPlayer.nextStreamTrack();
		return;
	}
	const ctx = get(queueContext);
	if (ctx.type === 'playlist') {
		const currentIndex = currentPlaylistIndex(ctx);
		if (ctx.entries.length <= 1) return;
		playPlaylistIndex(ctx, (currentIndex + 1) % ctx.entries.length);
		return;
	}
	if (ctx.takes && ctx.takes.length > 0) {
		const index = nativeTakeIndex(ctx, audioPlayer.current);
		if (index < 0) return;
		const atWindowEnd =
			ctx.type === 'library' && index === ctx.takes.length - 1 && !get(libraryQueueSkippedComplete);
		if (atWindowEnd) {
			windowEnded.set(true);
			return;
		}
		if (ctx.takes.length <= 1) return;
		playNativeIndex(ctx, (index + 1) % ctx.takes.length);
		return;
	}
	if (ctx.type === 'library') return;
	const cur = audioPlayer.current;
	if (!cur) return;
	const songs = queueSongs();
	const idx = songs.findIndex((s) => s.id === cur.songId);
	if (get(shuffleEnabled)) {
		const candidates = songs.filter((s) => s.id !== cur.songId && s.generation_count > 0);
		while (candidates.length > 0) {
			const next = candidates.splice(Math.floor(Math.random() * candidates.length), 1)[0];
			await ensureGenerationsLoaded(next.id);
			const fresh = get(songList).find((s) => s.id === next.id);
			const gen = fresh ? bestGen(fresh) : undefined;
			if (gen && fresh) {
				playGeneration(gen, fresh);
				return;
			}
		}
		return;
	}
	for (let offset = 1; offset <= songs.length; offset++) {
		const song = songs[(idx + offset + songs.length) % songs.length];
		if (!song || song.id === cur.songId || song.generation_count === 0) continue;
		await ensureGenerationsLoaded(song.id);
		const fresh = get(songList).find((s) => s.id === song.id);
		const gen = fresh ? bestGen(fresh) : undefined;
		if (gen && fresh) {
			playGeneration(gen, fresh);
			return;
		}
	}
}

export async function playPrevSong(): Promise<void> {
	if (audioPlayer.mode === 'stream') {
		audioPlayer.prevStreamTrack();
		return;
	}
	const ctx = get(queueContext);
	if (ctx.type === 'playlist') {
		const currentIndex = currentPlaylistIndex(ctx);
		if (ctx.entries.length > 1) {
			playPlaylistIndex(ctx, (currentIndex - 1 + ctx.entries.length) % ctx.entries.length);
		}
		return;
	}
	if (ctx.takes && ctx.takes.length > 0) {
		const index = nativeTakeIndex(ctx, audioPlayer.current);
		if (index < 0 || ctx.takes.length <= 1) return;
		playNativeIndex(ctx, (index - 1 + ctx.takes.length) % ctx.takes.length);
		return;
	}
	if (ctx.type === 'library') return;
	const cur = audioPlayer.current;
	if (!cur) return;
	const songs = queueSongs();
	const idx = songs.findIndex((s) => s.id === cur.songId);
	for (let offset = 1; offset <= songs.length; offset++) {
		const song = songs[(idx - offset + songs.length) % songs.length];
		if (!song || song.id === cur.songId || song.generation_count === 0) continue;
		await ensureGenerationsLoaded(song.id);
		const fresh = get(songList).find((s) => s.id === song.id);
		const gen = fresh ? bestGen(fresh) : undefined;
		if (gen && fresh) {
			playGeneration(gen, fresh);
			return;
		}
	}
}

// The album's opening take, which is not always the opening track's:
// `generation_count` counts archived takes too, so a track whose takes are
// all archived is skipped rather than taken as proof the album is
// unplayable. Returns null both when nothing is playable and when a newer
// play start superseded this one — the caller separates the two with its
// own playStartIsCurrent check. A rejected load (e.g. 429) is left
// uncaught here and propagates to the caller, which mirrors
// playAlbumSong's handling of the same call.
async function firstPlayableAlbumTake(
	albumId: string,
	seq: number
): Promise<{ song: SongItem; gen: GenerationItem } | null> {
	for (const song of albumSongsInOrder(albumId)) {
		if (song.generation_count === 0) continue;
		await ensureGenerationsLoaded(song.id);
		if (!playStartIsCurrent(seq)) return null;
		const fresh = get(songList).find((item) => item.id === song.id) ?? song;
		const gen = bestGen(fresh);
		if (gen) return { song: fresh, gen };
	}
	return null;
}

export async function playAlbum(albumId: string): Promise<void> {
	const { seq } = beginPlayStart();
	clearWindowEnd();
	clearLibraryQueueSkipFeedback();
	queueContext.set({ type: 'album', albumId });
	playStartNotice.set('building');
	if (albumSongsInOrder(albumId).length === 0) {
		await loadSongsForAlbum(albumId);
		if (!playStartIsCurrent(seq)) return;
	}
	let start: { song: SongItem; gen: GenerationItem } | null;
	try {
		start = await firstPlayableAlbumTake(albumId, seq);
	} catch (err) {
		if (!playStartIsCurrent(seq)) return;
		playStartNotice.set('idle');
		addToast(albumSongsErrorMessage(err), 'error');
		return;
	}
	if (!playStartIsCurrent(seq)) return;
	if (!start) {
		reportNothingPlayable(albumTitle(get(albumList), albumId), () => playAlbum(albumId));
		return;
	}
	playStartNotice.set('idle');
	playNativeAlbumTakes(
		albumId,
		[playlistEntryToPlaybackInfo(toAlbumQueueEntry(start.song, start.gen))],
		0
	);
	await loadSongsForAlbum(albumId);
	if (!playStartIsCurrent(seq)) return;
	const entries = await collectAlbumEntries(albumId, seq);
	if (entries === null || !playStartIsCurrent(seq)) return;
	setAlbumQueueTakes(albumId, entries, start.gen.id);
}

// A song row's play button inside an album. The row only knows the song's
// `generation_count`; the takes themselves are loaded per song, so a row
// tapped right after switching albums has none yet and must resolve one
// before the album queue can be built from it. Silence is the failure this
// replaces (#141): a song with no playable take now says so.
export async function playAlbumSong(albumId: string, song: SongItem): Promise<void> {
	try {
		await ensureGenerationsLoaded(song.id);
	} catch (err) {
		addToast(albumSongsErrorMessage(err), 'error');
		return;
	}
	const fresh = get(songList).find((item) => item.id === song.id) ?? song;
	const gen = bestGen(fresh);
	if (!gen) {
		addToast(
			fresh.generations.length > 0 ? ALBUM_ROW_ARCHIVED_ONLY_TOAST : ALBUM_ROW_NO_TAKE_TOAST,
			'error'
		);
		return;
	}
	await playAlbumFromGeneration(albumId, fresh, gen);
}

export async function playAlbumFromGeneration(
	albumId: string,
	song: SongItem,
	gen: GenerationItem,
	opts: { resumeAtTrackTime?: number } = {}
): Promise<void> {
	const { seq } = beginPlayStart();
	clearWindowEnd();
	clearLibraryQueueSkipFeedback();
	playNativeAlbumTakes(albumId, [toPlaybackInfo(gen, song)], 0, opts.resumeAtTrackTime);
	await loadSongsForAlbum(albumId);
	if (!playStartIsCurrent(seq)) return;
	const entries = await collectAlbumEntries(albumId, seq, { song, gen });
	if (entries === null || !playStartIsCurrent(seq)) return;
	setAlbumQueueTakes(albumId, entries, gen.id);
}

function playPlaylistIndex(
	ctx: { playlist: PlaylistQueueSource; entries: PlaylistEntryItem[] },
	newIndex: number,
	opts: { restart?: boolean; startAt?: number } = {}
): void {
	if (newIndex < 0 || newIndex >= ctx.entries.length) return;
	const entry = ctx.entries[newIndex];
	queueContext.set({
		type: 'playlist',
		playlist: ctx.playlist,
		entries: ctx.entries,
		index: newIndex
	});
	const info = playlistEntryToPlaybackInfo(entry);
	if (opts.startAt !== undefined) {
		audioPlayer.load(info, { restart: opts.restart ?? true, startAt: opts.startAt });
		return;
	}
	if (opts.restart) {
		audioPlayer.load(info, { restart: true });
		return;
	}
	audioPlayer.load(info);
}

function queueSourceOf(playlist: PlaylistDetailItem): PlaylistQueueSource {
	return { id: playlist.id, title: playlist.title };
}

// The idle transport Play on an open playlist. It keeps the listener's
// shuffle setting, unlike playPlaylistFrom, where picking a specific entry
// is itself the statement that the queue should start in playlist order.
function playPlaylist(playlist: PlaylistDetailItem): void {
	if (playlist.entries.length === 0) {
		reportNothingPlayable(playlist.title, async () => playPlaylist(playlist));
		return;
	}
	playStartNotice.set('idle');
	startPlaylistQueue(queueSourceOf(playlist), playlist.entries, 0, { restart: true });
}

// The one way a surface starts a playlist: name the playlist and the entry
// the listener picked. Owning the shuffle reset here is what keeps every
// entry click honest — a row means "play from here", which no leftover
// shuffle from a previous queue may reorder.
export function playPlaylistFrom(playlist: PlaylistDetailItem, startIndex: number): void {
	setShuffle(false);
	startPlaylistQueue(queueSourceOf(playlist), playlist.entries, startIndex, { restart: true });
}

// Whether an entry is the take the transport is holding right now: the same
// generation played from the same file, since a re-import keeps the id but
// changes the path.
export function isPlaylistEntryCurrent(entry: PlaylistEntryItem): boolean {
	const current = audioPlayer.current;
	return (
		current?.generation.id === entry.generation_id && current.generation.mp3_path === entry.mp3_path
	);
}

// A playlist row's ▶: pause or resume the entry that is already playing,
// otherwise start the playlist from it. Every playlist surface — the
// interior, the rail — shares this, so a row means the same thing in both.
export function playPlaylistEntry(playlist: PlaylistDetailItem, index: number): void {
	const entry = playlist.entries[index];
	if (entry && isPlaylistEntryCurrent(entry)) {
		audioPlayer.toggle();
		return;
	}
	playPlaylistFrom(playlist, index);
}

// A playlist entry's `position` is the playlist's order of record, so a
// queue is always built from that order — shuffled off it while shuffle is
// on, and restored to it the moment shuffle goes off, instead of freezing
// whatever order the last shuffle happened to produce.
function inPlaylistOrder(entries: PlaylistEntryItem[]): PlaylistEntryItem[] {
	return [...entries].sort((a, b) => a.position - b.position);
}

function startPlaylistQueue(
	playlist: PlaylistQueueSource,
	entries: PlaylistEntryItem[],
	startIndex: number,
	opts: { restart?: boolean; resumeAtTrackTime?: number } = {}
): void {
	beginPlayStart();
	clearWindowEnd();
	clearLibraryQueueSkipFeedback();
	const startEntry = entries[startIndex];
	const byPosition = inPlaylistOrder(entries);
	const ordered = shuffledWithStart(
		byPosition,
		startEntry ? Math.max(0, byPosition.indexOf(startEntry)) : 0
	);
	const loadOpts: { restart?: boolean; startAt?: number } = { restart: opts.restart };
	if (opts.resumeAtTrackTime !== undefined) loadOpts.startAt = opts.resumeAtTrackTime;
	playPlaylistIndex({ playlist, entries: ordered.items }, ordered.startIndex, loadOpts);
}

async function rebuildQueueStream(state: StreamFallbackState): Promise<QueueStreamManifest | null> {
	const ctx = get(queueContext);
	try {
		if (ctx.type === 'library') {
			clearLibraryQueueSkipFeedback();
			const currentTrack = state.manifest.tracks[state.trackIndex];
			const manifest = await createLibraryQueueStreamSnapshot(
				currentTrack?.generation_id ?? null,
				librarySnapshotOpts()
			);
			libraryQueueSkipped.set(manifest.skipped ?? []);
			libraryQueueSkippedComplete.set(manifest.skipped_complete ?? true);
			return manifest;
		}
		return await createQueueStreamSnapshot(
			state.manifest.tracks.map((track) => ({
				generation_id: track.generation_id,
				entry_id: track.entry_id
			}))
		);
	} catch {
		addToast('Stream expired and could not be rebuilt. Press play to retry.', 'error');
		return null;
	}
}

setupMediaSessionHandlers({
	play: () => audioPlayer.play(),
	pause: () => audioPlayer.pause(),
	stop: () => audioPlayer.pause(),
	next: () => {
		void playNextSong();
	},
	prev: () => {
		void playPrevSong();
	},
	seekTo: (seconds) => audioPlayer.seek(seconds)
});

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

function playlistEntryToPlaybackInfo(entry: PlaylistEntryItem): PlaybackInfo {
	return {
		generation: playlistEntryToGeneration(entry),
		songId: entry.song_id,
		songTitle: entry.song_title,
		artist: entry.artist,
		albumTitle: entry.album_title,
		lyrics: entry.lyrics
	};
}

export async function navigateToPlaying(): Promise<void> {
	const cur = audioPlayer.current;
	if (!cur) return;
	let song = get(songList).find((s) => s.id === cur.songId) ?? null;
	if (!song) {
		try {
			song = await fetchSong(cur.songId);
		} catch (err) {
			addToast(albumSongsErrorMessage(err), 'error');
			return;
		}
		upsertSongInList(song);
	}
	const { revealPlayingSong } = await import('./navigation');
	await revealPlayingSong(song, cur.generation.id);
}

export function handlePlaybackEnded(reason: 'normal' | 'window-end' = 'normal'): void {
	if (reason === 'window-end') {
		windowEnded.set(true);
		return;
	}
	void playNextSong();
}

// The app's single callback set for the singleton audioPlayer, installed
// once as one typed object (see AudioPlayerCallbacks) rather than five
// scattered assignments — a share route swaps in its own set on mount and
// restores this one on destroy.
audioPlayer.swapCallbacks({
	onEnded: handlePlaybackEnded,
	onPlaybackStarted: clearWindowEnd,
	onAuthLost: async () => {
		const { clearAuth } = await import('$lib/stores/auth');
		const { goto } = await import('$app/navigation');
		clearAuth();
		await goto('/login');
	},
	onStreamRebuild: rebuildQueueStream,
	onCurrentChange: updateMediaSessionMetadata
});
