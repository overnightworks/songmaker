import { setContext, getContext } from 'svelte';
import type { GenerationItem, ShareResult } from '$lib/api/types';

export interface GenerationActions {
	score: (genId: string) => void;
	pick: (genId: string, picked: boolean) => void;
	keep: (genId: string, kept: boolean) => void;
	del: (genId: string) => void;
	rate: (genId: string, rating: number, notes: string) => Promise<void>;
	share: (genId: string) => Promise<ShareResult>;
	unshare: (genId: string) => Promise<void>;
	addToPlaylist: (playlistId: string, genId: string) => Promise<void>;
	pinSeed: (seed: number) => void;
	clickVersion: (versionId: string) => void;
	useAsSource: (gen: GenerationItem) => void;
}

const KEY = Symbol('generation-actions');

export function setGenerationActions(actions: GenerationActions): void {
	setContext(KEY, actions);
}

export function getGenerationActions(): GenerationActions {
	return getContext<GenerationActions>(KEY);
}
