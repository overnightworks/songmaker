import { writable, derived, get, readonly } from 'svelte/store';
import { ApiError, describeFailure, handleSessionLost, NetworkError } from '$lib/api/fetch';
import {
	createLibraryQueueStreamSnapshot,
	createQueueStreamSnapshot,
	fetchLibraryPoolQueue,
	fetchPlaylist,
	fetchSong
} from '$lib/api/client';
import { recordSongListen } from '$lib/api/songs';
import type {
	AlbumItem,
	GenerationItem,
	LibraryPoolTakeItem,
	PlaylistDetailItem,
	PlaylistEntryItem,
	PlaylistItem,
	QueueStreamManifest,
	QueueStreamSkipItem,
	SongItem
} from '$lib/api/types';
import {
	audioPlayer,
	type AudioPlayerCallbacks,
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
import { offline, whenBackOnline } from '$lib/stores/connectivity';
import {
	desktopNowPlayingSurface,
	LIBRARY_TAKE_POOL_LABELS,
	libraryTakePool,
	setDesktopNowPlayingSurface,
	setLibraryTakePool,
	type LibraryTakePool
} from '$lib/stores/playbackSettings';
import {
	loadPlaylistDetail,
	playlistDetailLoad,
	selectedPlaylist,
	selectedPlaylistDetail
} from '$lib/stores/playlists';
import {
	followPlaybackForResume,
	savedPlayback,
	type ResumeQueueSource,
	type SavedPlayback
} from '$lib/stores/playbackResume';
import { closeSidebar } from '$lib/stores/ui';
import {
	LIBRARY_QUEUE_EMPTY_TITLE,
	QUEUE_STREAM_EMPTY_POOL_PREFIX,
	QUEUE_STREAM_UNPLAYABLE_START_DETAIL,
	QUEUE_TAKE_MISSING_TOAST,
	PLAYLIST_LOADING_LABEL,
	RAIL_LIBRARY_LABEL,
	SHUFFLE_SCOPE_ALBUM,
	SHUFFLE_SCOPE_LIBRARY,
	SHUFFLE_SCOPE_PLAYLIST
} from '$lib/constants';
import {
	NOW_PLAYING_SHUFFLE_DISABLE_PREFIX,
	NOW_PLAYING_SHUFFLE_LABEL_PREFIX,
	type NowPlayingSurfaceKind,
	type PlaybackSource
} from '$lib/constants/now-playing';

// --- Browsing state ---
export const selectedAlbumId = writable<string | null>(null);
export const selectedSongId = writable<string | null>(null);
export const selectedGenerationId = writable<string | null>(null);

export const selectedSong = derived(
	[songList, selectedSongId],
	([$songs, $id]) => $songs.find((s) => s.id === $id) ?? null
);

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
	if (inflight !== undefined) return inflight;
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
interface PlaylistQueueSource {
	id: string;
	title: string;
}

type QueueContext =
	| { type: 'library'; takes?: PlaybackInfo[]; index?: number }
	| { type: 'album'; albumId: string; takes?: PlaybackInfo[]; index?: number }
	| {
			type: 'playlist';
			playlist: PlaylistQueueSource;
			entries: PlaylistEntryItem[];
			index: number;
	  };

export const queueContext = writable<QueueContext>({ type: 'library' });

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

function setQueueContext(ctx: QueueContext, opts: { curating?: boolean } = {}): void {
	queueContext.set(ctx);
	curationActive.set(opts.curating ?? false);
}

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
		return null;
	}
);

type PlayStartNotice = 'idle' | 'building' | 'empty' | 'error';
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

// Offline, the one strip already says why the songs could not load (#1039).
function toastAlbumSongsFailure(err: unknown): void {
	if (err instanceof NetworkError && get(offline)) return;
	addToast(albumSongsErrorMessage(err), 'error');
}

function libraryStreamFailureToast(err: unknown): string {
	if (isEmptyPoolError(err)) return `${LIBRARY_QUEUE_EMPTY_TITLE} (${poolLabel()})`;
	if (isUnplayableStartError(err)) return QUEUE_STREAM_UNPLAYABLE_START_DETAIL;
	return `${poolLabel()} queue failed. Press play to retry.`;
}

// --- Playback dispatch ---

function toPlaybackInfo(gen: GenerationItem, song: SongItem): PlaybackInfo {
	return {
		generation: gen,
		songId: song.id,
		songTitle: song.title,
		artist: song.artist,
		albumTitle: song.album_title,
		lyrics: gen.version_lyrics
	};
}

function playGeneration(
	gen: GenerationItem,
	song: SongItem,
	opts: { restart?: boolean } = {}
): void {
	clearWindowEnd();
	clearLibraryQueueSkipFeedback();
	loadQueueTake(toPlaybackInfo(gen, song), opts);
}

function randomIndex(length: number): number {
	return Math.floor(Math.random() * length); // NOSONAR S2245: shuffle has no security context.
}

function shuffled<T>(items: T[]): T[] {
	const copy = [...items];
	for (let i = copy.length - 1; i > 0; i--) {
		const j = randomIndex(i + 1);
		[copy[i], copy[j]] = [copy[j], copy[i]];
	}
	return copy;
}

function shuffledWithStart<T>(items: T[], startIndex: number): { items: T[]; startIndex: number } {
	if (!get(shuffleEnabled) || items.length <= 1) return { items, startIndex };
	const start = items[startIndex] ?? items[0];
	const rest = items.filter((_, index) => index !== startIndex);
	return { items: [start, ...shuffled(rest)], startIndex: 0 };
}

// Where a collection start begins: its top, or — for a shuffled start, which
// has no top — a drawn entry, since shuffledWithStart keeps the start in front
// and only shuffles what follows it.
export type CollectionStart = 'top' | 'random';

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
			// LibraryPoolTakeItem carries no duration field at all -- null is
			// the honest value here, not a stand-in for a real one.
			audio_duration_sec: null,
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

// Where a queue's first take starts: at a place in it, and paused when the
// queue is restored rather than played.
interface QueueStart {
	resumeAtTrackTime?: number;
	autoplay?: boolean;
}

interface QueueTakeLoad {
	restart?: boolean;
	startAt?: number;
	autoplay?: boolean;
}

function loadNativeTake(info: PlaybackInfo, opts: QueueTakeLoad = {}): void {
	clearWindowEnd();
	loadQueueTake(info, opts);
}

// Every take a queue plays goes through here, so the take after it is
// already loading while this one plays (#1187 P1).
function loadQueueTake(info: PlaybackInfo, opts: QueueTakeLoad): void {
	if (opts.startAt !== undefined || opts.autoplay !== undefined) {
		audioPlayer.load(info, { ...opts, restart: opts.restart ?? true });
	} else if (opts.restart) {
		audioPlayer.load(info, { restart: true });
	} else {
		audioPlayer.load(info);
	}
	preloadNextTake();
}

function firstTakeLoad(start: QueueStart): QueueTakeLoad {
	return { restart: true, startAt: start.resumeAtTrackTime, autoplay: start.autoplay };
}

function playNativeLibraryTakes(
	takes: PlaybackInfo[],
	index: number,
	start: QueueStart = {}
): void {
	setQueueContext({ type: 'library', takes, index });
	loadNativeTake(takes[index], firstTakeLoad(start));
}

function playNativeAlbumTakes(
	albumId: string,
	takes: PlaybackInfo[],
	index: number,
	start: QueueStart = {}
): void {
	setQueueContext({ type: 'album', albumId, takes, index });
	loadNativeTake(takes[index], firstTakeLoad(start));
}

function nativeTakeIndex(
	ctx: Exclude<QueueContext, { type: 'playlist' }>,
	current: PlaybackInfo | null
): number {
	if (!ctx.takes || ctx.takes.length === 0) return -1;
	if (!current) return ctx.index ?? 0;
	return queuePositionFrom(
		ctx.takes,
		ctx.index ?? 0,
		(take) =>
			take.generation.id === current.generation.id &&
			take.generation.mp3_path === current.generation.mp3_path
	);
}

// Where the queue holds a take, looked for from the queue's own index on: a
// take the player moved on to by itself is the next one along, even in a
// playlist that holds that take twice.
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

// Moves the index within the queue that is already playing (Skip and Pick's
// auto-advance during curation, a queue-row jump, plain Previous/Next) —
// deliberately bypassing setQueueContext, so an advance never ends curation
// mode the way building a genuinely different queue does; a queue that
// wasn't curating stays not-curating either way.
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

interface LibraryTakeStart extends QueueStart {
	tappedRowSong?: SongItem;
	// A restore reports nothing it cannot rebuild (#1187 P2), so the listener
	// who reopens the page is never asked to retry a play they did not start.
	quiet?: boolean;
}

function reportLibraryTakeStartFailure(
	gen: GenerationItem,
	opts: LibraryTakeStart,
	notice: PlayStartNotice,
	toast: string
): void {
	clearLibraryQueueSkipFeedback();
	if (opts.quiet) {
		playStartNotice.set('idle');
		return;
	}
	retryPlayIntent = () => playLibraryFromGeneration(gen, opts);
	playStartNotice.set(notice);
	addToast(toast, 'error');
}

// A take row never plays alone (#1187 P6): when the pool holds only the
// tapped take, as it does before anything is picked, the row's song names the
// album the queue continues through instead.
async function playLibraryFromGeneration(
	gen: GenerationItem,
	opts: LibraryTakeStart = {}
): Promise<void> {
	const { seq, signal } = beginPlayStart();
	setQueueContext({ type: 'library' });
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
		reportLibraryTakeStartFailure(
			gen,
			opts,
			isEmptyPoolError(err) ? 'empty' : 'error',
			libraryStreamFailureToast(err)
		);
		return;
	}
	if (!playStartIsCurrent(seq)) return;
	const takes = queue.takes.map(poolTakeToPlaybackInfo);
	const startIndex = takes.findIndex((take) => take.generation.id === gen.id);
	if (startIndex < 0) {
		reportLibraryTakeStartFailure(gen, opts, 'error', QUEUE_TAKE_MISSING_TOAST);
		return;
	}
	playStartNotice.set('idle');
	if (takes.length === 1 && opts.tappedRowSong) {
		await playAlbumFromGeneration(opts.tappedRowSong.album_id, opts.tappedRowSong, gen);
		return;
	}
	libraryQueueSkipped.set(queue.skipped ?? []);
	libraryQueueSkippedComplete.set(queue.skipped_complete ?? true);
	playNativeLibraryTakes(takes, startIndex, opts);
}

async function playLibrary(opts: QueueStart = {}): Promise<void> {
	const { seq, signal } = beginPlayStart();
	setQueueContext({ type: 'library' });
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
	playNativeLibraryTakes(queue.takes.map(poolTakeToPlaybackInfo), 0, opts);
}

type IdlePlayTarget =
	| { type: 'playlist'; label: string; playlistId: string }
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
	listedPlaylist: PlaylistItem | null;
	playlistLoading: boolean;
	albums: AlbumItem[];
}): IdlePlayTarget {
	if (input.collection?.kind === 'playlist') {
		const playlistId = input.collection.id;
		if (input.playlist?.id === playlistId) {
			return { type: 'playlist', label: input.playlist.title, playlistId };
		}
		// The listener opened this playlist: while its detail is still on the
		// way, Play means this playlist and waits for it -- never the library,
		// never the list they just left.
		if (input.playlistLoading) {
			return {
				type: 'playlist',
				label: input.listedPlaylist?.title ?? PLAYLIST_LOADING_LABEL,
				playlistId
			};
		}
		// A detail that failed to load has nothing to natively play -- fall
		// back to the named library target instead of a dead Play button.
		return { type: 'library', label: RAIL_LIBRARY_LABEL };
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
		listedPlaylist: get(selectedPlaylist),
		playlistLoading: get(playlistDetailLoad).status === 'loading',
		albums: get(albumList)
	});
	if (target.type === 'playlist') {
		await playOpenPlaylistOnceLoaded(target.playlistId);
		return;
	}
	if (target.type === 'album') {
		await playAlbum(target.albumId);
		return;
	}
	await playLibrary();
}

// The playlist store owns loading and joins the fetch already in flight; a
// listener who moves on while it loads leaves nothing here to play, and a
// play started meanwhile supersedes this wait even if they come back to it.
async function playOpenPlaylistOnceLoaded(playlistId: string): Promise<void> {
	if (get(selectedPlaylistDetail)?.id !== playlistId) {
		const { seq } = beginPlayStart();
		playStartNotice.set('building');
		await loadPlaylistDetail(playlistId);
		if (!playStartIsCurrent(seq)) return;
	}
	const playlist = get(selectedPlaylistDetail);
	if (playlist?.id !== playlistId) {
		playStartNotice.set('idle');
		return;
	}
	playPlaylist(playlist, 'top');
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
	if (ctx.type === 'playlist' || (ctx.takes && ctx.takes.length > 0)) {
		return nextQueueTake(ctx, current).kind === 'take';
	}
	if (ctx.type === 'library') return false;
	const pool = songs.filter((s) => s.album_id === ctx.albumId);
	return pool.some((s) => s.id !== current.songId && s.generation_count > 0);
}

// Archived takes are not playable (their rows offer no play affordance), so
// they never stand in as a song's take in a queue either.
function playableGens(song: SongItem): GenerationItem[] {
	return song.generations.filter((gen) => !gen.is_archived);
}

function pickedGen(song: SongItem): GenerationItem | undefined {
	return playableGens(song).find((gen) => gen.is_picked);
}

function bestGen(song: SongItem): GenerationItem | undefined {
	return pickedGen(song) ?? playableGens(song)[0];
}

function albumQueueTake(song: SongItem, gen: GenerationItem): PlaybackInfo {
	return playlistEntryToPlaybackInfo(toAlbumQueueEntry(song, gen));
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
		audio_duration: gen.audio_duration_sec,
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
	startGenerationId: string | undefined,
	opts: { curating?: boolean } = {}
): void {
	if (entries.length === 0) return;
	const startIndex = startGenerationId
		? Math.max(
				0,
				entries.findIndex((entry) => entry.generation_id === startGenerationId)
			)
		: 0;
	const ordered = shuffledWithStart(entries, startIndex);
	setQueueContext(
		{
			type: 'album',
			albumId,
			takes: ordered.items.map(playlistEntryToPlaybackInfo),
			index: ordered.startIndex
		},
		opts
	);
}

// An album queue plays each song's pick, so a take picked for a song still
// ahead takes that song's place in the queue, and the preload follows it if it
// is the next one. Songs already played keep the take they played, and a
// move within the queue keeps curation going, as playNativeIndex does.
function followPicksAheadInAlbumQueue(songs: SongItem[]): void {
	const ctx = get(queueContext);
	if (ctx.type !== 'album' || !ctx.takes) return;
	const currentIndex = nativeTakeIndex(ctx, audioPlayer.current);
	if (currentIndex < 0) return;
	const songsById = new Map(songs.map((song) => [song.id, song]));
	let repicked = false;
	const takes = ctx.takes.map((take, index) => {
		if (index <= currentIndex) return take;
		const song = songsById.get(take.songId);
		const picked = song && pickedGen(song);
		if (!song || !picked || picked.id === take.generation.id) return take;
		repicked = true;
		return albumQueueTake(song, picked);
	});
	if (!repicked) return;
	queueContext.set({ ...ctx, takes, index: currentIndex });
	preloadNextTake();
}

songList.subscribe(followPicksAheadInAlbumQueue);

// Whether the transport holds an entry's take: the same generation played
// from the same file, since a re-import keeps the id but changes the path.
function holdsEntryTake(current: PlaybackInfo, entry: PlaylistEntryItem): boolean {
	return (
		current.generation.id === entry.generation_id && current.generation.mp3_path === entry.mp3_path
	);
}

function currentPlaylistIndex(
	ctx: { entries: PlaylistEntryItem[]; index: number },
	current: PlaybackInfo | null = audioPlayer.current
): number {
	if (!current) return ctx.index;
	const idx = queuePositionFrom(ctx.entries, ctx.index, (entry) => holdsEntryTake(current, entry));
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

function upNextItem(
	items: QueueRowItem[],
	ctx: QueueContext,
	current: PlaybackInfo | null
): QueueRowItem | null {
	const next = nextQueueTake(ctx, current);
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
	return { items, currentIndex, upNext: upNextItem(items, ctx, current) };
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
type NowPlayingSurface = 'closed' | NowPlayingSurfaceKind;
export const nowPlayingSurface = writable<NowPlayingSurface>('closed');
export const nowPlayingOpen = derived(nowPlayingSurface, (surface) => surface !== 'closed');
type NowPlayingPanel = 'queue' | 'take';
export const nowPlayingPanel = writable<NowPlayingPanel>('queue');

// Whether the viewport has room for the docked panel beside the workspace.
// The layout owns that media query — the same width/pointer switch the frame
// stacks on — and reports it here, so opening and Escape resolve the surface
// from one fact instead of each re-reading the breakpoint.
export const nowPlayingDockable = writable(false);

nowPlayingDockable.subscribe((dockable) => {
	if (!dockable && get(nowPlayingSurface) === 'docked') nowPlayingSurface.set('full');
});

// Whether Now Playing is a pushed screen: the full surface on a viewport with
// no room for the docked panel beside the workspace. Such a screen leaves as a
// whole (Escape closes it); a full surface with room to dock steps down to the
// docked panel instead.
const nowPlayingIsPushedScreen = derived(
	[nowPlayingSurface, nowPlayingDockable],
	([surface, dockable]) => surface === 'full' && !dockable
);

const fullSurfaceChosen = writable(false);
export const nowPlayingFullChosen = readonly(fullSurfaceChosen);

// The element to return focus to when Now Playing closes. PlayerBar
// registers its own "Now Playing" button here once on mount — every opener
// (PlayerBar's button, a TakesList row, NowPlayingTake's Repaint/Cover action)
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
// NowPlayingTake's Repaint/Cover action) routes through these two functions
// instead of poking `nowPlayingSurface`/`nowPlayingPanel` directly, so closing
// the mobile rail drawer on open and restoring focus on close happen exactly
// once, the same way, regardless of entry point.
export function openNowPlaying(panel: NowPlayingPanel): void {
	closeSidebar();
	nowPlayingPanel.set(panel);
	const surface = get(nowPlayingDockable) ? get(desktopNowPlayingSurface) : 'full';
	nowPlayingSurface.set(surface);
	fullSurfaceChosen.set(surface === 'full');
}

export function closeNowPlaying(): void {
	const surface = get(nowPlayingSurface);
	if (surface === 'closed') return;
	nowPlayingSurface.set('closed');
	fullSurfaceChosen.set(false);
	curationActive.set(false);
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
	fullSurfaceChosen.set(surface === 'full');
}

// Escape leaves Now Playing one level at a time: the full surface falls back
// to the docked panel wherever there is room for one, and the docked panel —
// like the pushed screen — closes.
export function escapeNowPlaying(): void {
	if (get(nowPlayingSurface) === 'full' && !get(nowPlayingIsPushedScreen)) {
		dockNowPlaying();
		return;
	}
	closeNowPlaying();
}

const PLAYBACK_FAILED_TOAST = 'Playback failed';

// The single playback entry point for a take row (TakesList, TakeStrip):
// toggles pause if the row's take is already playing, otherwise starts a
// queue from it (its album, else the library pool), reporting any failure as
// a toast instead of throwing into the caller.
export async function playTake(gen: GenerationItem, song: SongItem): Promise<void> {
	if (audioPlayer.current?.generation.id === gen.id && audioPlayer.status === 'playing') {
		audioPlayer.toggle();
		return;
	}
	try {
		const albumId = get(selectedAlbumId);
		if (albumId) await playAlbumFromGeneration(albumId, song, gen);
		else await playLibraryFromGeneration(gen, { tappedRowSong: song });
	} catch (e) {
		addToast(describeFailure(e, PLAYBACK_FAILED_TOAST), 'error');
	}
}

type TakeRow = { alreadyLoaded: boolean; start: () => void | Promise<void> };

// A row body never stops the music. The take a row stands for is left
// running, and a paused one picks up where it stands rather than starting
// over. Pausing belongs to a take row's own ▶ and to the transport.
async function playRow(row: TakeRow): Promise<void> {
	if (row.alreadyLoaded) audioPlayer.play();
	else await row.start();
}

// What a click on a take row means where it has no page of its own to show
// the result (the click rule of issue #140): play the take and surface Now
// Playing straight on its judging panel. The editor's takes list and the
// rail's playlist rows differ only in how playback starts, so both hand that
// start to this one action; clicking the row already loaded only brings up
// the panel.
async function playTakeRow(row: TakeRow): Promise<void> {
	await playRow(row);
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

function playlistEntryRow(playlist: PlaylistDetailItem, index: number): TakeRow {
	const entry = playlist.entries[index];
	return {
		alreadyLoaded: entry !== undefined && isPlaylistEntryCurrent(entry, get(queueContext)),
		start: () => playPlaylistFrom(playlist, index)
	};
}

export async function playPlaylistEntryAndShowNowPlaying(
	playlist: PlaylistDetailItem,
	index: number
): Promise<void> {
	await playTakeRow(playlistEntryRow(playlist, index));
}

// A row on the playlist page (#1010): it plays from here and leaves the
// listener on the page, whose playing row and mini-player show the result.
export async function playPlaylistEntry(
	playlist: PlaylistDetailItem,
	index: number
): Promise<void> {
	await playRow(playlistEntryRow(playlist, index));
}

type QueueDirection = -1 | 1;

function playStreamInDirection(direction: QueueDirection): boolean {
	if (audioPlayer.mode !== 'stream') return false;
	if (direction === 1) audioPlayer.nextStreamTrack();
	else audioPlayer.prevStreamTrack();
	return true;
}

type NextQueueTake =
	{ kind: 'take'; index: number; take: PlaybackInfo } | { kind: 'window-end' } | { kind: 'none' };

const NO_NEXT_TAKE: NextQueueTake = { kind: 'none' };

// The one decider of which take follows the current one: Next plays it, and
// the preload loads it while the current one still plays, so the two can
// never disagree. A queue wraps around; the library window's last take is
// followed by its end, not by a take.
function nextQueueTake(ctx: QueueContext, current: PlaybackInfo | null): NextQueueTake {
	if (ctx.type === 'playlist') {
		if (ctx.entries.length <= 1) return NO_NEXT_TAKE;
		const index = (currentPlaylistIndex(ctx, current) + 1) % ctx.entries.length;
		return { kind: 'take', index, take: playlistEntryToPlaybackInfo(ctx.entries[index]) };
	}
	const index = nativeTakeIndex(ctx, current);
	if (index < 0 || ctx.takes === undefined) return NO_NEXT_TAKE;
	if (
		ctx.type === 'library' &&
		index === ctx.takes.length - 1 &&
		!get(libraryQueueSkippedComplete)
	) {
		return { kind: 'window-end' };
	}
	if (ctx.takes.length <= 1) return NO_NEXT_TAKE;
	const nextIndex = (index + 1) % ctx.takes.length;
	return { kind: 'take', index: nextIndex, take: ctx.takes[nextIndex] };
}

function takeAfterCurrent(): PlaybackInfo | null {
	return takeAfter(audioPlayer.current);
}

function takeAfter(take: PlaybackInfo | null): PlaybackInfo | null {
	const next = nextQueueTake(get(queueContext), take);
	return next.kind === 'take' ? next.take : null;
}

// What a reopened page shows once the current take has ended: the take the
// queue plays next, or, where the library window ends, the ended take itself,
// since a restored library queue builds its next window from there (#1236).
function takeAfterTheEnd(): PlaybackInfo | null {
	const next = nextQueueTake(get(queueContext), audioPlayer.current);
	if (next.kind === 'window-end') return audioPlayer.current;
	return next.kind === 'take' ? next.take : null;
}

function preloadNextTake(): void {
	audioPlayer.preload(takeAfterCurrent());
}

function playPlaylistInDirection(
	ctx: Extract<QueueContext, { type: 'playlist' }>,
	direction: QueueDirection
): void {
	if (direction === 1) {
		const next = nextQueueTake(ctx, audioPlayer.current);
		if (next.kind === 'take') playPlaylistIndex(ctx, next.index);
		return;
	}
	if (ctx.entries.length <= 1) return;
	const currentIndex = currentPlaylistIndex(ctx);
	playPlaylistIndex(ctx, (currentIndex - 1 + ctx.entries.length) % ctx.entries.length);
}

function playNativeTakesInDirection(
	ctx: Exclude<QueueContext, { type: 'playlist' }>,
	direction: QueueDirection
): void {
	if (direction === 1) {
		const next = nextQueueTake(ctx, audioPlayer.current);
		if (next.kind === 'window-end') windowEnded.set(true);
		if (next.kind === 'take') playNativeIndex(ctx, next.index);
		return;
	}
	const index = nativeTakeIndex(ctx, audioPlayer.current);
	if (index < 0 || ctx.takes === undefined || ctx.takes.length <= 1) return;
	playNativeIndex(ctx, (index - 1 + ctx.takes.length) % ctx.takes.length);
}

function playContextInDirection(ctx: QueueContext, direction: QueueDirection): boolean {
	if (ctx.type === 'playlist') {
		playPlaylistInDirection(ctx, direction);
		return true;
	}
	if (ctx.takes && ctx.takes.length > 0) {
		playNativeTakesInDirection(ctx, direction);
		return true;
	}
	return ctx.type === 'library';
}

async function playSongCandidate(song: SongItem): Promise<boolean> {
	await ensureGenerationsLoaded(song.id);
	const fresh = get(songList).find((item) => item.id === song.id);
	const gen = fresh ? bestGen(fresh) : undefined;
	if (!gen || !fresh) return false;
	playGeneration(gen, fresh);
	return true;
}

async function playRandomNextSong(songs: SongItem[], currentSongId: string): Promise<void> {
	const candidates = songs.filter((song) => song.id !== currentSongId && song.generation_count > 0);
	while (candidates.length > 0) {
		const index = Math.floor(Math.random() * candidates.length); // NOSONAR S2245: shuffle has no security context.
		const [next] = candidates.splice(index, 1);
		if (await playSongCandidate(next)) return;
	}
}

async function playAdjacentSong(
	songs: SongItem[],
	currentSongId: string,
	direction: QueueDirection
): Promise<void> {
	const currentIndex = songs.findIndex((song) => song.id === currentSongId);
	for (let offset = 1; offset <= songs.length; offset++) {
		const song = songs[(currentIndex + direction * offset + songs.length) % songs.length];
		if (!song || song.id === currentSongId || song.generation_count === 0) continue;
		if (await playSongCandidate(song)) return;
	}
}

export async function playNextSong(): Promise<void> {
	if (playStreamInDirection(1)) return;
	const ctx = get(queueContext);
	if (playContextInDirection(ctx, 1)) return;
	const current = audioPlayer.current;
	if (!current) return;
	const songs = queueSongs();
	if (get(shuffleEnabled)) {
		await playRandomNextSong(songs, current.songId);
		return;
	}
	await playAdjacentSong(songs, current.songId, 1);
}

export async function playPrevSong(): Promise<void> {
	if (playStreamInDirection(-1)) return;
	const ctx = get(queueContext);
	if (playContextInDirection(ctx, -1)) return;
	const current = audioPlayer.current;
	if (!current) return;
	await playAdjacentSong(queueSongs(), current.songId, -1);
}

// The album's opening take, which is not always the opening track's:
// `generation_count` counts archived takes too, so a track whose takes are
// all archived is skipped rather than taken as proof the album is
// unplayable. Returns null both when nothing is playable and when a newer
// play start superseded this one — the caller separates the two with its
// own playStartIsCurrent check. A rejected load (e.g. 429) is left
// uncaught here and propagates to the caller.
async function firstPlayableAlbumTake(
	albumId: string,
	seq: number,
	start: CollectionStart
): Promise<{ song: SongItem; gen: GenerationItem } | null> {
	const inOrder = albumSongsInOrder(albumId);
	for (const song of start === 'random' ? shuffled(inOrder) : inOrder) {
		if (song.generation_count === 0) continue;
		await ensureGenerationsLoaded(song.id);
		if (!playStartIsCurrent(seq)) return null;
		const fresh = get(songList).find((item) => item.id === song.id) ?? song;
		const gen = bestGen(fresh);
		if (gen) return { song: fresh, gen };
	}
	return null;
}

// The album becomes the queue only once its opening take starts: an album
// that turns out to have nothing playable leaves the running queue, and the
// place it names as its source, exactly as they were.
export async function playAlbum(albumId: string, start: CollectionStart = 'top'): Promise<void> {
	const { seq } = beginPlayStart();
	clearWindowEnd();
	clearLibraryQueueSkipFeedback();
	playStartNotice.set('building');
	if (albumSongsInOrder(albumId).length === 0) {
		await loadSongsForAlbum(albumId);
		if (!playStartIsCurrent(seq)) return;
	}
	let startTake: { song: SongItem; gen: GenerationItem } | null;
	try {
		startTake = await firstPlayableAlbumTake(albumId, seq, start);
	} catch (err) {
		if (!playStartIsCurrent(seq)) return;
		playStartNotice.set('idle');
		toastAlbumSongsFailure(err);
		return;
	}
	if (!playStartIsCurrent(seq)) return;
	if (!startTake) {
		reportNothingPlayable(albumTitle(get(albumList), albumId), () => playAlbum(albumId, start));
		return;
	}
	playStartNotice.set('idle');
	playNativeAlbumTakes(albumId, [albumQueueTake(startTake.song, startTake.gen)], 0);
	await loadSongsForAlbum(albumId);
	if (!playStartIsCurrent(seq)) return;
	const entries = await collectAlbumEntries(albumId, seq);
	if (entries === null || !playStartIsCurrent(seq)) return;
	setAlbumQueueTakes(albumId, entries, startTake.gen.id);
	preloadNextTake();
}

async function playAlbumFromGeneration(
	albumId: string,
	song: SongItem,
	gen: GenerationItem,
	opts: QueueStart = {}
): Promise<void> {
	const { seq } = beginPlayStart();
	clearWindowEnd();
	clearLibraryQueueSkipFeedback();
	playNativeAlbumTakes(albumId, [toPlaybackInfo(gen, song)], 0, opts);
	await gatherAlbumQueueAround(albumId, song, gen, seq);
}

// Turns the one-take album queue a start loaded into the whole album, its
// takes in place around the one playing, unless a newer start superseded it.
async function gatherAlbumQueueAround(
	albumId: string,
	song: SongItem,
	gen: GenerationItem,
	seq: number
): Promise<void> {
	if (!playStartIsCurrent(seq)) return;
	await loadSongsForAlbum(albumId);
	if (!playStartIsCurrent(seq)) return;
	const entries = await collectAlbumEntries(albumId, seq, { song, gen });
	if (entries === null || !playStartIsCurrent(seq)) return;
	setAlbumQueueTakes(albumId, entries, gen.id);
	preloadNextTake();
}

// The one entry point for curation: the same per-song candidate takes
// playAlbum already builds (existing pick, else bestGen), started at the
// first song without a pick — or track 1 once every song has one, so
// re-curating an already-picked album still starts somewhere sensible.
export async function curateAlbum(albumId: string): Promise<void> {
	const { seq } = beginPlayStart();
	clearWindowEnd();
	clearLibraryQueueSkipFeedback();
	playStartNotice.set('building');
	await loadSongsForAlbum(albumId);
	if (!playStartIsCurrent(seq)) return;
	const entries = await collectAlbumEntries(albumId, seq);
	if (entries === null || !playStartIsCurrent(seq)) return;
	if (entries.length === 0) {
		playStartNotice.set('idle');
		reportNothingPlayable(albumTitle(get(albumList), albumId), () => curateAlbum(albumId));
		return;
	}
	playStartNotice.set('idle');
	const startIndex = Math.max(
		0,
		entries.findIndex((entry) => !entry.is_picked)
	);
	setAlbumQueueTakes(albumId, entries, entries[startIndex].generation_id, { curating: true });
	const ctx = get(queueContext);
	if (ctx.type === 'album' && ctx.takes) {
		loadNativeTake(ctx.takes[ctx.index ?? 0], { restart: true });
	}
	openNowPlaying('take');
}

function playPlaylistIndex(
	ctx: { playlist: PlaylistQueueSource; entries: PlaylistEntryItem[] },
	newIndex: number,
	opts: QueueTakeLoad = {}
): void {
	if (newIndex < 0 || newIndex >= ctx.entries.length) return;
	const entry = ctx.entries[newIndex];
	setQueueContext({
		type: 'playlist',
		playlist: ctx.playlist,
		entries: ctx.entries,
		index: newIndex
	});
	loadQueueTake(playlistEntryToPlaybackInfo(entry), opts);
}

function queueSourceOf(playlist: PlaylistDetailItem): PlaylistQueueSource {
	return { id: playlist.id, title: playlist.title };
}

// A whole-playlist start: the idle transport Play and the playlist header. It
// keeps the listener's shuffle setting, unlike playPlaylistFrom, where picking a
// specific entry is itself the statement that the queue should start in
// playlist order.
export function playPlaylist(playlist: PlaylistDetailItem, start: CollectionStart): void {
	if (playlist.entries.length === 0) {
		reportNothingPlayable(playlist.title, async () => playPlaylist(playlist, start));
		return;
	}
	playStartNotice.set('idle');
	const startIndex = start === 'random' ? randomIndex(playlist.entries.length) : 0;
	startPlaylistQueue(queueSourceOf(playlist), playlist.entries, startIndex, { restart: true });
}

// The one way a surface starts a playlist: name the playlist and the entry
// the listener picked. Owning the shuffle reset here is what keeps every
// entry click honest — a row means "play from here", which no leftover
// shuffle from a previous queue may reorder.
function playPlaylistFrom(playlist: PlaylistDetailItem, startIndex: number): void {
	setShuffle(false);
	startPlaylistQueue(queueSourceOf(playlist), playlist.entries, startIndex, { restart: true });
}

// Whether an entry is the one the playlist queue is playing right now. The
// entry, not its take, settles it: a playlist may hold one take twice, and
// only the place the queue stands on is playing. A take loaded from outside
// the queue is no entry's. The queue context is passed in so a template that
// reads it as `$queueContext` re-renders when the queue moves.
export function isPlaylistEntryCurrent(entry: PlaylistEntryItem, ctx: QueueContext): boolean {
	return playingPlaylistEntry(ctx)?.id === entry.id;
}

function playingPlaylistEntry(ctx: QueueContext): PlaylistEntryItem | undefined {
	const current = audioPlayer.current;
	if (ctx.type !== 'playlist' || !current) return undefined;
	const playing = ctx.entries[currentPlaylistIndex(ctx, current)];
	return playing && holdsEntryTake(current, playing) ? playing : undefined;
}

function listenSourcePlaylistId(ctx: QueueContext): string | null {
	if (ctx.type !== 'playlist' || !playingPlaylistEntry(ctx)) return null;
	return ctx.playlist.id;
}

// Whether a song is the one the transport is holding right now, whichever of
// its takes that is: an album row and its rail track mark the song, not a take.
export function isSongCurrent(songId: string): boolean {
	return audioPlayer.current?.songId === songId;
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
	opts: QueueStart & { restart?: boolean } = {}
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
	const loadOpts: QueueTakeLoad = { restart: opts.restart };
	if (opts.resumeAtTrackTime !== undefined) loadOpts.startAt = opts.resumeAtTrackTime;
	if (opts.autoplay !== undefined) loadOpts.autoplay = opts.autoplay;
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
			toastAlbumSongsFailure(err);
			return;
		}
		upsertSongInList(song);
	}
	const { revealPlayingSong } = await import('./navigation');
	await revealPlayingSong(song, cur.generation.id);
}

function handlePlaybackEnded(reason: 'normal' | 'window-end' = 'normal'): void {
	if (reason === 'window-end') {
		windowEnded.set(true);
		return;
	}
	void playNextSongOnceRestoredAlbumIsGathered();
}

// A take restored near its end can end before its album is gathered; the
// album's next song still follows it only while that take still stands ended.
// A take started, or the ended one played again, in the meantime is left to
// play, buffer or stay paused (#1236).
async function playNextSongOnceRestoredAlbumIsGathered(): Promise<void> {
	const gathering = restoredAlbumQueueGathering;
	if (gathering !== null) {
		const ended = audioPlayer.current;
		await gathering;
		if (audioPlayer.current !== ended || audioPlayer.status !== 'idle') return;
	}
	await playNextSong();
}

const recordedListens = new Set<string>();

function recordFirstTakeListen(): void {
	clearWindowEnd();
	const current = audioPlayer.current;
	if (!current) return;
	const playlistId = listenSourcePlaylistId(get(queueContext));
	const listenKey = `${current.generation.id}:${playlistId ?? ''}`;
	if (recordedListens.has(listenKey)) return;
	recordedListens.add(listenKey);
	void recordSongListen(current.songId, playlistId).catch((error: unknown) => {
		console.error('Could not record song listen:', error);
	});
}

function handlePlaybackStarted(): void {
	recordFirstTakeListen();
	gatherRestoredAlbumQueue();
}

// A take change the player made by itself — the playhead crossing into the
// next take on the continuous deck — moves the queue on and asks for the take
// after it, just as a load does.
function handleCurrentChange(current: PlaybackInfo | null): void {
	updateMediaSessionMetadata(current);
	if (audioPlayer.status === 'playing') recordFirstTakeListen();
	if (current === null) return;
	moveQueueIndexTo(current);
	preloadNextTake();
}

// The deck plays on past the skipped take, so the listener hears which one
// the queue lost instead of finding it silently gone.
function announceSkippedTake(take: PlaybackInfo): void {
	addToast(`${take.songTitle} couldn't be loaded, skipped.`, 'error');
}

function moveQueueIndexTo(current: PlaybackInfo): void {
	const ctx = get(queueContext);
	const index =
		ctx.type === 'playlist' ? currentPlaylistIndex(ctx, current) : nativeTakeIndex(ctx, current);
	if (index < 0 || index === ctx.index) return;
	queueContext.set({ ...ctx, index });
}

/**
 * Offline, a playback failure is the strip's to say; the take then plays on
 * by itself once the connection is back, so no wordless Retry outlives the
 * outage (#1161 R2).
 */
let stopWaitingForReturn: (() => void) | null = null;

function leaveNetworkFailureToTheStrip(): boolean {
	if (!get(offline)) return false;
	stopWaitingForReturn ??= whenBackOnline(resumePlaybackOnReturn);
	return true;
}

function resumePlaybackOnReturn(): void {
	stopWaitingForReturn?.();
	stopWaitingForReturn = null;
	audioPlayer.resumeAfterNetworkReturn();
}

// The app's single callback set for the singleton audioPlayer, installed
// once as one typed object (see AudioPlayerCallbacks) rather than five
// scattered assignments — a share route swaps in its own set on mount and
// restores this one on destroy.
const appPlayerCallbacks: AudioPlayerCallbacks = {
	onEnded: handlePlaybackEnded,
	onPlaybackStarted: handlePlaybackStarted,
	onAuthLost: handleSessionLost,
	onStreamRebuild: rebuildQueueStream,
	onCurrentChange: handleCurrentChange,
	takeAfter,
	onTakeSkipped: announceSkippedTake,
	networkFailureIsAnnounced: leaveNetworkFailureToTheStrip
};
audioPlayer.swapCallbacks(appPlayerCallbacks);

// A share route owns the player while it swaps in its own callbacks, so
// share playback is never remembered.
function playsTheAppsTakes(): boolean {
	return audioPlayer.currentCallbacks === appPlayerCallbacks;
}

// The queue a resumed take continues in. A library context without takes is
// no queue yet (the one a reload starts with, or one still building), so it
// names none rather than the library settings of the moment (#1226).
function resumeQueueSource(): ResumeQueueSource | null {
	const ctx = get(queueContext);
	if (ctx.type === 'album') return { type: 'album', albumId: ctx.albumId };
	if (ctx.type === 'playlist') return { type: 'playlist', playlistId: ctx.playlist.id };
	if (!ctx.takes?.length) return null;
	return { type: 'library', ...librarySnapshotOpts() };
}

followPlaybackForResume({
	playsTheAppsTakes,
	queueSource: resumeQueueSource,
	takeAfterCurrent: takeAfterTheEnd
});

/**
 * Shows the take the signed-in user last played on this device, paused where
 * it stood, in the queue it played from, so that reopening a page Android
 * killed finds it again and one tap plays on through that queue (#1187 P2).
 * An album queue is the album the song belongs to now, as the server says. A
 * take loaded in the meantime is never replaced.
 */
export async function restoreLastPlayback(): Promise<void> {
	const saved = savedPlayback();
	if (saved === null || audioPlayer.current !== null) return;
	const found = await playableSavedTake(saved);
	if (found === null || audioPlayer.current !== null) return;
	const start: QueueStart = {
		resumeAtTrackTime: positionWithinTake(saved.position, found.take),
		autoplay: false
	};
	const { source } = saved;
	if (source.type === 'album') {
		restoreAlbumTake(found.song, found.take, start);
	} else if (source.type === 'library') {
		await restoreLibraryTake(source, found.take, start);
	} else {
		await restorePlaylistQueue(source.playlistId, found.take, start);
	}
}

// The device's library settings are what build, extend and save a library
// queue, so a restored one takes on the settings its record names; the pool
// and shuffle controls then show the queue that plays (#1236).
async function restoreLibraryTake(
	source: Extract<ResumeQueueSource, { type: 'library' }>,
	take: GenerationItem,
	start: QueueStart
): Promise<void> {
	setLibraryTakePool(source.pool);
	setShuffle(source.shuffle);
	await playLibraryFromGeneration(take, { ...start, quiet: true });
}

// Gathering an album's takes costs a request per song, so a restored album
// take names its album queue at once but gathers the album's other takes only
// once it plays, not on every reload (#1236).
let restoredAlbumQueueToGather: (() => Promise<void>) | null = null;
let restoredAlbumQueueGathering: Promise<void> | null = null;

function restoreAlbumTake(song: SongItem, take: GenerationItem, start: QueueStart): void {
	const { seq } = beginPlayStart();
	playNativeAlbumTakes(song.album_id, [toPlaybackInfo(take, song)], 0, start);
	restoredAlbumQueueToGather = () => gatherAlbumQueueAround(song.album_id, song, take, seq);
}

function gatherRestoredAlbumQueue(): void {
	const gather = restoredAlbumQueueToGather;
	if (gather === null) return;
	restoredAlbumQueueToGather = null;
	restoredAlbumQueueGathering = gather()
		.catch(toastAlbumSongsFailure)
		.finally(() => {
			restoredAlbumQueueGathering = null;
		});
}

// A take saved in its last second would end the moment it plays, and Play
// would skip straight to the next take, so it comes back at its start instead
// (#1236).
const RESTORE_AT_START_WITHIN_END_SECONDS = 1;

function positionWithinTake(position: number, take: GenerationItem): number {
	const duration = take.audio_duration_sec;
	return duration !== null && position >= duration - RESTORE_AT_START_WITHIN_END_SECONDS
		? 0
		: position;
}

// The server answers 404 for a song deleted or out of this user's reach, and
// a take deleted or archived since is missing from its song or marked so;
// none of them, nor a server out of reach, is restored, and none is reported.
async function playableSavedTake(
	saved: SavedPlayback
): Promise<{ song: SongItem; take: GenerationItem } | null> {
	const song = await quietly(() => fetchSong(saved.songId));
	if (song === null) return null;
	const take = song.generations.find((gen) => gen.id === saved.generationId && !gen.is_archived);
	return take === undefined ? null : { song, take };
}

// A playlist deleted, out of reach, or no longer holding the take restores
// nothing, as a lost take does.
async function restorePlaylistQueue(
	playlistId: string,
	take: GenerationItem,
	start: QueueStart
): Promise<void> {
	const playlist = await quietly(() => fetchPlaylist(playlistId));
	if (playlist === null || audioPlayer.current !== null) return;
	const index = playlist.entries.findIndex((entry) => entry.generation_id === take.id);
	if (index < 0) return;
	startPlaylistQueue(queueSourceOf(playlist), playlist.entries, index, { restart: true, ...start });
}

async function quietly<T>(request: () => Promise<T>): Promise<T | null> {
	try {
		return await request();
	} catch (err) {
		if (err instanceof ApiError || err instanceof NetworkError) return null;
		throw err;
	}
}
