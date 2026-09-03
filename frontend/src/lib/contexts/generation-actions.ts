import { setContext, getContext } from 'svelte';
import type { ShareResult, SongItem } from '$lib/api/types';
import { pinSeed, rate, setKeep, setPick } from '$lib/stores/takeActions';

export interface GenerationActions {
	pick: (genId: string, picked: boolean) => void;
	keep: (genId: string, kept: boolean) => void;
	del: (genId: string) => void;
	rate: (genId: string, rating: number, notes: string) => Promise<void>;
	share: (genId: string) => Promise<ShareResult>;
	unshare: (genId: string) => Promise<void>;
	addToPlaylist: (playlistId: string, genId: string) => Promise<void>;
	pinSeed: (seed: number) => void;
	clickVersion: (versionId: string) => void;
}

export const GENERATION_ACTIONS_KEY = Symbol('generation-actions');

export function setGenerationActions(actions: GenerationActions): void {
	setContext(GENERATION_ACTIONS_KEY, actions);
}

export function getGenerationActions(): GenerationActions {
	return getContext<GenerationActions>(GENERATION_ACTIONS_KEY);
}

// stores/takeActions.ts is the one mutation owner for pick/keep/rate/pinSeed;
// this bakes the actions' target song into that store's per-song API, so a
// GenerationActions provider only has to supply its own bespoke handlers
// (delete, share, ...). Takes a getter rather than a SongItem so the
// provider's current song stays live across the provider's lifetime instead
// of freezing at the moment setGenerationActions runs.
export function takeActionsFor(
	getSong: () => SongItem | null
): Pick<GenerationActions, 'pick' | 'keep' | 'rate' | 'pinSeed'> {
	return {
		pick: (genId, picked) => {
			const song = getSong();
			if (song) void setPick(song.id, genId, picked);
		},
		keep: (genId, kept) => {
			const song = getSong();
			if (song) void setKeep(song.id, genId, kept);
		},
		rate: (genId, rating, notes) => {
			const song = getSong();
			return song ? rate(song.id, genId, rating, notes) : Promise.resolve();
		},
		pinSeed
	};
}
