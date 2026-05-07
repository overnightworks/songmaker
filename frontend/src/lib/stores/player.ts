import { writable, derived, get } from 'svelte/store';
import { fetchSong } from '$lib/api/client';
import type { AlbumItem, GenerationItem, PlaylistEntryItem, SongItem } from '$lib/api/types';
import { audioPlayer, type PlaybackInfo } from '$lib/services/audioPlayer.svelte';

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

// --- Playback dispatch ---

function toPlaybackInfo(gen: GenerationItem, song: SongItem): PlaybackInfo {
	return { generation: gen, songId: song.id, songTitle: song.title, artist: song.artist };
}

export function playGeneration(gen: GenerationItem, song: SongItem): void {
	audioPlayer.load(toPlaybackInfo(gen, song));
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
	if (ctx.type === 'playlist') return ctx.index > 0;
	const pool = ctx.type === 'album' ? songs.filter((s) => s.album_id === ctx.albumId) : songs;
	const idx = pool.findIndex((s) => s.id === current.songId);
	for (let i = idx - 1; i >= 0; i--) {
		if (pool[i].generation_count > 0) return true;
	}
	return false;
}

export function canPlayNextSong(
	current: PlaybackInfo | null,
	songs: SongItem[],
	ctx: QueueContext
): boolean {
	if (!current) return false;
	if (ctx.type === 'playlist') return ctx.index < ctx.entries.length - 1;
	const pool = ctx.type === 'album' ? songs.filter((s) => s.album_id === ctx.albumId) : songs;
	const idx = pool.findIndex((s) => s.id === current.songId);
	for (let i = idx + 1; i < pool.length; i++) {
		if (pool[i].generation_count > 0) return true;
	}
	return false;
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

export async function playNextSong(): Promise<void> {
	const ctx = get(queueContext);
	if (ctx.type === 'playlist') {
		playPlaylistIndex(ctx, ctx.index + 1);
		return;
	}
	const cur = audioPlayer.current;
	if (!cur) return;
	const songs = queueSongs();
	const idx = songs.findIndex((s) => s.id === cur.songId);
	for (let i = idx + 1; i < songs.length; i++) {
		if (songs[i].generation_count === 0) continue;
		await ensureGenerationsLoaded(songs[i].id);
		const fresh = get(songList).find((s) => s.id === songs[i].id);
		const gen = fresh ? bestGen(fresh) : undefined;
		if (gen && fresh) {
			playGeneration(gen, fresh);
			return;
		}
	}
}

export async function playPrevSong(): Promise<void> {
	const ctx = get(queueContext);
	if (ctx.type === 'playlist') {
		playPlaylistIndex(ctx, ctx.index - 1);
		return;
	}
	const cur = audioPlayer.current;
	if (!cur) return;
	const songs = queueSongs();
	const idx = songs.findIndex((s) => s.id === cur.songId);
	for (let i = idx - 1; i >= 0; i--) {
		if (songs[i].generation_count === 0) continue;
		await ensureGenerationsLoaded(songs[i].id);
		const fresh = get(songList).find((s) => s.id === songs[i].id);
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
	for (const song of songs) {
		if (song.generation_count === 0) continue;
		await ensureGenerationsLoaded(song.id);
		const fresh = get(songList).find((s) => s.id === song.id);
		const gen = fresh ? bestGen(fresh) : undefined;
		if (gen && fresh) {
			playGeneration(gen, fresh);
			return;
		}
	}
}

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

function playPlaylistIndex(
	ctx: { entries: PlaylistEntryItem[]; index: number },
	newIndex: number
): void {
	if (newIndex < 0 || newIndex >= ctx.entries.length) return;
	const entry = ctx.entries[newIndex];
	queueContext.set({ type: 'playlist', entries: ctx.entries, index: newIndex });
	audioPlayer.load({
		generation: playlistEntryToGeneration(entry),
		songId: '',
		songTitle: entry.song_title,
		artist: entry.artist
	});
}

export function playPlaylistEntries(entries: PlaylistEntryItem[]): void {
	if (entries.length === 0) return;
	queueContext.set({ type: 'playlist', entries, index: 0 });
	const first = entries[0];
	audioPlayer.load({
		generation: playlistEntryToGeneration(first),
		songId: '',
		songTitle: first.song_title,
		artist: first.artist
	});
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

audioPlayer.onEnded = () => {
	const ctx = get(queueContext);
	if (ctx.type === 'playlist') void playNextSong();
	else void playNextGeneration();
};

audioPlayer.onAuthLost = async () => {
	const { clearAuth } = await import('$lib/stores/auth');
	const { goto } = await import('$app/navigation');
	clearAuth();
	await goto('/login');
};
