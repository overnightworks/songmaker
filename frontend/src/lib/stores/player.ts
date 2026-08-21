import { writable, derived, get } from 'svelte/store';
import { ApiError } from '$lib/api/fetch';
import {
	createLibraryQueueStreamSnapshot,
	createQueueStreamSnapshot,
	fetchSong,
	fetchSongs
} from '$lib/api/client';
import type {
	AlbumItem,
	GenerationItem,
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
import { addToast } from '$lib/stores/toast';
import {
	LIBRARY_TAKE_POOL_LABELS,
	libraryTakePool,
	queuePlaybackMode,
	setLibraryTakePool,
	shouldUseQueueStream,
	type LibraryTakePool
} from '$lib/stores/playbackSettings';
import {
	LIBRARY_SONG_PAGE_SIZE,
	QUEUE_STREAM_EMPTY_POOL_PREFIX,
	QUEUE_STREAM_UNPLAYABLE_START_DETAIL,
	QUEUE_TAKE_MISSING_TOAST
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

const _loadingIds = new Set<string>();

export async function ensureGenerationsLoaded(songId: string): Promise<void> {
	const songs = get(songList);
	const song = songs.find((s) => s.id === songId);
	// A song already in the list with its generations (or none) needs no fetch. A song
	// NOT in the list — opened directly from a playlist, search, or URL rather than by
	// opening its album — must be fetched and added, not bailed on: otherwise its detail
	// view stays empty until the album is opened.
	if (song && (song.generations.length > 0 || song.generation_count === 0)) return;
	if (_loadingIds.has(songId)) return;
	_loadingIds.add(songId);
	try {
		const full = await fetchSong(songId);
		upsertSongInList(full);
	} finally {
		_loadingIds.delete(songId);
	}
}

export function selectGenerationInSidebar(gen: GenerationItem, song: SongItem): void {
	selectedSongId.set(song.id);
	selectedGenerationId.set(gen.id);
}

export function clearGenerationSelection(): void {
	selectedGenerationId.set(null);
}

// --- Playback queue context ---
type QueueContext =
	| { type: 'library' }
	| { type: 'album'; albumId: string }
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

export type LibraryQueueNotice = 'idle' | 'building' | 'empty' | 'error';
export const libraryQueueNotice = writable<LibraryQueueNotice>('idle');
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

function libraryStreamFailureToast(err: unknown): string {
	if (isEmptyPoolError(err)) return `Keine Takes (${poolLabel()})`;
	if (isUnplayableStartError(err)) return QUEUE_STREAM_UNPLAYABLE_START_DETAIL;
	return `${poolLabel()} queue failed. Tap play to retry.`;
}

// --- Playback dispatch ---

function toPlaybackInfo(gen: GenerationItem, song: SongItem): PlaybackInfo {
	return { generation: gen, songId: song.id, songTitle: song.title, artist: song.artist };
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

function useStreamForQueue(): boolean {
	return shouldUseQueueStream(get(queuePlaybackMode));
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

async function playStreamEntries(
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
	queueContext.set({ type: 'library' });
	libraryQueueNotice.set('building');
	clearLibraryQueueSkipFeedback();
	clearWindowEnd();
	let manifest: QueueStreamManifest;
	try {
		manifest = await createLibraryQueueStreamSnapshot(gen.id, librarySnapshotOpts());
	} catch (err) {
		retryPlayIntent = () => playLibraryFromGeneration(gen, opts);
		libraryQueueNotice.set(isEmptyPoolError(err) ? 'empty' : 'error');
		clearLibraryQueueSkipFeedback();
		addToast(libraryStreamFailureToast(err), 'error');
		return;
	}
	retryPlayIntent = null;
	const startIndex = manifest.tracks.findIndex((t) => t.generation_id === gen.id);
	if (startIndex < 0) {
		retryPlayIntent = () => playLibraryFromGeneration(gen, opts);
		libraryQueueNotice.set('error');
		clearLibraryQueueSkipFeedback();
		addToast(QUEUE_TAKE_MISSING_TOAST, 'error');
		return;
	}
	libraryQueueNotice.set('idle');
	libraryQueueSkipped.set(manifest.skipped ?? []);
	libraryQueueSkippedComplete.set(manifest.skipped_complete ?? true);
	audioPlayer.loadStream(
		manifest,
		startIndex,
		streamLoadOpts(true, manifest.tracks[startIndex], opts.resumeAtTrackTime)
	);
	if (manifest.windowed) {
		showWindowedNotice(manifest.tracks.length);
	}
}

export async function playLibrary(opts: { resumeAtTrackTime?: number } = {}): Promise<void> {
	queueContext.set({ type: 'library' });
	libraryQueueNotice.set('building');
	clearLibraryQueueSkipFeedback();
	clearWindowEnd();
	let manifest: QueueStreamManifest;
	try {
		manifest = await createLibraryQueueStreamSnapshot(null, librarySnapshotOpts());
	} catch (err) {
		retryPlayIntent = () => playLibrary(opts);
		libraryQueueNotice.set(isEmptyPoolError(err) ? 'empty' : 'error');
		clearLibraryQueueSkipFeedback();
		addToast(libraryStreamFailureToast(err), 'error');
		return;
	}
	retryPlayIntent = null;
	libraryQueueNotice.set('idle');
	libraryQueueSkipped.set(manifest.skipped ?? []);
	libraryQueueSkippedComplete.set(manifest.skipped_complete ?? true);
	audioPlayer.loadStream(
		manifest,
		0,
		streamLoadOpts(true, manifest.tracks[0], opts.resumeAtTrackTime)
	);
	if (manifest.windowed) {
		showWindowedNotice(manifest.tracks.length);
	}
}

async function rebuildLibraryQueueKeepingPlace(): Promise<void> {
	if (audioPlayer.mode !== 'stream' || !audioPlayer.current) return;
	if (get(queueContext).type !== 'library') return;
	await playLibraryFromGeneration(audioPlayer.current.generation, {
		resumeAtTrackTime: audioPlayer.currentTime
	});
}

async function rebuildQueueAfterShuffleToggle(): Promise<void> {
	if (audioPlayer.mode !== 'stream' || !audioPlayer.current) return;
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
	const pool = ctx.type === 'album' ? songs.filter((s) => s.album_id === ctx.albumId) : songs;
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
	const pool = ctx.type === 'album' ? songs.filter((s) => s.album_id === ctx.albumId) : songs;
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
		mp3_path: gen.mp3_path,
		seed: gen.seed,
		model_mode: gen.model_mode
	};
}

async function collectAlbumQueue(
	albumId: string,
	start?: { song: SongItem; gen: GenerationItem }
): Promise<{ entries: PlaylistEntryItem[]; startIndex: number }> {
	await loadSongsForAlbum(albumId);
	const songs = get(songList).filter((s) => s.album_id === albumId);
	const entries: PlaylistEntryItem[] = [];
	for (const song of songs) {
		if (song.generation_count === 0) continue;
		await ensureGenerationsLoaded(song.id);
		const fresh = get(songList).find((s) => s.id === song.id);
		if (!fresh) continue;
		const gen =
			start && fresh.id === start.song.id
				? (fresh.generations.find((g) => g.id === start.gen.id) ?? start.gen)
				: bestGen(fresh);
		if (!gen) continue;
		entries.push({ ...toAlbumQueueEntry(fresh, gen), position: entries.length });
	}
	const startIndex = start
		? Math.max(
				0,
				entries.findIndex((entry) => entry.generation_id === start.gen.id)
			)
		: 0;
	return { entries, startIndex };
}

function currentPlaylistIndex(
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

function randomIndexExcluding(length: number, excludedIndex: number): number | null {
	if (length <= 1) return null;
	const candidates = Array.from({ length }, (_, index) => index).filter(
		(index) => index !== excludedIndex
	);
	return candidates[Math.floor(Math.random() * candidates.length)] ?? null;
}

export async function playNextSong(): Promise<void> {
	if (audioPlayer.mode === 'stream') {
		audioPlayer.nextStreamTrack();
		return;
	}
	const ctx = get(queueContext);
	if (ctx.type === 'playlist') {
		const currentIndex = currentPlaylistIndex(ctx);
		const nextIndex = get(shuffleEnabled)
			? randomIndexExcluding(ctx.entries.length, currentIndex)
			: ctx.entries.length > 1
				? (currentIndex + 1) % ctx.entries.length
				: null;
		if (nextIndex !== null) playPlaylistIndex(ctx, nextIndex);
		return;
	}
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
	clearWindowEnd();
	clearLibraryQueueSkipFeedback();
	queueContext.set({ type: 'album', albumId });
	const { entries, startIndex } = await collectAlbumQueue(albumId);
	if (entries.length === 0) return;
	const ordered = shuffledWithStart(entries, startIndex);
	if (useStreamForQueue()) {
		await playStreamEntries(ordered.items, ordered.startIndex, { restart: true });
		return;
	}
	const first = ordered.items[ordered.startIndex];
	const firstSong = get(songList).find((s) => s.id === first.id.split(':')[1]);
	const firstGen = firstSong?.generations.find((g) => g.id === first.generation_id);
	if (firstGen && firstSong) {
		playGeneration(firstGen, firstSong);
	}
}

export async function playAlbumFromGeneration(
	albumId: string,
	song: SongItem,
	gen: GenerationItem,
	opts: { resumeAtTrackTime?: number } = {}
): Promise<void> {
	clearWindowEnd();
	clearLibraryQueueSkipFeedback();
	queueContext.set({ type: 'album', albumId });
	const { entries, startIndex } = await collectAlbumQueue(albumId, { song, gen });
	if (entries.length === 0) return;
	const ordered = shuffledWithStart(entries, startIndex);
	if (useStreamForQueue()) {
		await playStreamEntries(ordered.items, ordered.startIndex, {
			restart: true,
			resumeAtTrackTime: opts.resumeAtTrackTime
		});
		return;
	}
	playGeneration(gen, song, { restart: true });
}

function playPlaylistIndex(
	ctx: { entries: PlaylistEntryItem[]; index: number },
	newIndex: number,
	opts: { restart?: boolean; startAt?: number } = {}
): void {
	if (newIndex < 0 || newIndex >= ctx.entries.length) return;
	const entry = ctx.entries[newIndex];
	queueContext.set({ type: 'playlist', entries: ctx.entries, index: newIndex });
	const info = {
		generation: playlistEntryToGeneration(entry),
		songId: entry.song_id,
		songTitle: entry.song_title,
		artist: entry.artist
	};
	if (opts.restart || opts.startAt !== undefined) {
		audioPlayer.load(info, { restart: opts.restart, startAt: opts.startAt });
	} else {
		audioPlayer.load(info);
	}
}

export async function playPlaylistEntries(
	entries: PlaylistEntryItem[],
	startIndex = 0,
	opts: { restart?: boolean; resumeAtTrackTime?: number } = {}
): Promise<void> {
	if (entries.length === 0) return;
	clearWindowEnd();
	clearLibraryQueueSkipFeedback();
	queueContext.set({ type: 'playlist', entries, index: startIndex });
	const ordered = shuffledWithStart(entries, startIndex);
	if (useStreamForQueue()) {
		await playStreamEntries(ordered.items, ordered.startIndex, {
			restart: opts.restart ?? true,
			resumeAtTrackTime: opts.resumeAtTrackTime
		});
		return;
	}
	playPlaylistIndex({ entries, index: startIndex }, startIndex, { restart: opts.restart });
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
		scores: null,
		generation_params: null,
		created_at: ''
	};
}

export function navigateToPlaying(): void {
	const cur = audioPlayer.current;
	if (!cur) return;
	const songs = get(songList);
	const song = songs.find((s) => s.id === cur.songId);
	if (song) {
		selectedAlbumId.set(song.album_id);
		selectedSongId.set(song.id);
	}
}

// --- Song/album list mutations ---
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

export type AlbumSongsLoadStatus = 'idle' | 'loading' | 'error';

export interface AlbumSongsLoadState {
	status: AlbumSongsLoadStatus;
	error: string | null;
}

export const albumSongsLoad = writable<Readonly<Record<string, AlbumSongsLoadState>>>({});

export async function loadSongsForAlbum(albumId: string): Promise<void> {
	const inflight = albumSongLoads.get(albumId);
	if (inflight) return inflight;
	albumSongsLoad.update((state) => ({
		...state,
		[albumId]: { status: 'loading', error: null }
	}));
	const load = (async () => {
		let offset = 0;
		const collected: SongItem[] = [];
		for (;;) {
			const page = await fetchSongs(albumId, offset, LIBRARY_SONG_PAGE_SIZE);
			collected.push(...page.items);
			offset += page.items.length;
			if (!page.has_more || page.items.length === 0) break;
		}
		songList.update((list) => mergeAlbumSongs(list, collected));
	})();
	albumSongLoads.set(albumId, load);
	try {
		await load;
		albumSongsLoad.update((state) => ({
			...state,
			[albumId]: { status: 'idle', error: null }
		}));
	} catch (err) {
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
		const current = next.find((item) => item.id === song.id);
		const merged =
			current && current.generations.length > 0 && song.generations.length === 0
				? { ...song, generations: current.generations }
				: song;
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
