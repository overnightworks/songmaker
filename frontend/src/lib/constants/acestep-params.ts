/**
 * User-facing descriptions for ACE-Step generation parameters.
 *
 * Source-verified against the upstream ACE-Step Tutorial.md, the academic
 * papers behind each technique, and the vendored Python source. See
 * plans/acestep-model-parameters.md for the per-model capability matrix.
 *
 * Two layers per parameter:
 *   - short: ~80 char tooltip for hover / mobile long-press
 *   - long:  2–4 sentence explanation for an expanded help drawer (future)
 *
 * Form labels live next to the field definitions in ParamControls.svelte
 * and are not duplicated here.
 */

export interface ParamDescription {
	short: string;
	long: string;
}

export const ACESTEP_PARAM_DESCRIPTIONS: Record<string, ParamDescription> = {
	inference_steps: {
		short: 'Diffusion denoising steps. More = slower but more refined.',
		long: 'The diffusion model refines random noise into audio over this many steps. Turbo is distilled to ~8 steps; SFT and Base need ~50 for full quality. Below the recommended count produces underbaked output; above wastes compute.'
	},
	guidance_scale: {
		short: 'How strongly to follow your style prompt. Ignored on turbo models.',
		long: 'Classifier-Free Guidance — runs the diffusion model twice per step (with and without your prompt) and amplifies the difference. Higher = closer to prompt but can over-saturate. Turbo bakes guidance into training and forces this to 1.0.'
	},
	shift: {
		short: 'Biases denoising toward early structure or late detail. 3.0 is balanced.',
		long: 'Rebalances how denoising steps are distributed. Larger shift (3–5) spends more on early high-noise stages where large-scale structure forms — stronger semantics, clearer framework. Smaller shift (1–2) emphasizes detail but details may include noise.'
	},
	infer_method: {
		short: 'ODE = deterministic, reproducible. SDE = adds randomness, sometimes more natural.',
		long: 'ODE follows a deterministic trajectory — same seed produces the same output. SDE injects noise at each step, breaking exact reproducibility but sometimes yielding more natural texture on sustained sounds. ODE is the default.'
	},
	use_adg: {
		short: 'Smarter CFG that prevents over-saturation. Only matters when guidance_scale > 1.',
		long: "At high CFG values plain guidance over-saturates the output. Adaptive Projected Guidance (called ADG in ACE-Step's UI but actually APG from Sadat et al. 2024) decomposes the CFG update and down-weights the part that causes saturation. Useful when you want guidance_scale=7+ without harshness."
	},
	cfg_interval_start: {
		short: 'Apply CFG starting from this point in the denoising trajectory (0.0–1.0).',
		long: 'CFG is mostly harmful at the very start of denoising and only helps in the middle. Setting start=0.1 skips guidance during the first 10% of steps. Default 0.0 applies CFG from the start. No effect when guidance_scale ≤ 1.0.'
	},
	cfg_interval_end: {
		short: 'Stop applying CFG at this point in the denoising trajectory (0.0–1.0).',
		long: 'CFG is unnecessary toward the end of denoising and can be turned off early to save compute and improve quality. Setting end=0.8 stops guidance after 80% of steps. Default 1.0 applies CFG until the end. No effect when guidance_scale ≤ 1.0.'
	},
	thinking: {
		short: 'Let the LM plan musical structure before audio generation.',
		long: 'When enabled, the 5Hz Language Model uses chain-of-thought to infer BPM, key, time signature, and structure from your caption and lyrics, then passes that plan to the diffusion model. Auto-disabled in Cover, Extract, and Repaint-with-codes modes.'
	},
	lm_temperature: {
		short: 'How creative the LM is when planning. Higher = more varied, lower = more predictable.',
		long: 'Standard sampling temperature. 0.0 is fully deterministic, 2.0 is chaotic. The default 0.85 balances creativity and coherence. 1.0–1.5 produces surprising structures (and sometimes nonsense); 0.3–0.6 gives conservative on-prompt planning.'
	},
	lm_top_k: {
		short: 'Limit LM sampling to the K most-likely tokens. 0 = disabled.',
		long: "Caps the LM's sampling pool to the top K candidates by probability. K=50 avoids implausible tokens but can cut off creative ones. Default 0 lets top_p and temperature do the filtering instead."
	},
	lm_top_p: {
		short: 'Nucleus sampling — sample only from tokens covering P of the probability mass.',
		long: 'At each step, the LM ranks possible next tokens by probability and considers only the smallest set whose cumulative probability adds up to P. Default 0.9 is the standard recommendation. Adapts to context: small nucleus when confident, large when uncertain.'
	},
	lm_cfg_scale: {
		short: "CFG strength for the LM's plan (separate from the DiT guidance_scale).",
		long: 'Higher values make the LM stick more closely to your caption and lyrics when generating its musical plan. Default 2.0 is balanced; 2.5–3.0 produces stricter adherence at the cost of creativity.'
	},
	lm_negative_prompt: {
		short: 'Tell the LM what NOT to include in its musical plan.',
		long: "Negative prompt for the LM's CoT step — the LM tries to avoid concepts mentioned here. Useful for steering away from defaults you don't want (e.g. 'drums, electronic' if you want a slow acoustic piece). Has no effect when thinking is off."
	},
	lm_repetition_penalty: {
		short: 'Discourages the LM from repeating itself. 1.0 = off.',
		long: 'Penalizes already-generated tokens, reducing degenerate loops where the same lyric or musical idea repeats. Default 1.0 is fine for normal use; 1.05–1.15 helps if you see stuck outputs. Above 1.3 starts damaging coherence.'
	},
	use_cot_caption: {
		short: 'Let the LM rewrite your style caption to be more model-friendly.',
		long: 'Takes your style caption and expands it into a richer prompt the diffusion model can use more effectively. Often improves output on short or vague captions. Disable for verbatim caption use (e.g. reproducibility tests).'
	},
	use_cot_language: {
		short: 'Let the LM auto-detect the language of your lyrics.',
		long: 'Analyzes lyrics to infer vocal language so the diffusion model pronounces correctly. Disable to force a specific vocal_language manually or to control which one wins on intentionally mixed-language lyrics.'
	},
	batch_size: {
		short: 'Number of audio variations to generate from one request (1–8).',
		long: 'Each candidate uses a different seed, giving you N variations of the same prompt. Larger batches use linearly more VRAM but are more efficient than running N separate generations. Hard maximum is 8.'
	}
};
