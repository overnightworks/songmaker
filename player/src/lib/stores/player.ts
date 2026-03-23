import { writable, derived } from 'svelte/store';
import type { Album } from '$lib/api/types';

export const albums = writable<Album[]>([]);
export const currentAlbumIndex = writable(0);
export const currentTrackIndex = writable(0);

export const currentAlbum = derived(
	[albums, currentAlbumIndex],
	([$albums, $idx]) => $albums[$idx] ?? null
);

export const currentTrack = derived(
	[currentAlbum, currentTrackIndex],
	([$album, $idx]) => $album?.tracks[$idx] ?? null
);

export function selectAlbum(index: number): void {
	currentAlbumIndex.set(index);
	currentTrackIndex.set(0);
}

export function selectTrack(index: number): void {
	currentTrackIndex.set(index);
}

export function nextTrack(): boolean {
	let advanced = false;
	currentAlbum.subscribe(($album) => {
		if (!$album) return;
		currentTrackIndex.update((i) => {
			if (i < $album.tracks.length - 1) {
				advanced = true;
				return i + 1;
			}
			return i;
		});
	})();
	return advanced;
}
