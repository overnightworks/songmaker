import { writable } from 'svelte/store';
import type { GenerationItem, GenerationParams, VersionGenerationParams } from '$lib/api/types';

export type SourceMode = 'repaint' | 'cover';

export interface PendingSource {
	generation: GenerationItem;
	mode: SourceMode;
}

export const pendingSource = writable<PendingSource | null>(null);

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
