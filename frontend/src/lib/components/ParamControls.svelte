<script lang="ts">
	import type { VersionGenerationParams } from '$lib/api/types';

	interface Props {
		values: VersionGenerationParams;
		placeholders: Required<VersionGenerationParams>;
		onchange: (params: VersionGenerationParams) => void;
	}

	let { values, placeholders, onchange }: Props = $props();

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

	const NUMBER_FIELDS: NumberField[] = [
		{ key: 'inference_steps', label: 'Inference Steps', min: 1, max: 200, step: 1 },
		{ key: 'guidance_scale', label: 'Guidance Scale', min: 0, max: 20, step: 0.5 },
		{ key: 'shift', label: 'Shift', min: 0, max: 20, step: 0.5 },
		{ key: 'lm_temperature', label: 'LM Temperature', min: 0, max: 2, step: 0.05 },
		{ key: 'lm_top_k', label: 'LM Top-K', min: 0, max: 200, step: 1 },
		{ key: 'lm_top_p', label: 'LM Top-P', min: 0, max: 1, step: 0.05 },
		{ key: 'lm_cfg_scale', label: 'LM CFG Scale', min: 0, max: 10, step: 0.5 },
		{ key: 'batch_size', label: 'Batch Size', min: 1, max: 8, step: 1 }
	];

	const SELECT_FIELDS: SelectField[] = [
		{ key: 'infer_method', label: 'Infer Method', options: ['ode', 'sde'] },
		{ key: 'think_mode', label: 'Think Mode', options: ['deep', 'off'] }
	];

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
</div>

<style>
	.settings-grid {
		display: grid;
		grid-template-columns: 1fr 1fr 1fr;
		gap: 8px;
	}

	.setting {
		display: flex;
		flex-direction: column;
		gap: 3px;
	}

	.setting span {
		font-size: 10px;
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.setting.full-width {
		grid-column: 1 / -1;
	}

	.setting input[type='text'],
	.setting input[type='number'],
	.setting select {
		padding: 5px 8px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 12px;
		width: 100%;
	}

	.setting input:focus,
	.setting select:focus {
		border-color: var(--primary);
		outline: none;
	}
</style>
