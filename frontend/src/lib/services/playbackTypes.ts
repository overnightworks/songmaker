import type { GenerationItem } from '$lib/api/types';

export interface PlaybackInfo {
	generation: GenerationItem;
	songId: string;
	songTitle: string;
	artist: string;
	albumTitle: string;
	lyrics: string | null;
}
