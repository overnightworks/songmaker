import { writable, derived, get } from 'svelte/store';
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
