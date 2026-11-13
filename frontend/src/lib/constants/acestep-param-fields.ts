import type { VersionGenerationParams } from '#lib/api/types.ts';
import type { TextKey } from '#lib/utils/page-words.ts';

// The one registry of which generation_params keys the app knows how to edit
// and the catalog key of what it calls each one. ParamControls renders its form fields straight
// from these arrays; any other surface that names a take's params (e.g. a
// read-only recipe summary) reads the same arrays instead of hand-maintaining
// a second list that can drift out of sync with what the editor actually
// exposes (#212).

export interface NumberParamField {
	key: keyof VersionGenerationParams;
	labelKey: TextKey;
	min: number;
	max: number;
	step: number;
}

export interface SelectParamField {
	key: keyof VersionGenerationParams;
	labelKey: TextKey;
	options: string[];
}

export interface BoolParamField {
	key: keyof VersionGenerationParams;
	labelKey: TextKey;
	defaultValue: boolean;
}

export interface TextParamField {
	key: keyof VersionGenerationParams;
	labelKey: TextKey;
	placeholderKey: TextKey;
}

export const DIT_NUMBER_FIELDS: NumberParamField[] = [
	{ key: 'inference_steps', labelKey: 'paramField.inferenceSteps', min: 1, max: 200, step: 1 },
	{ key: 'guidance_scale', labelKey: 'paramField.guidanceScale', min: 0, max: 20, step: 0.5 },
	{ key: 'shift', labelKey: 'paramField.shift', min: 0, max: 20, step: 0.5 },
	{
		key: 'cfg_interval_start',
		labelKey: 'paramField.cfgIntervalStart',
		min: 0,
		max: 1,
		step: 0.05
	},
	{ key: 'cfg_interval_end', labelKey: 'paramField.cfgIntervalEnd', min: 0, max: 1, step: 0.05 },
	{
		key: 'velocity_norm_threshold',
		labelKey: 'paramField.velocityNorm',
		min: 0,
		max: 100,
		step: 0.5
	},
	{ key: 'velocity_ema_factor', labelKey: 'paramField.velocityEma', min: 0, max: 1, step: 0.05 },
	{ key: 'latent_shift', labelKey: 'paramField.latentShift', min: -10, max: 10, step: 0.1 },
	{ key: 'latent_rescale', labelKey: 'paramField.latentRescale', min: 0.1, max: 5, step: 0.1 },
	{ key: 'audio_cover_strength', labelKey: 'paramField.lmCodeStrength', min: 0, max: 1, step: 0.05 }
];

export const DIT_SELECT_FIELDS: SelectParamField[] = [
	{ key: 'infer_method', labelKey: 'paramField.inferMethod', options: ['ode', 'sde'] },
	{
		key: 'sampler_mode',
		labelKey: 'paramField.sampler',
		options: ['euler', 'heun']
	}
];

export const DIT_BOOL_FIELDS: BoolParamField[] = [
	{ key: 'use_adg', labelKey: 'paramField.adaptiveDualGuidance', defaultValue: false }
];

export const LM_NUMBER_FIELDS: NumberParamField[] = [
	{ key: 'lm_temperature', labelKey: 'paramField.temperature', min: 0, max: 2, step: 0.05 },
	{ key: 'lm_top_k', labelKey: 'paramField.topK', min: 0, max: 200, step: 1 },
	{ key: 'lm_top_p', labelKey: 'paramField.topP', min: 0, max: 1, step: 0.05 },
	{ key: 'lm_cfg_scale', labelKey: 'paramField.cfgScale', min: 0, max: 10, step: 0.5 },
	{
		key: 'lm_repetition_penalty',
		labelKey: 'paramField.repetitionPenalty',
		min: 0.5,
		max: 5,
		step: 0.1
	},
	{ key: 'batch_size', labelKey: 'paramField.batchSize', min: 1, max: 8, step: 1 }
];

export const LM_BOOL_FIELDS: BoolParamField[] = [
	{ key: 'thinking', labelKey: 'paramField.thinking', defaultValue: true },
	{ key: 'use_cot_caption', labelKey: 'paramField.cotCaption', defaultValue: true },
	{ key: 'use_cot_language', labelKey: 'paramField.cotLanguage', defaultValue: true }
];

export const LM_TEXT_FIELDS: TextParamField[] = [
	{
		key: 'lm_negative_prompt',
		labelKey: 'paramField.negativePrompt',
		placeholderKey: 'paramField.negativePromptPlaceholder'
	}
];
