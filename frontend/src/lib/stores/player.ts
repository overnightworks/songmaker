import { writable, derived, get } from 'svelte/store';
import {
	createLibraryQueueStreamSnapshot,
	createQueueStreamSnapshot,
	fetchSong
} from '$lib/api/client';
import type {
	AlbumItem,
	GenerationItem,
	PlaylistEntryItem,
	QueueStreamManifest,
	SongItem
} from '$lib/api/types';
import {
	audioPlayer,
	type PlaybackInfo,
	type StreamFallbackState
} from '$lib/services/audioPlayer.svelte';
import { setupMediaSessionHandlers, updateMediaSessionMetadata } from '$lib/services/mediaSession';
import { addToast } from '$lib/stores/toast';
import { queuePlaybackMode, shouldUseQueueStream } from '$lib/stores/playbackSettings';

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
	if (!song || song.generations.length > 0 || song.generation_count === 0) return;
	if (_loadingIds.has(songId)) return;
	_loadingIds.add(songId);
	try {
		const full = await fetchSong(songId);
		replaceSongInList(full);
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
export const shuffleEnabled = writable(false);

export function toggleShuffle(): void {
	shuffleEnabled.update((enabled) => !enabled);
}

export function setShuffle(enabled: boolean): void {
	shuffleEnabled.set(enabled);
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
	opts: { restart?: boolean }
): Promise<void> {
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
	audioPlayer.loadStream(manifest, startIndex, { restart: opts.restart ?? true });
	if (manifest.windowed) {
		showWindowedNotice(manifest.tracks.length);
	}
}

export async function playLibraryFromGeneration(gen: GenerationItem): Promise<void> {
	queueContext.set({ type: 'library' });
	let manifest: QueueStreamManifest;
	try {
		manifest = await createLibraryQueueStreamSnapshot(gen.id);
	} catch {
		retryPlayIntent = () => playLibraryFromGeneration(gen);
		addToast('Stream unavailable. Tap play to retry.', 'error');
		return;
	}
	retryPlayIntent = null;
	const startIndex = manifest.tracks.findIndex((t) => t.generation_id === gen.id);
	audioPlayer.loadStream(manifest, startIndex >= 0 ? startIndex : 0, { restart: true });
	if (manifest.windowed) {
		showWindowedNotice(manifest.tracks.length);
	}
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
	queueContext.set({ type: 'album', albumId });
	const songs = get(songList).filter((s) => s.album_id === albumId);
	const playableEntries: PlaylistEntryItem[] = [];
	for (const song of songs) {
		if (song.generation_count === 0) continue;
		await ensureGenerationsLoaded(song.id);
		const fresh = get(songList).find((s) => s.id === song.id);
		const gen = fresh ? bestGen(fresh) : undefined;
		if (gen && fresh) {
			playableEntries.push({
				id: `album:${fresh.id}:${gen.id}`,
				position: playableEntries.length,
				generation_id: gen.id,
				song_title: fresh.title,
				album_title: fresh.album_title,
				artist: fresh.artist,
				generation_number: gen.generation_number,
				mp3_path: gen.mp3_path,
				seed: gen.seed,
				model_mode: gen.model_mode
			});
		}
	}
	if (playableEntries.length === 0) return;
	const ordered = shuffledWithStart(playableEntries, 0);
	if (useStreamForQueue()) {
		void playStreamEntries(ordered.items, ordered.startIndex, { restart: true });
		return;
	}
	const first = ordered.items[ordered.startIndex];
	const firstSong = get(songList).find((s) => s.id === first.id.split(':')[1]);
	const firstGen = firstSong?.generations.find((g) => g.id === first.generation_id);
	if (firstGen && firstSong) {
		playGeneration(firstGen, firstSong);
	}
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
		songId: '',
		songTitle: entry.song_title,
		artist: entry.artist
	};
	if (opts.restart || opts.startAt !== undefined) {
		audioPlayer.load(info, { restart: opts.restart, startAt: opts.startAt });
	} else {
		audioPlayer.load(info);
	}
}

export function playPlaylistEntries(
	entries: PlaylistEntryItem[],
	startIndex = 0,
	opts: { restart?: boolean } = {}
): void {
	if (entries.length === 0) return;
	const ordered = shuffledWithStart(entries, startIndex);
	const ctx = { entries: ordered.items, index: ordered.startIndex };
	queueContext.set({ type: 'playlist', entries: ordered.items, index: ordered.startIndex });
	if (useStreamForQueue()) {
		void playStreamEntries(ordered.items, ordered.startIndex, opts);
		return;
	}
	playPlaylistIndex(ctx, ordered.startIndex, opts);
}

async function rebuildQueueStream(state: StreamFallbackState): Promise<QueueStreamManifest | null> {
	const ctx = get(queueContext);
	try {
		if (ctx.type === 'library') {
			const currentTrack = state.manifest.tracks[state.trackIndex];
			return await createLibraryQueueStreamSnapshot(currentTrack?.generation_id ?? null);
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
		song_id: '',
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

export function handlePlaybackEnded(): void {
	void playNextSong();
}

audioPlayer.onEnded = handlePlaybackEnded;

audioPlayer.onAuthLost = async () => {
	const { clearAuth } = await import('$lib/stores/auth');
	const { goto } = await import('$app/navigation');
	clearAuth();
	await goto('/login');
};
