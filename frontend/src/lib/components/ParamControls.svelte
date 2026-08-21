<script lang="ts">
	import { onMount } from 'svelte';
	import type { VersionGenerationParams } from '$lib/api/types';
	import { ACESTEP_PARAM_DESCRIPTIONS } from '$lib/constants/acestep-params';
	import { ensureCompactUiStyles } from '$lib/styles/compact-ui';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';

	interface Props {
		values: VersionGenerationParams;
		placeholders: Required<VersionGenerationParams>;
		onchange: (params: VersionGenerationParams) => void;
		hiddenParams?: string[];
		maxInferenceSteps?: number;
	}

	function tooltip(key: string): string {
		return ACESTEP_PARAM_DESCRIPTIONS[key]?.short ?? '';
	}

	let {
		values,
		placeholders,
		onchange,
		hiddenParams = [],
		maxInferenceSteps = 200
	}: Props = $props();

	let compact = $state(false);

	onMount(() => {
		ensureCompactUiStyles();
		return subscribeCompactLayout((value) => (compact = value));
	});

	interface NumberField {
		key: keyof VersionGenerationParams;
		label: string;
		min: number;
		max: number;
		step: number;
	}

	interface SelectField {
		key: keyof VersionGenerationParams;
		label: string;
		options: string[];
	}

	interface BoolField {
		key: keyof VersionGenerationParams;
		label: string;
		defaultValue: boolean;
	}

	const DIT_NUMBER_FIELDS: NumberField[] = [
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

	const DIT_SELECT_FIELDS: SelectField[] = [
		{ key: 'infer_method', label: 'Infer Method', options: ['ode', 'sde'] },
		{
			key: 'sampler_mode',
			label: 'Sampler',
			options: ['euler', 'heun']
		}
	];

	const DIT_BOOL_FIELDS: BoolField[] = [
		{ key: 'use_adg', label: 'Adaptive Dual Guidance', defaultValue: false }
	];

	const LM_NUMBER_FIELDS: NumberField[] = [
		{ key: 'lm_temperature', label: 'Temperature', min: 0, max: 2, step: 0.05 },
		{ key: 'lm_top_k', label: 'Top-K', min: 0, max: 200, step: 1 },
		{ key: 'lm_top_p', label: 'Top-P', min: 0, max: 1, step: 0.05 },
		{ key: 'lm_cfg_scale', label: 'CFG Scale', min: 0, max: 10, step: 0.5 },
		{ key: 'lm_repetition_penalty', label: 'Rep. Penalty', min: 0.5, max: 5, step: 0.1 },
		{ key: 'batch_size', label: 'Batch Size', min: 1, max: 8, step: 1 }
	];

	const LM_BOOL_FIELDS: BoolField[] = [
		{ key: 'thinking', label: 'Thinking', defaultValue: true },
		{ key: 'use_cot_caption', label: 'CoT Caption', defaultValue: true },
		{ key: 'use_cot_language', label: 'CoT Language', defaultValue: true }
	];

	const hiddenSet = $derived(new Set(hiddenParams));

	function filterNumbers(fields: NumberField[]): NumberField[] {
		return fields
			.filter((f) => !hiddenSet.has(f.key))
			.map((f) => (f.key === 'inference_steps' ? { ...f, max: maxInferenceSteps } : f));
	}

	const ditNumbers = $derived(filterNumbers(DIT_NUMBER_FIELDS));
	const ditSelects = $derived(DIT_SELECT_FIELDS.filter((f) => !hiddenSet.has(f.key)));
	const ditBools = $derived(DIT_BOOL_FIELDS.filter((f) => !hiddenSet.has(f.key)));
	const lmNumbers = $derived(filterNumbers(LM_NUMBER_FIELDS));
	const lmBools = $derived(LM_BOOL_FIELDS.filter((f) => !hiddenSet.has(f.key)));

	function setParam(key: keyof VersionGenerationParams, value: unknown): void {
		if (value === undefined || value === '') {
			const { [key]: _, ...rest } = values;
			onchange(Object.keys(rest).length > 0 ? rest : {});
		} else {
			onchange({ ...values, [key]: value });
		}
	}

	function handleNumber(key: keyof VersionGenerationParams, raw: string): void {
		if (raw === '') {
			setParam(key, undefined);
		} else {
			const num = Number(raw);
			if (!isNaN(num)) setParam(key, num);
		}
	}
</script>

{#snippet numberField(f: NumberField)}
	<label class="setting" title={tooltip(f.key)}>
		<span>{f.label}</span>
		<input
			type="number"
			min={f.min}
			max={f.max}
			step={f.step}
			value={values[f.key] ?? ''}
			placeholder={String(placeholders[f.key])}
			title={tooltip(f.key)}
			oninput={(e) => handleNumber(f.key, e.currentTarget.value)}
		/>
	</label>
{/snippet}

{#snippet selectField(f: SelectField)}
	<label class="setting" title={tooltip(f.key)}>
		<span>{f.label}</span>
		<select
			value={values[f.key] ?? ''}
			title={tooltip(f.key)}
			onchange={(e) => setParam(f.key, e.currentTarget.value || undefined)}
		>
			<option value="">default ({placeholders[f.key]})</option>
			{#each f.options as opt (opt)}
				<option value={opt}>{opt}</option>
			{/each}
		</select>
	</label>
{/snippet}

{#snippet boolField(f: BoolField)}
	<label class="setting toggle" title={tooltip(f.key)}>
		<span>{f.label}</span>
		<input
			type="checkbox"
			checked={(values[f.key] as boolean | null | undefined) ?? f.defaultValue}
			title={tooltip(f.key)}
			onchange={(e) => {
				const checked = e.currentTarget.checked;
				setParam(f.key, checked === f.defaultValue ? undefined : checked);
			}}
		/>
	</label>
{/snippet}

<div class="param-controls" class:compact>
	<details class="param-section" open>
		<summary class="section-label">DiT (Sound)</summary>
		<div class="settings-grid">
			{#each ditNumbers as f (f.key)}
				{@render numberField(f)}
			{/each}
			{#each ditSelects as f (f.key)}
				{@render selectField(f)}
			{/each}
			{#each ditBools as f (f.key)}
				{@render boolField(f)}
			{/each}
		</div>
	</details>

	<details class="param-section" open>
		<summary class="section-label">LM (Lyrics)</summary>
		<div class="settings-grid">
			{#each lmNumbers as f (f.key)}
				{@render numberField(f)}
			{/each}

			<label class="setting full-width" title={tooltip('lm_negative_prompt')}>
				<span>Negative Prompt</span>
				<input
					type="text"
					value={values.lm_negative_prompt ?? ''}
					placeholder="e.g. bad quality, noise"
					title={tooltip('lm_negative_prompt')}
					oninput={(e) => setParam('lm_negative_prompt', e.currentTarget.value || undefined)}
				/>
			</label>

			{#each lmBools as f (f.key)}
				{@render boolField(f)}
			{/each}
		</div>
	</details>
</div>

<style>
	.param-section {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.section-label {
		font-size: 0.65rem;
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 1px;
		cursor: pointer;
		list-style: disclosure-closed;
	}

	.param-section[open] > .section-label {
		list-style: disclosure-open;
	}

	.section-label:hover {
		color: var(--text);
	}

	.settings-grid {
		display: grid;
		grid-template-columns: 1fr 1fr 1fr;
		gap: 0.7rem;
	}

	.param-controls.compact .settings-grid {
		grid-template-columns: minmax(0, 1fr);
	}

	.setting {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		min-width: 0;
	}

	.setting span {
		font-size: var(--label-font-size);
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.setting.full-width {
		grid-column: 1 / -1;
	}

	.setting.toggle {
		flex-direction: row;
		align-items: center;
		gap: 0.5rem;
	}

	.setting.toggle input[type='checkbox'] {
		accent-color: var(--accent);
	}

	.setting input[type='text'],
	.setting input[type='number'],
	.setting select {
		padding: 0.4rem 0.6rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 1rem;
		width: 100%;
		min-width: 0;
		box-sizing: border-box;
	}

	.setting input:focus,
	.setting select:focus {
		border-color: var(--accent);
		outline: none;
		box-shadow: 0 0 8px rgba(160, 32, 240, 0.2);
	}
</style>
