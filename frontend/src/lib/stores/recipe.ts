import { writable, get } from 'svelte/store';
import type { GenerationItem, GenerationParams, VersionGenerationParams } from '$lib/api/types';
import { applyGenerationSettings, pinnedSeed } from '$lib/stores/editor';

export type SourceMode = 'repaint' | 'cover';
export type RepaintMode = 'conservative' | 'balanced' | 'aggressive';

export interface PendingSource {
	generation: GenerationItem;
	mode: SourceMode;
}

// Model and takes-per-generate are session state (epic #98 decision 1): they
// persist across songs for the session rather than living on the version, and
// are seeded once from the first available model.
export const recipeModel = writable<string | null>(null);
export const takesPerGenerate = writable<number>(1);

// The Editor's two independent, stackable views (epic #98 "Views vs. Action").
export const recipeOpen = writable(false);
export const coWriterOpen = writable(false);

// Repaint/cover source state — merged from the former stores/source.ts.
export const sourceGeneration = writable<GenerationItem | null>(null);
export const sourceMode = writable<SourceMode>('repaint');
export const repaintStart = writable(0);
export const repaintEnd = writable(1);
export const repaintMode = writable<RepaintMode>('conservative');
export const repaintStrength = writable(0.5);
export const coverStrength = writable(0.7);
export const coverNoiseStrength = writable(0);

export const pendingSource = writable<PendingSource | null>(null);

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
	recipeOpen.set(true);
}

export function clearSource(): void {
	sourceGeneration.set(null);
}

const RECIPE_PARAM_KEYS: (keyof VersionGenerationParams)[] = [
	'inference_steps',
	'guidance_scale',
	'shift',
	'thinking',
	'lm_temperature',
	'lm_top_k',
	'lm_top_p',
	'lm_cfg_scale',
	'lm_negative_prompt',
	'infer_method',
	'batch_size',
	'repaint_mode',
	'repaint_strength',
	'lm_repetition_penalty',
	'use_cot_caption',
	'use_cot_language',
	'use_adg',
	'cfg_interval_start',
	'cfg_interval_end',
	'sampler_mode',
	'velocity_norm_threshold',
	'velocity_ema_factor',
	'latent_shift',
	'latent_rescale',
	'audio_cover_strength',
	'user_lora_id'
];

export function recipeParamsFromTake(
	params: GenerationParams | null | undefined
): VersionGenerationParams {
	const filtered: VersionGenerationParams = {};
	if (!params) return filtered;
	for (const key of RECIPE_PARAM_KEYS) {
		if (params[key] != null) {
			(filtered as Record<string, unknown>)[key] = params[key];
		}
	}
	return filtered;
}

export function applyAgainFromGeneration(gen: GenerationItem): void {
	sourceGeneration.set(null);
	const params = recipeParamsFromTake(gen.generation_params);
	if (Object.keys(params).length > 0) applyGenerationSettings(params);
	if (gen.seed != null && gen.seed >= 0) pinnedSeed.set(gen.seed);
	recipeOpen.set(true);
}

// Called whenever the editor switches to a different song: the recipe
// (model, takes-per-generate) is session-wide and stays, but a repaint/cover
// source picked from the previous song's takes cannot carry over.
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
	coWriterOpen.set(false);
}

const LM_PARAM_KEYS: (keyof VersionGenerationParams)[] = [
	'lm_temperature',
	'lm_top_k',
	'lm_top_p',
	'lm_cfg_scale',
	'lm_repetition_penalty',
	'batch_size',
	'thinking',
	'use_cot_caption',
	'use_cot_language',
	'lm_negative_prompt'
];

const DIT_PARAM_KEYS: (keyof VersionGenerationParams)[] = [
	'inference_steps',
	'guidance_scale',
	'shift',
	'cfg_interval_start',
	'cfg_interval_end',
	'velocity_norm_threshold',
	'velocity_ema_factor',
	'latent_shift',
	'latent_rescale',
	'audio_cover_strength',
	'infer_method',
	'sampler_mode',
	'use_adg'
];

function hasAnyParam(
	genParams: VersionGenerationParams | null,
	keys: readonly (keyof VersionGenerationParams)[]
): boolean {
	if (!genParams) return false;
	return keys.some((key) => genParams[key] != null);
}

function capitalize(value: string): string {
	return value.length > 0 ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

export interface RecipeChip {
	key: string;
	label: string;
	value: string;
	title: string;
	changed: boolean;
}

export interface RecipeChipInput {
	model: string | null;
	takes: number;
	bpm: number;
	audioDuration: number;
	keyScale: string;
	voiceLabel: string;
	pinnedSeed: number | null;
	genParams: VersionGenerationParams | null;
	sourceGeneration: GenerationItem | null;
	sourceMode: SourceMode;
	repaintMode: RepaintMode;
	// The last-saved version's values, compared against the draft fields above
	// to mark a chip "changed". Omitted fields are treated as unchanged.
	savedBpm?: number;
	savedAudioDuration?: number;
	savedKeyScale?: string;
	savedGenParams?: VersionGenerationParams | null;
}

function paramsSubsetEqual(
	a: VersionGenerationParams | null,
	b: VersionGenerationParams | null,
	keys: readonly (keyof VersionGenerationParams)[]
): boolean {
	return keys.every((key) => (a?.[key] ?? null) === (b?.[key] ?? null));
}

// Pure projection from editor/recipe state to the labeled chip row — kept
// side-effect free so it can be unit tested without mounting a component.
export function recipeChips(input: RecipeChipInput): RecipeChip[] {
	const repaintValue =
		input.sourceGeneration === null
			? 'Off'
			: input.sourceMode === 'cover'
				? 'Cover'
				: capitalize(input.repaintMode);
	return [
		{
			key: 'model',
			label: 'Model',
			value: input.model ? input.model.toUpperCase() : '—',
			title: 'Model used for the next generation',
			changed: false
		},
		{
			key: 'takes',
			label: 'Takes',
			value: `×${input.takes}`,
			title: 'How many takes Generate produces at once',
			changed: false
		},
		{
			key: 'bpm',
			label: 'BPM',
			value: input.bpm > 0 ? String(input.bpm) : 'Auto',
			title: 'Target tempo (0 = let the model choose)',
			changed: input.bpm !== (input.savedBpm ?? input.bpm)
		},
		{
			key: 'duration',
			label: 'Duration',
			value: input.audioDuration > 0 ? `${input.audioDuration} s` : 'Auto',
			title: 'Target length (0 = let the model choose)',
			changed: input.audioDuration !== (input.savedAudioDuration ?? input.audioDuration)
		},
		{
			key: 'key',
			label: 'Key',
			value: input.keyScale || '—',
			title: 'Target musical key',
			changed: input.keyScale !== (input.savedKeyScale ?? input.keyScale)
		},
		{
			key: 'voice',
			label: 'Voice',
			value: input.voiceLabel,
			title: 'Cloned voice applied to vocals',
			changed:
				(input.genParams?.user_lora_id ?? null) !==
				(input.savedGenParams === undefined
					? (input.genParams?.user_lora_id ?? null)
					: (input.savedGenParams?.user_lora_id ?? null))
		},
		{
			key: 'seed',
			label: 'Seed',
			value: input.pinnedSeed != null ? `Pinned ${input.pinnedSeed}` : 'Random',
			title: 'A pinned seed reproduces the same noise for A/B testing',
			changed: false
		},
		{
			key: 'lm',
			label: 'LM',
			value: hasAnyParam(input.genParams, LM_PARAM_KEYS) ? 'Custom' : 'Default',
			title: 'Language-model generation parameters',
			changed: !paramsSubsetEqual(
				input.genParams,
				input.savedGenParams === undefined ? input.genParams : input.savedGenParams,
				LM_PARAM_KEYS
			)
		},
		{
			key: 'dit',
			label: 'DIT',
			value: hasAnyParam(input.genParams, DIT_PARAM_KEYS) ? 'Custom' : 'Default',
			title: 'Diffusion-transformer generation parameters',
			changed: !paramsSubsetEqual(
				input.genParams,
				input.savedGenParams === undefined ? input.genParams : input.savedGenParams,
				DIT_PARAM_KEYS
			)
		},
		{
			key: 'repaint',
			label: 'Repaint',
			value: repaintValue,
			title: 'Regenerate part of a take instead of starting fresh',
			changed: false
		}
	];
}
