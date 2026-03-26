import type { VersionGenerationParams } from '$lib/api/types';

const SHARED_DEFAULTS: Omit<Required<VersionGenerationParams>, 'inference_steps'> = {
	guidance_scale: 0.0,
	shift: 3.0,
	think_mode: 'deep',
	lm_temperature: 0.85,
	lm_top_k: 0,
	lm_top_p: 0.9,
	lm_cfg_scale: 2.0,
	lm_negative_prompt: '',
	infer_method: 'ode',
	batch_size: 1
};

export const FALLBACK_DEFAULTS: Record<string, Required<VersionGenerationParams>> = {
	turbo: { inference_steps: 8, ...SHARED_DEFAULTS } as Required<VersionGenerationParams>,
	sft: { inference_steps: 50, ...SHARED_DEFAULTS } as Required<VersionGenerationParams>
};
