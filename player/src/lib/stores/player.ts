import { writable, derived, get } from 'svelte/store';
import type { Album, Track } from '$lib/api/types';

// --- Browsing state (what the user is looking at) ---
export const albums = writable<Album[]>([]);
export const browsingAlbumIndex = writable(0);
export const browsingTrackIndex = writable(0);

export const browsingAlbum = derived(
	[albums, browsingAlbumIndex],
	([$albums, $idx]) => $albums[$idx] ?? null
);

export const browsingTrack = derived(
	[browsingAlbum, browsingTrackIndex],
	([$album, $idx]) => $album?.tracks[$idx] ?? null
);

// --- Playback state (what's actually playing) ---
interface PlaybackState {
	track: Track;
	albumIndex: number;
	trackIndex: number;
}

export const playback = writable<PlaybackState | null>(null);

export const playingTrack = derived(playback, ($pb) => $pb?.track ?? null);

export function selectAlbum(index: number): void {
	browsingAlbumIndex.set(index);
	browsingTrackIndex.set(0);
}

export function selectTrack(index: number): void {
	browsingTrackIndex.set(index);
}

export function playTrack(albumIndex: number, trackIndex: number): void {
	const allAlbums = get(albums);
	const album = allAlbums[albumIndex];
	if (!album) return;
	const track = album.tracks[trackIndex];
	if (!track) return;
	browsingAlbumIndex.set(albumIndex);
	browsingTrackIndex.set(trackIndex);
	playback.set({ track, albumIndex, trackIndex });
}

export function playBrowsingTrack(): void {
	playTrack(get(browsingAlbumIndex), get(browsingTrackIndex));
}

export function nextTrack(): boolean {
	const pb = get(playback);
	if (!pb) return false;
	const allAlbums = get(albums);
	const album = allAlbums[pb.albumIndex];
	if (!album) return false;
	if (pb.trackIndex < album.tracks.length - 1) {
		playTrack(pb.albumIndex, pb.trackIndex + 1);
		return true;
	}
	return false;
}
