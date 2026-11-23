import { writable, derived, get, readonly } from 'svelte/store';
import { NetworkError } from '#lib/api/fetch.ts';
import { fetchLibraryPoolQueue, fetchSong } from '#lib/api/client.ts';
import { recordSongListen } from '#lib/api/songs.ts';
import { bestTake, songHasPlayableTake, songTakesLoaded } from '#lib/utils/playable.ts';
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
	loadSavedPlaylist,
	loadSavedTake,
	savedPlayback,
	type ResumeQueueSource,
	type SavedPlayback
} from '#lib/stores/playbackResume.ts';
import { pageText, type TextKey } from '#lib/utils/page-words.ts';
import { type NowPlayingSurfaceKind, type PlaybackSource } from '#lib/constants/now-playing.ts';
import {
	adjacentQueueTake,
	albumQueueTake,
	albumTitle,
	curationActive,
	currentPlaylistIndex,
	followPicksAheadInAlbumQueue,
	holdsEntryTake,
	libraryQueueSkippedComplete,
	nativeTakeIndex,
	playbackSource,
	playlistEntryToPlaybackInfo,
	queueContext,
	setQueueContext,
	songQueueTakeIsGone,
	songTakeQueue,
	toAlbumQueueEntry,
	toPlaybackInfo,
	type PlaylistQueueSource,
	type QueueContext,
	type QueueDirection,
	type SkipNotice,
	type SongQueue
} from '#lib/stores/queue.ts';
import { isEmptyPoolError, libraryStreamFailureToast } from '#lib/stores/libraryQueueFailure.ts';
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

// A load a test left waiting must not answer the next test's request.
export function forgetSongGenerationLoadsForTests(): void {
	songGenerationLoads.clear();
}

export function clearGenerationSelection(): void {
	selectedGenerationId.set(null);
}

// --- Playback queue context ---

songList.subscribe((songs) => {
	if (followPicksAheadInAlbumQueue(songs)) preloadNextTake();
	if (get(queueContext).type === 'song') preloadNextTake();
});

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

const SHUFFLE_LABEL_KEYS = {
	library: { on: 'transport.unshuffleLibrary', off: 'transport.shuffleLibrary' },
	album: { on: 'transport.unshuffleAlbum', off: 'transport.shuffleAlbum' },
	playlist: { on: 'transport.unshufflePlaylist', off: 'transport.shufflePlaylist' },
	song: { on: 'transport.unshuffleSong', off: 'transport.shuffleSong' }
} as const satisfies Record<QueueContext['type'], Record<'on' | 'off', TextKey>>;

// Every shuffle control (transport bar, Now Playing) names the same scope
// from the same place, so the two can never disagree about what a toggle
// would shuffle.
export const shuffleLabel = derived([shuffleEnabled, queueContext], ([$enabled, $ctx]) =>
	pageText(SHUFFLE_LABEL_KEYS[$ctx.type][$enabled ? 'on' : 'off'])
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

function reportNothingPlayable(retry: () => Promise<void>): void {
	retryPlayIntent = retry;
	playStartNotice.set('empty');
	clearLibraryQueueSkipFeedback();
	addToast(pageText('player.nothingToPlay'), 'error');
}

// Offline, the one strip already says why the songs could not load (#1039).
function toastAlbumSongsFailure(err: unknown): void {
	if (err instanceof NetworkError && get(offline)) return;
	addToast(albumSongsErrorMessage(err), 'error');
}

// --- Playback dispatch ---

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

// Moves the index within the queue that is already playing (Skip and Pick's
// auto-advance during curation, a queue-row jump, plain Previous/Next) —
// deliberately bypassing setQueueContext, so an advance never ends curation
// mode the way building a genuinely different queue does; a queue that
// wasn't curating stays not-curating either way.
function playNativeIndex(ctx: Exclude<QueueContext, { type: 'playlist' }>, index: number): void {
	const takes = ctx.takes;
	if (!takes || index < 0 || index >= takes.length) return;
	if (ctx.type === 'song' && songQueueTakeIsGone(ctx, takes[index], get(songList))) return;
	queueContext.set({ ...ctx, index });
	loadNativeTake(takes[index]);
}

interface LibraryTakeStart extends QueueStart {
	keepPlaying?: boolean;
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
			reportLibraryTakeStartFailure(
				startGeneration,
				opts,
				'error',
				pageText('player.takeNotInQueue')
			);
			return;
		}
		const start = libraryQueueStart(opts, continuation);
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
		reportNothingPlayable(() => playLibrary(opts));
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
				label: input.listedPlaylist?.title ?? pageText('player.playlistLoading'),
				playlistId
			};
		}
		// A detail that failed to load has nothing to natively play -- fall
		// back to the named library target instead of a dead Play button.
		return { type: 'library', label: pageText('places.library') };
	}
	if (input.collection?.kind === 'album') {
		return {
			type: 'album',
			label: albumTitle(input.albums, input.collection.id),
			albumId: input.collection.id
		};
	}
	return { type: 'library', label: pageText('places.library') };
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
	if (ctx.type === 'song') {
		const index = ctx.inListOrder.findIndex((take) => take.generation.id === current.generation.id);
		if (index < 0) return;
		startSongQueue({ ...ctx, takes: ctx.inListOrder, index }, { resumeAtTrackTime: trackTime });
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
		return adjacentQueueTake(ctx, songs, current, -1).kind === 'take';
	}
	if (ctx.type !== 'album') return false;
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
		return adjacentQueueTake(ctx, songs, current).kind === 'take';
	}
	if (ctx.type !== 'album') return false;
	const pool = songs.filter((s) => s.album_id === ctx.albumId);
	return pool.some((s) => s.id !== current.songId && songHasPlayableTake(s));
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

songList.subscribe(followPicksAheadInAlbumQueue);

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
// closes it (PlayerBar's button, a rail playlist row via
// playPlaylistEntryAndShowNowPlaying, NowPlayingTake's Repaint/Cover action) routes through these two functions
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

// The single playback entry point for a take row (TakesList): a tap on the
// row of the take the transport holds is that take's play or pause, any other
// starts the song's takes as a queue, the tapped one first. A tap says "play
// from here", so no leftover shuffle reorders the queue, as with a playlist
// entry. The listener stays where they are; the bar and the playing row show
// the result.
export function playTake(gen: GenerationItem, song: SongItem): void {
	if (isTakeCurrent(gen)) {
		audioPlayer.toggle();
		return;
	}
	const queue = songTakeQueue(song, gen.id);
	if (queue === null) return;
	setShuffle(false);
	startSongQueue(queue);
}

function startSongQueue(queue: SongQueue, start: QueueStart = {}): void {
	beginPlayStart();
	clearWindowEnd();
	clearLibraryQueueSkipFeedback();
	playStartNotice.set('idle');
	const ordered = shuffledWithStart(queue.takes, queue.index);
	setQueueContext({ ...queue, takes: ordered.items, index: ordered.startIndex });
	loadNativeTake(ordered.items[ordered.startIndex], firstTakeLoad(start));
}

type TakeRow = { alreadyLoaded: boolean; start: () => void | Promise<void> };

// A row on a page that shows the playing row itself never stops the music.
// The take a row stands for is left running, and a paused one picks up where
// it stands rather than starting over. Pausing belongs to the transport.
async function playRow(row: TakeRow): Promise<void> {
	if (row.alreadyLoaded) audioPlayer.play();
	else await row.start();
}

// Whether a take is the one the transport holds. The generation's id settles
// it.
function isTakeCurrent(gen: GenerationItem): boolean {
	return audioPlayer.current?.generation.id === gen.id;
}

function playlistEntryRow(playlist: PlaylistDetailItem, index: number): TakeRow {
	const entry = playlist.entries[index];
	return {
		alreadyLoaded: entry !== undefined && isPlaylistEntryCurrent(entry, get(queueContext)),
		start: () => playPlaylistFrom(playlist, index)
	};
}

// What a click on a rail playlist row means where it has no page of its own to
// show the result: play the entry and surface Now Playing straight on its
// judging panel. Clicking the entry already loaded only brings up the panel.
export async function playPlaylistEntryAndShowNowPlaying(
	playlist: PlaylistDetailItem,
	index: number
): Promise<void> {
	await playRow(playlistEntryRow(playlist, index));
	openNowPlaying('take');
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

function playStreamInDirection(direction: QueueDirection): boolean {
	if (audioPlayer.mode !== 'stream') return false;
	if (direction === 1) audioPlayer.nextStreamTrack();
	else audioPlayer.prevStreamTrack();
	return true;
}

function takeAfterCurrent(): PlaybackInfo | null {
	return takeAfter(audioPlayer.current);
}

function takeAfter(take: PlaybackInfo | null): PlaybackInfo | null {
	const next = adjacentQueueTake(get(queueContext), get(songList), take);
	return next.kind === 'take' ? next.take : null;
}

// What a reopened page shows once the current take has ended: the take the
// queue plays next, or, where the library window ends, the ended take itself,
// since a restored library queue builds its next window from there (#1236).
function takeAfterTheEnd(): PlaybackInfo | null {
	const next = adjacentQueueTake(get(queueContext), get(songList), audioPlayer.current);
	if (next.kind === 'window-end') return audioPlayer.current;
	return next.kind === 'take' ? next.take : null;
}

// A take of a song queue can be archived, lose its audio or be deleted while it
// waits as the next one, already loading: with none left to follow, what was
// readied is taken back.
function preloadNextTake(): void {
	if (!playsTheAppsTakes()) return;
	const next = takeAfterCurrent();
	if (next || get(queueContext).type !== 'song') audioPlayer.preload(next);
	else audioPlayer.withdrawPreload();
}

// A step always lands on another place of the playlist, so that place starts
// from its beginning even where it holds the very take playing now.
function playPlaylistInDirection(
	ctx: Extract<QueueContext, { type: 'playlist' }>,
	direction: QueueDirection
): void {
	const next = adjacentQueueTake(ctx, get(songList), audioPlayer.current, direction);
	if (next.kind === 'take') playPlaylistIndex(ctx, next.index, { restart: true });
}

function playNativeTakesInDirection(
	ctx: Exclude<QueueContext, { type: 'playlist' }>,
	direction: QueueDirection
): void {
	const next = adjacentQueueTake(ctx, get(songList), audioPlayer.current, direction);
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
		reportNothingPlayable(() => playAlbum(albumId, start));
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
		reportNothingPlayable(() => curateAlbum(albumId));
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
		reportNothingPlayable(() => {
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
			: adjacentQueueTake(ctx, get(songList), atPlace);
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
		addToast(pageText('player.takeSkipped', { title: take.songTitle }), 'error');
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
	if (ctx.type === 'song') return { type: 'song' };
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
	const found = await loadSavedTake(saved);
	if (found === null || !restoreMayLoad(tenure)) return;
	const at = positionWithinTake(saved.position, found.take);
	const { source } = saved;
	if (source.type === 'album') {
		restoreAlbumTake(found.song, found.take, restoredStart(at));
	} else if (source.type === 'song') {
		restoreSongQueue(found.song, found.take, at);
	} else if (source.type === 'library') {
		await restoreLibraryTake(source, found.take, at);
	} else {
		await restorePlaylistQueue(saved, source.playlistId, at, tenure);
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

// The saved take's song is in hand once the take is found, so its queue comes
// back whole at once.
function restoreSongQueue(song: SongItem, take: GenerationItem, at: number): void {
	const queue = songTakeQueue(song, take.id);
	if (queue !== null) startSongQueue(queue, restoredStart(at));
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

// A playlist deleted, out of reach, or no longer holding the take restores
// nothing, as a lost take does.
async function restorePlaylistQueue(
	saved: SavedPlayback,
	playlistId: string,
	at: number,
	tenure: PlayerTenure
): Promise<void> {
	const found = await loadSavedPlaylist(saved, playlistId);
	if (found === null || !restoreMayLoad(tenure)) return;
	const { playlist, index } = found;
	startPlaylistQueue(queueSourceOf(playlist), playlist.entries, index, {
		restart: true,
		...restoredStart(at)
	});
}
