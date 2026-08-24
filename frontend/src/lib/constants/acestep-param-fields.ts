import type { VersionGenerationParams } from '$lib/api/types';

// The one registry of which generation_params keys the app knows how to edit
// and what it calls each one. ParamControls renders its form fields straight
// from these arrays; any other surface that names a take's params (e.g. a
// read-only recipe summary) reads the same arrays instead of hand-maintaining
// a second list that can drift out of sync with what the editor actually
// exposes (#212).

export interface NumberParamField {
	key: keyof VersionGenerationParams;
	label: string;
	min: number;
	max: number;
	step: number;
}

export interface SelectParamField {
	key: keyof VersionGenerationParams;
	label: string;
	options: string[];
}

export interface BoolParamField {
	key: keyof VersionGenerationParams;
	label: string;
	defaultValue: boolean;
}

export interface TextParamField {
	key: keyof VersionGenerationParams;
	label: string;
}

export const DIT_NUMBER_FIELDS: NumberParamField[] = [
	{ key: 'inference_steps', label: 'Inference Steps', min: 1, max: 200, step: 1 },
	{ key: 'guidance_scale', label: 'Guidance Scale', min: 0, max: 20, step: 0.5 },
	{ key: 'shift', label: 'Shift', min: 0, max: 20, step: 0.5 },
	{ key: 'cfg_interval_start', label: 'CFG Interval Start', min: 0, max: 1, step: 0.05 },
	{ key: 'cfg_interval_end', label: 'CFG Interval End', min: 0, max: 1, step: 0.05 },
	{ key: 'velocity_norm_threshold', label: 'Velocity Norm', min: 0, max: 100, step: 0.5 },
	{ key: 'velocity_ema_factor', label: 'Velocity EMA', min: 0, max: 1, step: 0.05 },
	{ key: 'latent_shift', label: 'Latent Shift', min: -10, max: 10, step: 0.1 },
	{ key: 'latent_rescale', label: 'Latent Rescale', min: 0.1, max: 5, step: 0.1 },
	{ key: 'audio_cover_strength', label: 'LM Code Strength', min: 0, max: 1, step: 0.05 }
];

export const DIT_SELECT_FIELDS: SelectParamField[] = [
	{ key: 'infer_method', label: 'Infer Method', options: ['ode', 'sde'] },
	{
		key: 'sampler_mode',
		label: 'Sampler',
		options: ['euler', 'heun']
	}
];

export const DIT_BOOL_FIELDS: BoolParamField[] = [
	{ key: 'use_adg', label: 'Adaptive Dual Guidance', defaultValue: false }
];

export const LM_NUMBER_FIELDS: NumberParamField[] = [
	{ key: 'lm_temperature', label: 'Temperature', min: 0, max: 2, step: 0.05 },
	{ key: 'lm_top_k', label: 'Top-K', min: 0, max: 200, step: 1 },
	{ key: 'lm_top_p', label: 'Top-P', min: 0, max: 1, step: 0.05 },
	{ key: 'lm_cfg_scale', label: 'CFG Scale', min: 0, max: 10, step: 0.5 },
	{ key: 'lm_repetition_penalty', label: 'Rep. Penalty', min: 0.5, max: 5, step: 0.1 },
	{ key: 'batch_size', label: 'Batch Size', min: 1, max: 8, step: 1 }
];

export const LM_BOOL_FIELDS: BoolParamField[] = [
	{ key: 'thinking', label: 'Thinking', defaultValue: true },
	{ key: 'use_cot_caption', label: 'CoT Caption', defaultValue: true },
	{ key: 'use_cot_language', label: 'CoT Language', defaultValue: true }
];

export const LM_TEXT_FIELDS: TextParamField[] = [
	{ key: 'lm_negative_prompt', label: 'Negative Prompt' }
];
