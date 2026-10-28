import { writable, get } from 'svelte/store';
import type { GenerationItem } from '$lib/api/types';
import { RECIPE_SOURCE_DURATION_DEFAULT_SECONDS } from '$lib/constants';
import { RECIPE_TAKES_STANDARD } from '$lib/constants/recipe';
import { takeUseSeedToast } from '$lib/constants/take-task';
import { addToast } from '$lib/stores/toast';

export type SourceMode = 'repaint' | 'cover';
export type RepaintMode = 'conservative' | 'balanced' | 'aggressive';

/** What a take is used for: the card's two tasks, or the seed for the next jobs. */
export type TakeUse = SourceMode | 'seed';

interface PendingTakeUse {
	generation: GenerationItem;
	use: TakeUse;
}

interface SeedFromTake {
	seed: number;
	takeNumber: number;
}

// Model and takes-per-generate are session state (epic #98 decision 1): they
// persist across songs for the session rather than living on the version, and
// are seeded once from the first available model.
export const recipeModel = writable<string | null>(null);
export const takesPerGenerate = writable<number>(RECIPE_TAKES_STANDARD);

// Whether the recipe card is open; it closes when the editor switches songs.
export const recipeOpen = writable(false);

// Repaint/cover source state — merged from the former stores/source.ts.
export const sourceGeneration = writable<GenerationItem | null>(null);
export const sourceMode = writable<SourceMode>('repaint');
export const repaintStart = writable(0);
export const repaintEnd = writable(1);
export const repaintMode = writable<RepaintMode>('conservative');
export const repaintStrength = writable(0.5);
export const coverStrength = writable(0.7);
export const coverNoiseStrength = writable(0);

// Now Playing hands a take over before its song is open; the song page applies it.
export const pendingTakeUse = writable<PendingTakeUse | null>(null);

// The seed Generate, Repaint and Cover send, until the musician clears it or
// leaves the song. It is session state: a reload shows none.
export const seedFromTake = writable<SeedFromTake | null>(null);

export function useSeed(gen: GenerationItem): void {
	if (gen.seed == null) return;
	seedFromTake.set({ seed: gen.seed, takeNumber: gen.generation_number });
	addToast(takeUseSeedToast(gen.generation_number), 'success');
}

export function clearSeed(): void {
	seedFromTake.set(null);
}

// Returns whether the use opened a task card.
export function applyTakeUse({ generation, use }: PendingTakeUse): boolean {
	if (use === 'seed') {
		useSeed(generation);
		return false;
	}
	setSourceFromGeneration(generation, use);
	return true;
}

export function seedRecipeModel(activeModelIds: readonly string[]): void {
	if (get(recipeModel) !== null) return;
	const first = activeModelIds[0];
	if (first) recipeModel.set(first);
}

export function setSourceFromGeneration(gen: GenerationItem, mode: SourceMode): void {
	sourceGeneration.set(gen);
	sourceMode.set(mode);
	if (mode === 'repaint') {
		repaintStart.set(0);
		repaintEnd.set(1);
	}
}

/** The take's real length; the requested Duration is 0 for auto and wrong whenever the render differs. */
export function sourceTakeDurationSeconds(gen: GenerationItem): number {
	return gen.audio_duration_sec ?? RECIPE_SOURCE_DURATION_DEFAULT_SECONDS;
}

export function clearSource(): void {
	sourceGeneration.set(null);
}

// Called whenever the editor switches to a different song: the recipe
// (model, takes-per-generate) is session-wide and stays, but a repaint/cover
// source or a seed picked from the previous song's takes cannot carry over.
export function resetRecipeSourceForSong(): void {
	sourceGeneration.set(null);
	sourceMode.set('repaint');
	repaintStart.set(0);
	repaintEnd.set(1);
	repaintMode.set('conservative');
	repaintStrength.set(0.5);
	coverStrength.set(0.7);
	coverNoiseStrength.set(0);
	recipeOpen.set(false);
	clearSeed();
}
