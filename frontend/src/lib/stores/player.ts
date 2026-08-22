import { writable, derived, get } from 'svelte/store';
import { ApiError } from '$lib/api/fetch';
import {
	createLibraryQueueStreamSnapshot,
	createQueueStreamSnapshot,
	fetchLibraryPoolQueue,
	fetchSong,
	fetchSongs
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
import { addToast } from '$lib/stores/toast';
import {
	LIBRARY_TAKE_POOL_LABELS,
	libraryTakePool,
	queuePlaybackMode,
	setLibraryTakePool,
	shouldUseQueueStream,
	type LibraryTakePool
} from '$lib/stores/playbackSettings';
import { selectedPlaylistDetail } from '$lib/stores/playlists';
import { closeSidebar } from '$lib/stores/ui';
import {
	LIBRARY_QUEUE_EMPTY_TITLE,
	LIBRARY_SONG_PAGE_SIZE,
	QUEUE_STREAM_EMPTY_POOL_PREFIX,
	QUEUE_STREAM_UNPLAYABLE_START_DETAIL,
	QUEUE_TAKE_MISSING_TOAST,
	RAIL_LIBRARY_LABEL
} from '$lib/constants';

// --- Data ---
export const albumList = writable<AlbumItem[]>([]);
export const songList = writable<SongItem[]>([]);

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
export type QueueContext =
	| { type: 'library'; takes?: PlaybackInfo[]; index?: number }
	| { type: 'album'; albumId: string; takes?: PlaybackInfo[]; index?: number }
	| { type: 'playlist'; entries: PlaylistEntryItem[]; index: number };

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
	return `${poolLabel()} queue failed. Tap play to retry.`;
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

function streamLoadOpts(
	restart: boolean,
	track: QueueStreamManifest['tracks'][number] | undefined,
	resumeAtTrackTime: number | undefined
): { restart: boolean; resumeAt?: number } {
	if (resumeAtTrackTime === undefined || !track) return { restart };
	return { restart, resumeAt: track.start_offset + resumeAtTrackTime };
}

function showWindowedNotice(trackCount: number): void {
	addToast(
		`Streaming the first ${trackCount} tracks — the queue is longer than one stream allows.`,
		'info'
	);
}

// A failed stream start remembers what the listener actually asked for, so the
// "tap play to retry" affordance replays that exact intent instead of falling
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

export async function playStreamEntries(
	entries: PlaylistEntryItem[],
	startIndex: number,
	opts: { restart?: boolean; resumeAtTrackTime?: number }
): Promise<void> {
	clearWindowEnd();
	clearLibraryQueueSkipFeedback();
	let manifest: QueueStreamManifest;
	try {
		manifest = await createQueueStreamSnapshot(
			entries.map((entry) => ({
				generation_id: entry.generation_id,
				entry_id: entry.id
			}))
		);
	} catch {
		retryPlayIntent = () => playStreamEntries(entries, startIndex, opts);
		addToast('Stream unavailable. Tap play to retry.', 'error');
		return;
	}
	retryPlayIntent = null;
	audioPlayer.loadStream(
		manifest,
		startIndex,
		streamLoadOpts(opts.restart ?? true, manifest.tracks[startIndex], opts.resumeAtTrackTime)
	);
	if (manifest.windowed) {
		showWindowedNotice(manifest.tracks.length);
	}
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
		await playPlaylist(playlist);
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
	const currentIndex = currentPlaylistIndex(ctx, current);
	await playPlaylistEntries(ctx.entries, currentIndex >= 0 ? currentIndex : ctx.index, {
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

export function canPlayPrevGen(current: PlaybackInfo | null, songs: SongItem[]): boolean {
	if (!current) return false;
	const song = songs.find((s) => s.id === current.songId);
	if (!song) return false;
	const idx = song.generations.findIndex((g) => g.id === current.generation.id);
	return idx > 0;
}

export function canPlayNextGen(current: PlaybackInfo | null, songs: SongItem[]): boolean {
	if (!current) return false;
	const song = songs.find((s) => s.id === current.songId);
	if (!song) return false;
	const idx = song.generations.findIndex((g) => g.id === current.generation.id);
	return idx >= 0 && idx < song.generations.length - 1;
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

export function playNextGeneration(): void {
	const cur = audioPlayer.current;
	if (!cur) return;
	const songs = get(songList);
	const song = songs.find((s) => s.id === cur.songId);
	if (!song) return;
	const gens = song.generations;
	const idx = gens.findIndex((g) => g.id === cur.generation.id);
	if (idx < gens.length - 1) {
		playGeneration(gens[idx + 1], song);
	}
}

export function playPrevGeneration(): void {
	const cur = audioPlayer.current;
	if (!cur) return;
	const songs = get(songList);
	const song = songs.find((s) => s.id === cur.songId);
	if (!song) return;
	const gens = song.generations;
	const idx = gens.findIndex((g) => g.id === cur.generation.id);
	if (idx > 0) {
		playGeneration(gens[idx - 1], song);
	}
}

function bestGen(song: SongItem): GenerationItem | undefined {
	return song.generations.find((g) => g.is_picked) ?? song.generations[0];
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

function nativeQueueItem(take: PlaybackInfo, songs: SongItem[]): QueueRowItem {
	return {
		key: `${take.songId}:${take.generation.id}`,
		songId: take.songId,
		songTitle: take.songTitle,
		generationId: take.generation.id,
		// SongItem.audio_duration is the latest version's requested duration,
		// not this specific take's actual length — PlaybackInfo carries no
		// per-take duration (that lives only on the loaded <audio> element).
		// Good enough for a queue row estimate; the transport's own progress
		// bar shows the real duration once the take is playing.
		durationSec: songs.find((s) => s.id === take.songId)?.audio_duration ?? null,
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
		durationSec: entry.audio_duration,
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
		const items = ctx.entries.map(playlistQueueItem);
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

// Whether the Now Playing surface is mounted, and which of its right-panel
// tabs it should open on. Owned here (not by PlayerBar, which only reads
// them) so any surface — a take row, a deep link — can open Now Playing
// straight to the judging panel without routing through PlayerBar's own
// open/close click handlers.
export const nowPlayingOpen = writable(false);
export type NowPlayingPanel = 'queue' | 'take';
export const nowPlayingPanel = writable<NowPlayingPanel>('queue');

// The element to return focus to when Now Playing closes. PlayerBar
// registers its own "Now Playing" button here once on mount — every opener
// (PlayerBar's button, a TakesList row, NowPlayingTake's "Use as reference")
// shares that single restore target instead of each tracking its own.
let nowPlayingFocusTrigger: HTMLElement | null = null;

export function registerNowPlayingTrigger(el: HTMLElement | null): void {
	nowPlayingFocusTrigger = el;
}

// The single open/close owner for Now Playing: every surface that opens or
// closes it (PlayerBar's button, a TakesList row via playTakeAndShowNowPlaying,
// NowPlayingTake's "Use as reference") routes through these two functions
// instead of poking `nowPlayingOpen`/`nowPlayingPanel` directly, so closing
// the mobile rail drawer on open and restoring focus on close happen exactly
// once, the same way, regardless of entry point.
export function openNowPlaying(panel: NowPlayingPanel): void {
	closeSidebar();
	nowPlayingPanel.set(panel);
	nowPlayingOpen.set(true);
}

export function closeNowPlaying(): void {
	if (!get(nowPlayingOpen)) return;
	nowPlayingOpen.set(false);
	const trigger = nowPlayingFocusTrigger;
	queueMicrotask(() => trigger?.focus());
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

// TakesList's row body: play the take and surface Now Playing straight on
// its judging panel. Distinct from playTake (used by TakeStrip's dedicated
// play chip), which never opens Now Playing.
export async function playTakeAndShowNowPlaying(
	gen: GenerationItem,
	song: SongItem
): Promise<void> {
	await playTake(gen, song);
	openNowPlaying('take');
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
	const startSong = albumSongsInOrder(albumId).find((song) => song.generation_count > 0);
	if (startSong) await ensureGenerationsLoaded(startSong.id);
	if (!playStartIsCurrent(seq)) return;
	const freshStart = startSong
		? (get(songList).find((item) => item.id === startSong.id) ?? startSong)
		: undefined;
	const startGen = freshStart ? bestGen(freshStart) : undefined;
	if (!freshStart || !startGen) {
		reportNothingPlayable(albumTitle(get(albumList), albumId), () => playAlbum(albumId));
		return;
	}
	playStartNotice.set('idle');
	playNativeAlbumTakes(
		albumId,
		[playlistEntryToPlaybackInfo(toAlbumQueueEntry(freshStart, startGen))],
		0
	);
	await loadSongsForAlbum(albumId);
	if (!playStartIsCurrent(seq)) return;
	const entries = await collectAlbumEntries(albumId, seq);
	if (entries === null || !playStartIsCurrent(seq)) return;
	setAlbumQueueTakes(albumId, entries, startGen.id);
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
	ctx: { entries: PlaylistEntryItem[]; index: number },
	newIndex: number,
	opts: { restart?: boolean; startAt?: number } = {}
): void {
	if (newIndex < 0 || newIndex >= ctx.entries.length) return;
	const entry = ctx.entries[newIndex];
	queueContext.set({ type: 'playlist', entries: ctx.entries, index: newIndex });
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

async function playPlaylist(playlist: PlaylistDetailItem): Promise<void> {
	if (playlist.entries.length === 0) {
		reportNothingPlayable(playlist.title, () => playPlaylist(playlist));
		return;
	}
	playStartNotice.set('idle');
	await playPlaylistEntries(playlist.entries, 0, { restart: true });
}

export async function playPlaylistEntries(
	entries: PlaylistEntryItem[],
	startIndex = 0,
	opts: { restart?: boolean; resumeAtTrackTime?: number } = {}
): Promise<void> {
	beginPlayStart();
	clearWindowEnd();
	clearLibraryQueueSkipFeedback();
	const ordered = shuffledWithStart(entries, startIndex);
	const loadOpts: { restart?: boolean; startAt?: number } = { restart: opts.restart };
	if (opts.resumeAtTrackTime !== undefined) loadOpts.startAt = opts.resumeAtTrackTime;
	playPlaylistIndex(
		{ entries: ordered.items, index: ordered.startIndex },
		ordered.startIndex,
		loadOpts
	);
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

audioPlayer.onStreamRebuild = rebuildQueueStream;
audioPlayer.onCurrentChange = updateMediaSessionMetadata;
audioPlayer.onPlaybackStarted = clearWindowEnd;

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
		version_number: null,
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

// --- Song/album list mutations ---
export function retainRicherSong(current: SongItem | undefined, incoming: SongItem): SongItem {
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

export type AlbumSongsLoadStatus = 'idle' | 'loading' | 'error';

export interface AlbumSongsLoadState {
	status: AlbumSongsLoadStatus;
	error: string | null;
}

export const albumSongsLoad = writable<Readonly<Record<string, AlbumSongsLoadState>>>({});

export async function loadSongsForAlbum(albumId: string): Promise<void> {
	const inflight = albumSongLoads.get(albumId);
	if (inflight) return inflight;
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

function albumSongsErrorMessage(err: unknown): string {
	if (err instanceof ApiError) return err.detail || err.message;
	if (err instanceof Error) return err.message;
	return 'Failed to load songs';
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

export function updateGenerationScores(
	genId: string,
	update: Record<string, number | string>
): void {
	updateGenerationInList(genId, (gen) => ({
		...gen,
		scores: { ...gen.scores, ...update }
	}));
}

export function handlePlaybackEnded(reason: 'normal' | 'window-end' = 'normal'): void {
	if (reason === 'window-end') {
		windowEnded.set(true);
		return;
	}
	void playNextSong();
}

audioPlayer.onEnded = handlePlaybackEnded;

audioPlayer.onAuthLost = async () => {
	const { clearAuth } = await import('$lib/stores/auth');
	const { goto } = await import('$app/navigation');
	clearAuth();
	await goto('/login');
};
