import { writable, derived, get } from 'svelte/store';
import { fetchSong } from '$lib/api/client';
import type { AlbumItem, GenerationItem, SongItem } from '$lib/api/types';

// --- Data ---
export const albumList = writable<AlbumItem[]>([]);
export const songList = writable<SongItem[]>([]);

// --- Browsing state ---
export const selectedAlbumId = writable<string | null>(null);
export const selectedSongId = writable<string | null>(null);
export const expandedSongIds = writable<Set<string>>(new Set());
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

export function toggleSongExpanded(songId: string): void {
	expandedSongIds.update((ids) => {
		const next = new Set(ids);
		if (next.has(songId)) next.delete(songId);
		else next.add(songId);
		return next;
	});
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
		songList.update((list) => list.map((s) => (s.id === songId ? full : s)));
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

// --- Playback state ---
interface PlaybackState {
	generation: GenerationItem;
	songId: string;
	songTitle: string;
	artist: string;
	autoplay: boolean;
}

export const playback = writable<PlaybackState | null>(null);
export const playingGeneration = derived(playback, ($pb) => $pb?.generation ?? null);

export function playGeneration(gen: GenerationItem, song: SongItem): void {
	playback.set({
		generation: gen,
		songId: song.id,
		songTitle: song.title,
		artist: song.artist,
		autoplay: true
	});
}

export const canPlayPrevGen = derived([playback, songList], ([$pb, $songs]) => {
	if (!$pb) return false;
	const song = $songs.find((s) => s.id === $pb.songId);
	if (!song) return false;
	const idx = song.generations.findIndex((g) => g.id === $pb.generation.id);
	return idx > 0;
});

export const canPlayNextGen = derived([playback, songList], ([$pb, $songs]) => {
	if (!$pb) return false;
	const song = $songs.find((s) => s.id === $pb.songId);
	if (!song) return false;
	const idx = song.generations.findIndex((g) => g.id === $pb.generation.id);
	return idx < song.generations.length - 1;
});

export const canPlayPrevSong = derived([playback, songList], ([$pb, $songs]) => {
	if (!$pb) return false;
	const idx = $songs.findIndex((s) => s.id === $pb.songId);
	for (let i = idx - 1; i >= 0; i--) {
		if ($songs[i].generation_count > 0) return true;
	}
	return false;
});

export const canPlayNextSong = derived([playback, songList], ([$pb, $songs]) => {
	if (!$pb) return false;
	const idx = $songs.findIndex((s) => s.id === $pb.songId);
	for (let i = idx + 1; i < $songs.length; i++) {
		if ($songs[i].generation_count > 0) return true;
	}
	return false;
});

export function playNextGeneration(): void {
	const pb = get(playback);
	if (!pb) return;
	const songs = get(songList);
	const song = songs.find((s) => s.id === pb.songId);
	if (!song) return;
	const gens = song.generations;
	const idx = gens.findIndex((g) => g.id === pb.generation.id);
	if (idx < gens.length - 1) {
		playGeneration(gens[idx + 1], song);
	}
}

export function playPrevGeneration(): void {
	const pb = get(playback);
	if (!pb) return;
	const songs = get(songList);
	const song = songs.find((s) => s.id === pb.songId);
	if (!song) return;
	const gens = song.generations;
	const idx = gens.findIndex((g) => g.id === pb.generation.id);
	if (idx > 0) {
		playGeneration(gens[idx - 1], song);
	}
}

function bestGen(song: SongItem): GenerationItem | undefined {
	return song.generations.find((g) => g.is_picked) ?? song.generations[0];
}

export async function playNextSong(): Promise<void> {
	const pb = get(playback);
	if (!pb) return;
	const songs = get(songList);
	const idx = songs.findIndex((s) => s.id === pb.songId);
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
	const pb = get(playback);
	if (!pb) return;
	const songs = get(songList);
	const idx = songs.findIndex((s) => s.id === pb.songId);
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

export function navigateToPlaying(): void {
	const pb = get(playback);
	if (!pb) return;
	const songs = get(songList);
	const song = songs.find((s) => s.id === pb.songId);
	if (song) {
		selectedAlbumId.set(song.album_id);
		selectedSongId.set(song.id);
	}
}

// --- Playback control ---
export const isAudioPlaying = writable(false);
export const requestTogglePlay = writable(0);

export function togglePlayPause(): void {
	requestTogglePlay.update((n) => n + 1);
}

// --- Playback time ---
export const playbackTime = writable(0);
export const playbackDuration = writable(0);

// --- Update scores in memory ---
export function updateGenerationScores(
	genId: string,
	update: Record<string, number | string>
): void {
	songList.update((songs) =>
		songs.map((song) => ({
			...song,
			generations: song.generations.map((gen) => {
				if (gen.id !== genId) return gen;
				return { ...gen, scores: { ...gen.scores, ...update } };
			})
		}))
	);
}
