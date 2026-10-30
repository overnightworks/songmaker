import { writable, derived, get, readonly } from 'svelte/store';
import { ApiError, describeFailure, NetworkError } from '#lib/api/fetch.ts';
import { fetchLibraryPoolQueue, fetchPlaylist, fetchSong } from '#lib/api/client.ts';
import { recordSongListen } from '#lib/api/songs.ts';
import {
	bestTake,
	isPlayableTake,
	pickedTake,
	songHasPlayableTake,
	songTakesLoaded
} from '#lib/utils/playable.ts';
import type {
	AlbumItem,
	GenerationItem,
	LibraryPoolTakeItem,
	PlaylistDetailItem,
	PlaylistEntryItem,
	PlaylistItem,
	QueueStreamSkipItem,
	SongItem
} from '#lib/api/types.ts';
import {
	audioPlayer,
	RECOVERY_DEADLINE_MS,
	transportOffersPause,
	type AudioPlayerCallbacks,
	type PlaybackInfo,
	type PlayerTenure,
	type TransportState
} from '#lib/services/audioPlayer.svelte.ts';
import {
	clearMediaSessionPositionState,
	type LockScreenTitle,
	setupMediaSessionHandlers,
	updateMediaSessionMetadata,
	updateMediaSessionPlaybackState
} from '#lib/services/mediaSession.ts';
import { type OpenCollection, openCollection } from '#lib/stores/collection.ts';
import {
	albumList,
	albumSongsErrorMessage,
	loadSongsForAlbum,
	songList,
	upsertSongInList
} from '#lib/stores/libraryData.ts';
import { handleSessionLost } from '#lib/stores/auth.ts';
import { addToast } from '#lib/stores/toast.ts';
import { offline, whenBackOnline } from '#lib/stores/connectivity.ts';
import { outdateLastPlayedRanking } from '#lib/stores/libraryOrder.ts';
import {
	desktopNowPlayingSurface,
	LIBRARY_TAKE_POOL_LABELS,
	libraryTakePool,
	setDesktopNowPlayingSurface,
	setLibraryTakePool,
	type LibraryTakePool
} from '#lib/stores/playbackSettings.ts';
import {
	loadPlaylistDetail,
	playlistDetailLoad,
	selectedPlaylist,
	selectedPlaylistDetail
} from '#lib/stores/playlists.ts';
import {
	followPlaybackForResume,
	savedPlayback,
	type ResumeQueueSource,
	type SavedPlayback
} from '#lib/stores/playbackResume.ts';
import {
	LIBRARY_QUEUE_EMPTY_TITLE,
	QUEUE_STREAM_EMPTY_POOL_PREFIX,
	QUEUE_STREAM_UNPLAYABLE_START_DETAIL,
	QUEUE_TAKE_MISSING_TOAST,
	PLAYLIST_LOADING_LABEL,
	LIBRARY_PAGE_LABEL,
	SHUFFLE_SCOPE_ALBUM,
	SHUFFLE_SCOPE_LIBRARY,
	SHUFFLE_SCOPE_PLAYLIST
} from '#lib/constants.ts';
import {
	NOW_PLAYING_SHUFFLE_DISABLE_PREFIX,
	NOW_PLAYING_SHUFFLE_LABEL_PREFIX,
	type NowPlayingSurfaceKind,
	type PlaybackSource
} from '#lib/constants/now-playing.ts';
import { shuffled } from '#lib/utils/shuffle.ts';
import { readStorage, writeStorage } from '#lib/utils/storage.ts';

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
	if (song && songTakesLoaded(song)) return;
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

// A take the deck could not fetch stays skipped for the life of its queue,
// and is named once, when playback reaches the place it would have started.
interface SkipNotice {
	state: 'pending' | 'announced';
	index: number;
}

interface QueueSkips {
	skipped?: ReadonlyMap<PlaybackInfo, SkipNotice>;
}

type QueueContext = QueueSkips &
	(
		| { type: 'library'; takes?: PlaybackInfo[]; index?: number }
		| { type: 'album'; albumId: string; takes?: PlaybackInfo[]; index?: number }
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

function setQueueContext(ctx: QueueContext, opts: { curating?: boolean } = {}): void {
	queueContext.set(ctx);
	curationActive.set(opts.curating ?? false);
}

const SHUFFLE_STORAGE_KEY = 'queueShuffleEnabled';

function readStoredShuffle(): boolean {
	if (typeof window === 'undefined') return false;
	return readStorage(SHUFFLE_STORAGE_KEY) === 'true';
}

export const shuffleEnabled = writable(readStoredShuffle());

export function setShuffle(enabled: boolean): void {
	shuffleEnabled.set(enabled);
	if (typeof window !== 'undefined') {
		writeStorage(SHUFFLE_STORAGE_KEY, String(enabled));
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

// 'awaiting-network': a start that could not read its takes offline waits
// for the network, with nothing playing yet (#1288). 'gave-up-on-network':
// it waited as long as a stalled take does and now waits calmly, as a given-up
// take does, until the network's return runs it again (#1312). 'restoring':
// Play was pressed while the take a reload restores is still on its way
// (#1330).
type PlayStartNotice =
	'idle' | 'building' | 'awaiting-network' | 'gave-up-on-network' | 'restoring' | 'empty' | 'error';
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

function shuffledWithStart<T>(items: T[], startIndex: number): { items: T[]; startIndex: number } {
	if (!get(shuffleEnabled) || items.length <= 1) return { items, startIndex };
	const start = items[startIndex] ?? items[0];
	const rest = items.filter((_, index) => index !== startIndex);
	return { items: shuffled([start, ...rest], { keepFirst: true }), startIndex: 0 };
}

// Where an album start begins: at its first playable song, or at the song the
// listener tapped on the album page. shuffledWithStart keeps that start in
// front and shuffles only what follows it.
type AlbumStart = 'top' | { songId: string };

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
let playStartTenure: PlayerTenure = audioPlayer.tenure;

interface PlayStart {
	seq: number;
	signal: AbortSignal;
}

// A new start replaces whatever start came before it, a waiting one included.
function beginPlayStart(): PlayStart {
	dropPendingStart();
	return openPlayStart();
}

function openPlayStart(): PlayStart {
	cancelPlayStart();
	playStartAbort = new AbortController();
	playStartTenure = audioPlayer.tenure;
	return { seq: playStartSeq, signal: playStartAbort.signal };
}

function cancelPlayStart(): void {
	playStartAbort?.abort();
	playStartSeq += 1;
	retryPlayIntent = null;
}

// A start lands only while it is the newest one and the player has not
// changed hands since it began: one begun before a share route took the
// player, or while the share held it, is not the app's to land once the app
// holds it again (#1391).
function playStartIsCurrent(seq: number): boolean {
	return seq === playStartSeq && !audioPlayer.changedHandsSince(playStartTenure);
}

// Offline, the strip already says why a start could not reach its takes: the
// start keeps waiting where the listener sees it and runs again once the
// network is back, unless a newer start replaced it meanwhile (#1288).
function retryOnceBackOnline(
	err: unknown,
	signal: AbortSignal,
	retry: () => Promise<void>
): boolean {
	if (!(err instanceof NetworkError) || !get(offline)) return false;
	const stopWaiting = whenBackOnline(() => {
		stopWaiting();
		void retry().catch(toastAlbumSongsFailure);
	});
	signal.addEventListener('abort', stopWaiting, { once: true });
	return true;
}

// An album start that could not read its takes offline, held until a take of
// it plays: the bar and the lock screen, the only surface with the screen
// off, name the song it will play (#1312, #1330). A start paused from the
// lock screen stays named there, paused, until its Play runs it again.
interface PendingStart {
	albumId: string;
	song: LockScreenTitle;
}
const pendingStartState = writable<PendingStart | null>(null);
export const pendingStart = readonly(pendingStartState);

// Component tests hold a waiting start as this store would (#1330).
export function setPendingStartForTests(start: PendingStart | null): void {
	pendingStartState.set(start);
}
let runPendingStartAgain: ((playStart: PlayStart) => Promise<void>) | null = null;
let pendingStartGiveUp: ReturnType<typeof setTimeout> | undefined;

// The bar shows the start waiting until it runs again, a newer start
// replaces it, or the listener stops it. Running again once the network is
// back continues this same start, so nothing it shows lapses meanwhile. The
// start is what the listener asked to hear, so it takes the place of a take
// already loaded, and that take falls silent rather than play on under it.
function noticeStartAwaitingNetwork(
	start: PendingStart,
	runAgain: (playStart: PlayStart) => Promise<void>
): void {
	pendingStartState.set(start);
	runPendingStartAgain = runAgain;
	if (audioPlayer.current) audioPlayer.pause();
	updateMediaSessionMetadata(start.song);
	playStartNotice.set('awaiting-network');
	clearTimeout(pendingStartGiveUp);
	pendingStartGiveUp = setTimeout(
		() => playStartNotice.set('gave-up-on-network'),
		RECOVERY_DEADLINE_MS
	);
}

function stopPendingStartWait(): void {
	clearTimeout(pendingStartGiveUp);
	if (startAwaitsNetwork(get(playStartNotice))) playStartNotice.set('idle');
}

function dropPendingStart(): void {
	stopPendingStartWait();
	if (get(pendingStart) === null) return;
	pendingStartState.set(null);
	runPendingStartAgain = null;
	updateMediaSessionMetadata(audioPlayer.current);
}

// A take that plays is what the listener now hears, so a start still pending
// is over: the lock screen names that take, and the network starts nothing.
function endPendingStartForThePlayingTake(): void {
	if (get(pendingStart) === null) return;
	cancelPlayStart();
	dropPendingStart();
}

function lockScreenTitleOf(song: SongItem): LockScreenTitle {
	return { songTitle: song.title, artist: song.artist, albumTitle: song.album_title };
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
	if (!playsTheAppsTakes()) return;
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
	return queuePositionOf(
		ctx.takes,
		ctx.index ?? 0,
		(take) => take === current,
		(take) =>
			take.generation.id === current.generation.id &&
			take.generation.mp3_path === current.generation.mp3_path
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

// Moves the index within the queue that is already playing (Skip and Pick's
// auto-advance during curation, a queue-row jump, plain Previous/Next) —
// deliberately bypassing setQueueContext, so an advance never ends curation
// mode the way building a genuinely different queue does; a queue that
// wasn't curating stays not-curating either way.
function playNativeIndex(ctx: Exclude<QueueContext, { type: 'playlist' }>, index: number): void {
	const takes = ctx.takes;
	if (!takes || index < 0 || index >= takes.length) return;
	queueContext.set({ ...ctx, index });
	loadNativeTake(takes[index]);
}

interface LibraryTakeStart extends QueueStart {
	keepPlaying?: boolean;
	tappedRowSong?: SongItem;
	// A restore starts the queue at the saved position and reports nothing it
	// cannot rebuild (#1187 P2), so the listener who reopens the page is never
	// asked to retry a play they did not start. Whether it plays is decided
	// once its take is back, so a Play pressed meanwhile keeps its intent (#1330).
	restoredAt?: number;
}

function reportLibraryTakeStartFailure(
	gen: GenerationItem,
	opts: LibraryTakeStart,
	notice: PlayStartNotice,
	toast: string
): void {
	clearLibraryQueueSkipFeedback();
	if (opts.restoredAt !== undefined) return;
	retryPlayIntent = () => playLibraryFromGeneration(gen, opts);
	playStartNotice.set(notice);
	addToast(toast, 'error');
}

function currentTakeAtPosition(): { generation: GenerationItem; position: number } | null {
	const current = audioPlayer.current;
	if (!current) return null;
	return {
		generation: current.generation,
		position: audioPlayer.currentTimeNow ?? audioPlayer.currentTime
	};
}

// Where a library queue whose takes are back starts: a restore answers a
// Play pressed while they were on their way, and a continuation goes on from
// where the take that plays now stands.
function libraryQueueStart(
	opts: LibraryTakeStart,
	continuation: { position: number } | null
): QueueStart {
	if (opts.restoredAt !== undefined) return restoredStart(opts.restoredAt);
	playStartNotice.set('idle');
	return opts.keepPlaying ? { ...opts, resumeAtTrackTime: continuation?.position } : opts;
}

type LibraryPoolQueueResult = Awaited<ReturnType<typeof fetchLibraryPoolQueue>>;

// A failed fetch is reported here; null tells the caller to stop, whether the
// start was superseded or the failure is already on screen.
async function fetchLibraryTakeQueueOrReport(
	requested: GenerationItem,
	opts: LibraryTakeStart,
	play: { seq: number; signal: AbortSignal }
): Promise<LibraryPoolQueueResult | null> {
	try {
		const queue = await fetchLibraryPoolQueue({
			startGenerationId: requested.id,
			...librarySnapshotOpts(),
			signal: play.signal
		});
		return playStartIsCurrent(play.seq) ? queue : null;
	} catch (err) {
		if (!playStartIsCurrent(play.seq)) return null;
		reportLibraryTakeStartFailure(
			requested,
			opts,
			isEmptyPoolError(err) ? 'empty' : 'error',
			libraryStreamFailureToast(err)
		);
		return null;
	}
}

// A take row never plays alone (#1187 P6): when the pool holds only the
// tapped take, as it does before anything is picked, the row's song names the
// album the queue continues through instead.
async function playLibraryFromGeneration(
	gen: GenerationItem,
	opts: LibraryTakeStart = {}
): Promise<void> {
	const play = beginPlayStart();
	setQueueContext({ type: 'library' });
	// A restore waits as album and playlist restores do, with the transport
	// free to take a Play for the take it brings back.
	if (opts.restoredAt === undefined) playStartNotice.set('building');
	clearLibraryQueueSkipFeedback();
	clearWindowEnd();
	let requested = gen;
	for (;;) {
		const queue = await fetchLibraryTakeQueueOrReport(requested, opts, play);
		if (!queue) return;
		const takes = queue.takes.map(poolTakeToPlaybackInfo);
		const continuation = opts.keepPlaying ? currentTakeAtPosition() : null;
		const startGeneration = continuation?.generation ?? requested;
		const startIndex = takes.findIndex((take) => take.generation.id === startGeneration.id);
		// The pool only guarantees the take it was asked to start from; a take
		// the deck advanced to during the fetch may lie outside it, so the queue
		// is asked again from the take that is playing now.
		if (startIndex < 0 && startGeneration.id !== requested.id) {
			requested = startGeneration;
			continue;
		}
		if (startIndex < 0) {
			reportLibraryTakeStartFailure(startGeneration, opts, 'error', QUEUE_TAKE_MISSING_TOAST);
			return;
		}
		const start = libraryQueueStart(opts, continuation);
		if (takes.length === 1 && opts.tappedRowSong) {
			await playAlbumFromGeneration(opts.tappedRowSong.album_id, opts.tappedRowSong, gen);
			return;
		}
		libraryQueueSkipped.set(queue.skipped ?? []);
		libraryQueueSkippedComplete.set(queue.skipped_complete ?? true);
		playNativeLibraryTakes(takes, startIndex, start);
		return;
	}
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
		return { type: 'library', label: LIBRARY_PAGE_LABEL };
	}
	if (input.collection?.kind === 'album') {
		return {
			type: 'album',
			label: albumTitle(input.albums, input.collection.id),
			albumId: input.collection.id
		};
	}
	return { type: 'library', label: LIBRARY_PAGE_LABEL };
}

// The transport with no take: a start that waits for the network is what the
// listener asked for, so a press stops it rather than starting another.
export async function playIdleStart(): Promise<void> {
	if (stopStartAwaitingNetwork() || askForTheRestoringTake()) return;
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

// The bar and the lock screen show a start that waits for the network as the
// transport's own wait, whatever take is loaded, and their presses stop it
// (#1288, #1330).
function startAwaitsNetwork(notice: PlayStartNotice): boolean {
	return notice === 'awaiting-network' || notice === 'gave-up-on-network';
}

// The start the bar and the album header show as waiting, naming its song and
// its album, as the lock screen does (#1330).
export function waitingStartOf(
	notice: PlayStartNotice,
	pending: PendingStart | null
): PendingStart | null {
	return startAwaitsNetwork(notice) ? pending : null;
}

// A start that waits for the network shows the transport a take waiting for
// it shows: recovering at first, then given up after the same deadline
// (#1312). A Play pressed before a restored take arrived shows it loading,
// as a press on the take itself would (#1330).
export function transportOfTheStart(
	current: PlaybackInfo | null,
	notice: PlayStartNotice,
	transport: TransportState
): TransportState {
	if (!current && notice === 'restoring') return 'loading';
	if (!startAwaitsNetwork(notice)) return transport;
	return notice === 'gave-up-on-network' ? 'waiting-for-network' : 'recovering';
}

interface CollectionTransport {
	current: boolean;
	waiting: boolean;
	transport: TransportState;
}

// Store inputs stay subscribed by the surface; reading the callable also tracks
// the audio player's reactive transport without copying it into another store.
export const collectionTransport = derived(
	[playbackSource, playStartNotice, pendingStart],
	([$source, $notice, $pending]) =>
		(kind: PlaybackSource['kind'], id: string): CollectionTransport => {
			const current = audioPlayer.current !== null && $source?.kind === kind && $source.id === id;
			const waiting = kind === 'album' && waitingStartOf($notice, $pending)?.albumId === id;
			if (waiting) {
				return { current, waiting, transport: transportOfTheStart(null, $notice, 'idle') };
			}
			return { current, waiting, transport: current ? audioPlayer.transport : 'idle' };
		}
);

export function toggleOrStartCollection(
	kind: PlaybackSource['kind'],
	id: string,
	onstart: (() => void) | null
): void {
	const state = get(collectionTransport)(kind, id);
	if (state.waiting) stopStartAwaitingNetwork();
	else if (state.current) audioPlayer.toggle();
	else if (onstart) onstart();
}

// The bar's and the header's press withdraw a waiting start altogether.
function stopStartAwaitingNetwork(): boolean {
	if (!pauseStartAwaitingNetwork()) return false;
	dropPendingStart();
	return true;
}

// The lock screen pauses a waiting start the way it pauses a take: it stops
// waiting but stays named, and the lock screen's Play runs it again (#1330).
function pauseStartAwaitingNetwork(): boolean {
	if (!startAwaitsNetwork(get(playStartNotice))) return false;
	cancelPlayStart();
	stopPendingStartWait();
	return true;
}

function resumePausedStart(): boolean {
	const runAgain = runPendingStartAgain;
	if (runAgain === null) return false;
	if (startAwaitsNetwork(get(playStartNotice))) return true;
	const playStart = openPlayStart();
	playStartNotice.set('awaiting-network');
	void runAgain(playStart).catch(toastAlbumSongsFailure);
	return true;
}

function pauseFromLockScreen(): void {
	if (pauseStartAwaitingNetwork()) return;
	audioPlayer.pause();
}

function playFromLockScreen(): void {
	if (resumePausedStart()) return;
	audioPlayer.play();
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
	playPlaylist(playlist);
}

async function rebuildLibraryQueueKeepingPlace(): Promise<void> {
	if (!audioPlayer.current) return;
	if (get(queueContext).type !== 'library') return;
	await playLibraryFromGeneration(audioPlayer.current.generation, {
		keepPlaying: true
	});
}

async function rebuildQueueAfterShuffleToggle(): Promise<void> {
	if (!audioPlayer.current) return;
	const current = audioPlayer.current;
	const trackTime = audioPlayer.currentTime;
	const ctx = get(queueContext);
	if (ctx.type === 'library') {
		await playLibraryFromGeneration(current.generation, { keepPlaying: true });
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

export function canPlayPrevSong(
	current: PlaybackInfo | null,
	songs: SongItem[],
	ctx: QueueContext
): boolean {
	if (audioPlayer.mode === 'stream') return audioPlayer.canPrevStreamTrack;
	if (!current) return false;
	if (ctx.type === 'playlist' || (ctx.takes && ctx.takes.length > 0)) {
		return adjacentQueueTake(ctx, current, -1).kind === 'take';
	}
	if (ctx.type === 'library') return false;
	const pool = songs.filter((s) => s.album_id === ctx.albumId);
	return pool.filter(songHasPlayableTake).length > 1;
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
		return adjacentQueueTake(ctx, current).kind === 'take';
	}
	if (ctx.type === 'library') return false;
	const pool = songs.filter((s) => s.album_id === ctx.albumId);
	return pool.some((s) => s.id !== current.songId && songHasPlayableTake(s));
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
		if (!songHasPlayableTake(song)) continue;
		await ensureGenerationsLoaded(song.id);
		if (!playStartIsCurrent(seq)) return null;
		const fresh = get(songList).find((s) => s.id === song.id);
		if (!fresh) continue;
		const gen =
			start && fresh.id === start.song.id
				? (fresh.generations.find((g) => g.id === start.gen.id) ?? start.gen)
				: bestTake(fresh);
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
		const picked = song && pickedTake(song);
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
	const idx = queuePositionOf(
		ctx.entries,
		ctx.index,
		(entry) => playbackInfoOfEntry.get(entry) === current,
		(entry) => holdsEntryTake(current, entry)
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
// instead of poking `nowPlayingSurface`/`nowPlayingPanel` directly, so surface
// selection and focus restoration happen the same way for every entry point.
export function openNowPlaying(panel: NowPlayingPanel): void {
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

// The single playback entry point for a take row (TakesList):
// toggles pause if the row's take is already playing, otherwise starts a
// queue from it (its album, else the library pool), reporting any failure as
// a toast instead of throwing into the caller.
// A press on the row of the take that offers Pause, a waiting one included,
// is that Pause, as the bar's is (#1330).
export async function playTake(gen: GenerationItem, song: SongItem): Promise<void> {
	if (isTakeCurrent(gen) && transportOffersPause(audioPlayer.transport)) {
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

// A song box on the album page (#1383) does the same for the album: it plays
// the song with the rest of the album queued around it.
export async function playAlbumSong(albumId: string, songId: string): Promise<void> {
	await playRow({
		alreadyLoaded: isSongCurrent(songId),
		start: () => playAlbum(albumId, { songId })
	});
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

function adjacentQueueTake(
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
		if (!ctx.skipped?.has(take)) return { kind: 'take', index, take };
	}
	return windowEnd;
}

function takeAfterCurrent(): PlaybackInfo | null {
	return takeAfter(audioPlayer.current);
}

function takeAfter(take: PlaybackInfo | null): PlaybackInfo | null {
	const next = adjacentQueueTake(get(queueContext), take);
	return next.kind === 'take' ? next.take : null;
}

// What a reopened page shows once the current take has ended: the take the
// queue plays next, or, where the library window ends, the ended take itself,
// since a restored library queue builds its next window from there (#1236).
function takeAfterTheEnd(): PlaybackInfo | null {
	const next = adjacentQueueTake(get(queueContext), audioPlayer.current);
	if (next.kind === 'window-end') return audioPlayer.current;
	return next.kind === 'take' ? next.take : null;
}

function preloadNextTake(): void {
	if (playsTheAppsTakes()) audioPlayer.preload(takeAfterCurrent());
}

// A step always lands on another place of the playlist, so that place starts
// from its beginning even where it holds the very take playing now.
function playPlaylistInDirection(
	ctx: Extract<QueueContext, { type: 'playlist' }>,
	direction: QueueDirection
): void {
	const next = adjacentQueueTake(ctx, audioPlayer.current, direction);
	if (next.kind === 'take') playPlaylistIndex(ctx, next.index, { restart: true });
}

function playNativeTakesInDirection(
	ctx: Exclude<QueueContext, { type: 'playlist' }>,
	direction: QueueDirection
): void {
	const next = adjacentQueueTake(ctx, audioPlayer.current, direction);
	if (next.kind === 'window-end') windowEnded.set(true);
	if (next.kind === 'take') playNativeIndex(ctx, next.index);
}

// Every queue the app plays holds its takes: an album or library start loads
// its opening take as the queue at once and gathers the rest around it. Only
// the library context a reload begins with holds none, and nothing plays in
// it to step from.
function playContextInDirection(ctx: QueueContext, direction: QueueDirection): void {
	if (ctx.type === 'playlist') {
		playPlaylistInDirection(ctx, direction);
		return;
	}
	if (ctx.takes && ctx.takes.length > 0) playNativeTakesInDirection(ctx, direction);
}

export function playNextSong(): void {
	if (playStreamInDirection(1)) return;
	playContextInDirection(get(queueContext), 1);
}

export function playPrevSong(): void {
	if (playStreamInDirection(-1)) return;
	playContextInDirection(get(queueContext), -1);
}

// The album's opening take, which is not always the opening track's:
// A track with nothing playable (all takes archived or without a file) is
// skipped rather than taken as proof the album is unplayable. Returns null both when nothing is playable and when a newer
// play start superseded this one — the caller separates the two with its
// own playStartIsCurrent check. A rejected load (e.g. 429) is handed to the
// caller with the song whose takes it could not read.
async function firstPlayableAlbumTake(
	albumId: string,
	seq: number,
	start: AlbumStart
): Promise<{ song: SongItem; gen: GenerationItem } | { unread: SongItem; error: unknown } | null> {
	for (const song of albumSongsFrom(albumId, start)) {
		if (!songHasPlayableTake(song)) continue;
		try {
			await ensureGenerationsLoaded(song.id);
		} catch (error) {
			return { unread: song, error };
		}
		if (!playStartIsCurrent(seq)) return null;
		const fresh = get(songList).find((item) => item.id === song.id) ?? song;
		const gen = bestTake(fresh);
		if (gen) return { song: fresh, gen };
	}
	return null;
}

function albumSongsFrom(albumId: string, start: AlbumStart): SongItem[] {
	const inOrder = albumSongsInOrder(albumId);
	return start === 'top' ? inOrder : inOrder.filter((song) => song.id === start.songId);
}

// The album becomes the queue only once its opening take starts: an album
// that turns out to have nothing playable leaves the running queue, and the
// place it names as its source, exactly as they were.
export async function playAlbum(albumId: string, start: AlbumStart = 'top'): Promise<void> {
	const playStart = beginPlayStart();
	clearWindowEnd();
	clearLibraryQueueSkipFeedback();
	playStartNotice.set('building');
	await runAlbumStart(albumId, start, playStart);
}

async function runAlbumStart(
	albumId: string,
	start: AlbumStart,
	playStart: PlayStart
): Promise<void> {
	const { seq, signal } = playStart;
	if (albumSongsInOrder(albumId).length === 0) {
		await loadSongsForAlbum(albumId);
		if (!playStartIsCurrent(seq)) return;
	}
	const startTake = await firstPlayableAlbumTake(albumId, seq, start);
	if (!playStartIsCurrent(seq)) return;
	if (startTake && 'unread' in startTake) {
		const runAgain = (again: PlayStart) => runAlbumStart(albumId, start, again);
		const runAgainOnceBackOnline = () => {
			playStartNotice.set('awaiting-network');
			return runAgain(playStart);
		};
		if (retryOnceBackOnline(startTake.error, signal, runAgainOnceBackOnline)) {
			noticeStartAwaitingNetwork({ albumId, song: lockScreenTitleOf(startTake.unread) }, runAgain);
			return;
		}
		dropPendingStart();
		playStartNotice.set('idle');
		toastAlbumSongsFailure(startTake.error);
		return;
	}
	if (!startTake) {
		dropPendingStart();
		reportNothingPlayable(albumTitle(get(albumList), albumId), () => playAlbum(albumId, start));
		return;
	}
	playNativeAlbumTakes(albumId, [albumQueueTake(startTake.song, startTake.gen)], 0);
	playStartNotice.set('idle');
	dropPendingStart();
	await gatherAlbumQueueAround(albumId, startTake.song, startTake.gen, playStart);
}

async function playAlbumFromGeneration(
	albumId: string,
	song: SongItem,
	gen: GenerationItem,
	opts: QueueStart = {}
): Promise<void> {
	const playStart = beginPlayStart();
	clearWindowEnd();
	clearLibraryQueueSkipFeedback();
	playNativeAlbumTakes(albumId, [toPlaybackInfo(gen, song)], 0, opts);
	await gatherAlbumQueueAround(albumId, song, gen, playStart);
}

// Turns the one-take album queue a start loaded into the whole album, its
// takes in place around the one playing, unless a newer start superseded it.
async function gatherAlbumQueueAround(
	albumId: string,
	song: SongItem,
	gen: GenerationItem,
	playStart: PlayStart
): Promise<void> {
	const { seq, signal } = playStart;
	if (!playStartIsCurrent(seq)) return;
	await loadSongsForAlbum(albumId);
	if (!playStartIsCurrent(seq)) return;
	let entries: PlaylistEntryItem[] | null;
	try {
		entries = await collectAlbumEntries(albumId, seq, { song, gen });
	} catch (err) {
		const gatherAgain = () => gatherAlbumQueueAround(albumId, song, gen, playStart);
		if (!playStartIsCurrent(seq) || retryOnceBackOnline(err, signal, gatherAgain)) return;
		throw err;
	}
	if (entries === null || !playStartIsCurrent(seq)) return;
	setAlbumQueueTakes(albumId, entries, gen.id);
	preloadNextTake();
}

// The one entry point for curation: the same per-song candidate takes
// playAlbum already builds (existing pick, else bestTake), started at the
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
	ctx: Extract<QueueContext, { type: 'playlist' }>,
	newIndex: number,
	opts: QueueTakeLoad = {}
): void {
	if (newIndex < 0 || newIndex >= ctx.entries.length) return;
	queueContext.set({ ...ctx, index: newIndex });
	loadQueueTake(playlistEntryToPlaybackInfo(ctx.entries[newIndex]), opts);
}

function queueSourceOf(playlist: PlaylistDetailItem): PlaylistQueueSource {
	return { id: playlist.id, title: playlist.title };
}

// A whole-playlist start: the idle transport Play and the playlist header. It
// keeps the listener's shuffle setting, unlike playPlaylistFrom, where picking a
// specific entry is itself the statement that the queue should start in
// playlist order.
export function playPlaylist(playlist: PlaylistDetailItem): void {
	if (playlist.entries.length === 0) {
		reportNothingPlayable(playlist.title, () => {
			playPlaylist(playlist);
			return Promise.resolve();
		});
		return;
	}
	playStartNotice.set('idle');
	startPlaylistQueue(queueSourceOf(playlist), playlist.entries, 0, { restart: true });
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
	const startTake = ordered.items[ordered.startIndex];
	if (!startTake) return;
	setQueueContext({
		type: 'playlist',
		playlist,
		entries: ordered.items,
		index: ordered.startIndex
	});
	loadQueueTake(playlistEntryToPlaybackInfo(startTake), loadOpts);
}

setupMediaSessionHandlers({
	play: playFromLockScreen,
	pause: pauseFromLockScreen,
	stop: pauseFromLockScreen,
	next: () => {
		playNextSong();
	},
	prev: () => {
		playPrevSong();
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
	playNextSong();
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
	void recordSongListen(current.songId, playlistId)
		.then(outdateLastPlayedRanking)
		.catch((error: unknown) => {
			console.error('Could not record song listen:', error);
		});
}

function handlePlaybackStarted(): void {
	endPendingStartForThePlayingTake();
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
	announcePendingSkips();
	preloadNextTake();
}

// The deck plays on past the skipped take; the queue passes over it at once
// and names it when playback reaches its place, so the listener hears which
// one the queue lost instead of finding it silently gone.
function recordSkippedTake(take: PlaybackInfo): void {
	const ctx = get(queueContext);
	if (ctx.skipped?.has(take)) return;
	const skipped = new Map(ctx.skipped).set(take, {
		state: 'pending' as const,
		index: queuePlaceOf(ctx, take)
	});
	queueContext.set({ ...ctx, skipped });
	announcePendingSkips();
}

// A repick changes the take at a place, not the place awaiting its notice.
// No follower, or only the playing take, closes it without a take-change event (#1298).
function skipReachedOrClosed(ctx: QueueContext, take: PlaybackInfo, notice: SkipNotice): boolean {
	const atPlace =
		ctx.type === 'playlist'
			? playlistEntryToPlaybackInfo(ctx.entries[notice.index])
			: ctx.takes?.[notice.index];
	if (!atPlace) return true;
	const follower =
		atPlace !== take && !ctx.skipped?.has(atPlace)
			? { kind: 'take', index: notice.index }
			: adjacentQueueTake(ctx, atPlace);
	return follower.kind !== 'take' || follower.index === queuePlaceOf(ctx, audioPlayer.current);
}

function announcePendingSkips(): void {
	const ctx = get(queueContext);
	const reached = [...(ctx.skipped ?? [])].filter(
		([take, notice]) => notice.state === 'pending' && skipReachedOrClosed(ctx, take, notice)
	);
	if (reached.length === 0) return;
	const skipped = new Map(ctx.skipped);
	for (const [take, notice] of reached) {
		addToast(`${take.songTitle} couldn't be loaded, skipped.`, 'error');
		skipped.set(take, { ...notice, state: 'announced' });
	}
	queueContext.set({ ...ctx, skipped });
}

function queuePlaceOf(ctx: QueueContext, take: PlaybackInfo | null): number {
	return ctx.type === 'playlist' ? currentPlaylistIndex(ctx, take) : nativeTakeIndex(ctx, take);
}

function moveQueueIndexTo(current: PlaybackInfo): void {
	const ctx = get(queueContext);
	const index = queuePlaceOf(ctx, current);
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
	onStreamRebuild: null,
	onCurrentChange: handleCurrentChange,
	takeAfter,
	onTakeSkipped: recordSkippedTake,
	networkFailureIsAnnounced: leaveNetworkFailureToTheStrip,
	onPlayerTaken: letGoOfThePlayer
};
audioPlayer.swapCallbacks(appPlayerCallbacks);

// A share route owns the player while it swaps in its own callbacks: share
// playback is never remembered, and no take of the app's loads or sounds in
// it meanwhile — a share link shows only what was shared (#1391).
function playsTheAppsTakes(): boolean {
	return audioPlayer.currentCallbacks === appPlayerCallbacks;
}

// A share route took the player. Nothing the app still had under way lands
// in it: a start waiting on the server or the network, a Play pressed while
// the saved take was on its way, an album still to gather, a take waiting to
// play on once the network is back. The lock screen stops naming the take
// the app let go of, and stops saying it plays.
function letGoOfThePlayer(): void {
	cancelPlayStart();
	dropPendingStart();
	playStartNotice.set('idle');
	restoredAlbumQueueToGather = null;
	stopWaitingForReturn?.();
	stopWaitingForReturn = null;
	updateMediaSessionMetadata(null);
	updateMediaSessionPlaybackState('none');
	clearMediaSessionPositionState();
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
	if (saved === null || !playsTheAppsTakes()) return;
	const tenure = audioPlayer.tenure;
	if (!restoreMayLoad(tenure)) return;
	restoringIn = tenure;
	try {
		await restoreSavedPlayback(saved, tenure);
	} finally {
		endRestore(tenure);
	}
}

async function restoreSavedPlayback(saved: SavedPlayback, tenure: PlayerTenure): Promise<void> {
	const found = await playableSavedTake(saved);
	if (found === null || !restoreMayLoad(tenure)) return;
	const at = positionWithinTake(saved.position, found.take);
	const { source } = saved;
	if (source.type === 'album') {
		restoreAlbumTake(found.song, found.take, restoredStart(at));
	} else if (source.type === 'library') {
		await restoreLibraryTake(source, found.take, at);
	} else {
		await restorePlaylistQueue(source.playlistId, found.take, at, tenure);
	}
}

// A take loaded in the meantime is never replaced. A player that changed
// hands since the restore began is not the restore's to fill: a share route
// took it, and once it gives it back, what the restore asked for before is
// not what the listener came back to (#1391).
function restoreMayLoad(tenure: PlayerTenure): boolean {
	return audioPlayer.current === null && !audioPlayer.changedHandsSince(tenure);
}

// A Play pressed after a reload, before the saved take is back, keeps its
// intent: the transport reads Pause with its spinner, a second press
// withdraws it, and the take plays from its saved position once it is back
// (#1330). The restore under way is named by the tenure it began in and is
// over once the player changed hands, whatever its request still waits on:
// a Play pressed in the app after that starts what the transport names
// (#1391).
let restoringIn: PlayerTenure | null = null;

function restoreIsUnderway(): boolean {
	return restoringIn !== null && !audioPlayer.changedHandsSince(restoringIn);
}

function askForTheRestoringTake(): boolean {
	if (!restoreIsUnderway()) return false;
	playStartNotice.set(get(playStartNotice) === 'restoring' ? 'idle' : 'restoring');
	return true;
}

// Where the restored take starts, and whether it plays: the press, if any,
// is answered here, so a later one goes to the take itself.
function restoredStart(resumeAtTrackTime: number): QueueStart {
	const askedForSound = get(playStartNotice) === 'restoring';
	restoringIn = null;
	if (askedForSound) playStartNotice.set('idle');
	return { resumeAtTrackTime, autoplay: askedForSound };
}

// A restore that ends without its take answers the press it kept, unless a
// newer restore, begun once the app held the player again, keeps it now.
function endRestore(tenure: PlayerTenure): void {
	if (restoringIn !== tenure) return;
	restoringIn = null;
	playWhatWasAskedForIfNothingWasRestored();
}

// A saved take that cannot come back leaves the press to start what the
// transport names, as it would have without a reload; a take the listener
// started in the meantime has already answered it.
function playWhatWasAskedForIfNothingWasRestored(): void {
	if (get(playStartNotice) !== 'restoring') return;
	playStartNotice.set('idle');
	if (audioPlayer.current === null) void playIdleStart();
}

// The device's library settings are what build, extend and save a library
// queue, so a restored one takes on the settings its record names; the pool
// and shuffle controls then show the queue that plays (#1236).
async function restoreLibraryTake(
	source: Extract<ResumeQueueSource, { type: 'library' }>,
	take: GenerationItem,
	at: number
): Promise<void> {
	setLibraryTakePool(source.pool);
	setShuffle(source.shuffle);
	await playLibraryFromGeneration(take, { restoredAt: at });
}

// Gathering an album's takes costs a request per song, so a restored album
// take names its album queue at once but gathers the album's other takes only
// once it plays, not on every reload (#1236).
let restoredAlbumQueueToGather: (() => Promise<void>) | null = null;
let restoredAlbumQueueGathering: Promise<void> | null = null;

function restoreAlbumTake(song: SongItem, take: GenerationItem, start: QueueStart): void {
	const playStart = beginPlayStart();
	playNativeAlbumTakes(song.album_id, [toPlaybackInfo(take, song)], 0, start);
	restoredAlbumQueueToGather = () => gatherAlbumQueueAround(song.album_id, song, take, playStart);
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
	const take = song.generations.find((gen) => gen.id === saved.generationId && isPlayableTake(gen));
	return take === undefined ? null : { song, take };
}

// A playlist deleted, out of reach, or no longer holding the take restores
// nothing, as a lost take does.
async function restorePlaylistQueue(
	playlistId: string,
	take: GenerationItem,
	at: number,
	tenure: PlayerTenure
): Promise<void> {
	const playlist = await quietly(() => fetchPlaylist(playlistId));
	if (playlist === null || !restoreMayLoad(tenure)) return;
	const index = playlist.entries.findIndex((entry) => entry.generation_id === take.id);
	if (index < 0) return;
	startPlaylistQueue(queueSourceOf(playlist), playlist.entries, index, {
		restart: true,
		...restoredStart(at)
	});
}

async function quietly<T>(request: () => Promise<T>): Promise<T | null> {
	try {
		return await request();
	} catch (err) {
		if (err instanceof ApiError || err instanceof NetworkError) return null;
		throw err;
	}
}
