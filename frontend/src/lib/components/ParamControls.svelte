<script lang="ts">
	import type { VersionGenerationParams } from '$lib/api/types';

	interface Props {
		values: VersionGenerationParams;
		placeholders: Required<VersionGenerationParams>;
		onchange: (params: VersionGenerationParams) => void;
		hiddenParams?: string[];
		maxInferenceSteps?: number;
	}

	let {
		values,
		placeholders,
		onchange,
		hiddenParams = [],
		maxInferenceSteps = 200
	}: Props = $props();

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

	const ALL_NUMBER_FIELDS: NumberField[] = [
		{ key: 'inference_steps', label: 'Inference Steps', min: 1, max: 200, step: 1 },
		{ key: 'guidance_scale', label: 'Guidance Scale', min: 0, max: 20, step: 0.5 },
		{ key: 'shift', label: 'Shift', min: 0, max: 20, step: 0.5 },
		{ key: 'lm_temperature', label: 'LM Temperature', min: 0, max: 2, step: 0.05 },
		{ key: 'lm_top_k', label: 'LM Top-K', min: 0, max: 200, step: 1 },
		{ key: 'lm_top_p', label: 'LM Top-P', min: 0, max: 1, step: 0.05 },
		{ key: 'lm_cfg_scale', label: 'LM CFG Scale', min: 0, max: 10, step: 0.5 },
		{ key: 'lm_repetition_penalty', label: 'LM Rep. Penalty', min: 0.5, max: 5, step: 0.1 },
		{ key: 'batch_size', label: 'Batch Size', min: 1, max: 8, step: 1 },
		{ key: 'cfg_interval_start', label: 'CFG Interval Start', min: 0, max: 1, step: 0.05 },
		{ key: 'cfg_interval_end', label: 'CFG Interval End', min: 0, max: 1, step: 0.05 }
	];

	const hiddenSet = $derived(new Set(hiddenParams));

	const NUMBER_FIELDS = $derived(
		ALL_NUMBER_FIELDS.filter((f) => !hiddenSet.has(f.key)).map((f) =>
			f.key === 'inference_steps' ? { ...f, max: maxInferenceSteps } : f
		)
	);

	interface BoolField {
		key: keyof VersionGenerationParams;
		label: string;
		defaultValue: boolean;
	}

	const SELECT_FIELDS: SelectField[] = [
		{ key: 'infer_method', label: 'Infer Method', options: ['ode', 'sde'] }
	];

	const ALL_BOOL_FIELDS: BoolField[] = [
		{ key: 'thinking', label: 'Thinking (LM)', defaultValue: true },
		{ key: 'use_cot_caption', label: 'CoT Caption', defaultValue: true },
		{ key: 'use_cot_language', label: 'CoT Language', defaultValue: true },
		{ key: 'use_adg', label: 'Adaptive Dual Guidance', defaultValue: false }
	];

	const BOOL_FIELDS = $derived(ALL_BOOL_FIELDS.filter((f) => !hiddenSet.has(f.key)));

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

<div class="settings-grid">
	{#each NUMBER_FIELDS.slice(0, 4) as f (f.key)}
		<label class="setting">
			<span>{f.label}</span>
			<input
				type="number"
				min={f.min}
				max={f.max}
				step={f.step}
				value={values[f.key] ?? ''}
				placeholder={String(placeholders[f.key])}
				oninput={(e) => handleNumber(f.key, e.currentTarget.value)}
			/>
		</label>
	{/each}

	{#each SELECT_FIELDS as f (f.key)}
		<label class="setting">
			<span>{f.label}</span>
			<select
				value={values[f.key] ?? ''}
				onchange={(e) => setParam(f.key, e.currentTarget.value || undefined)}
			>
				<option value="">default ({placeholders[f.key]})</option>
				{#each f.options as opt (opt)}
					<option value={opt}>{opt}</option>
				{/each}
			</select>
		</label>
	{/each}

	{#each NUMBER_FIELDS.slice(4) as f (f.key)}
		<label class="setting">
			<span>{f.label}</span>
			<input
				type="number"
				min={f.min}
				max={f.max}
				step={f.step}
				value={values[f.key] ?? ''}
				placeholder={String(placeholders[f.key])}
				oninput={(e) => handleNumber(f.key, e.currentTarget.value)}
			/>
		</label>
	{/each}

	<label class="setting full-width">
		<span>LM Negative Prompt</span>
		<input
			type="text"
			value={values.lm_negative_prompt ?? ''}
			placeholder="e.g. bad quality, noise"
			oninput={(e) => setParam('lm_negative_prompt', e.currentTarget.value || undefined)}
		/>
	</label>

	{#if BOOL_FIELDS.length > 0}
		{#each BOOL_FIELDS as f (f.key)}
			<label class="setting toggle">
				<span>{f.label}</span>
				<input
					type="checkbox"
					checked={(values[f.key] as boolean | null | undefined) ?? f.defaultValue}
					onchange={(e) => {
						const checked = e.currentTarget.checked;
						setParam(f.key, checked === f.defaultValue ? undefined : checked);
					}}
				/>
			</label>
		{/each}
	{/if}
</div>

<style>
	.settings-grid {
		display: grid;
		grid-template-columns: 1fr 1fr 1fr;
		gap: 0.7rem;
	}

	.setting {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
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
	}

	.setting input:focus,
	.setting select:focus {
		border-color: var(--accent);
		outline: none;
		box-shadow: 0 0 8px rgba(160, 32, 240, 0.2);
	}
</style>
