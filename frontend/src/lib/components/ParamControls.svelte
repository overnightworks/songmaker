<script lang="ts">
	import { onMount } from 'svelte';
	import type { VersionGenerationParams } from '$lib/api/types';
	import {
		DIT_BOOL_FIELDS,
		DIT_NUMBER_FIELDS,
		DIT_SELECT_FIELDS,
		LM_BOOL_FIELDS,
		LM_NUMBER_FIELDS,
		LM_TEXT_FIELDS,
		type BoolParamField,
		type NumberParamField,
		type SelectParamField
	} from '$lib/constants/acestep-param-fields';
	import { ACESTEP_PARAM_DESCRIPTIONS } from '$lib/constants/acestep-params';
	import { ensureCompactUiStyles } from '$lib/styles/compact-ui';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';
	import { addToast } from '$lib/stores/toast';

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

	const hiddenSet = $derived(new Set(hiddenParams));

	function filterNumbers(fields: NumberParamField[]): NumberParamField[] {
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

	const defaultsLoaded = $derived(Object.keys(placeholders).length > 0);

	const DEFAULT_MISSING_PREFIX = 'Default missing for';

	// Once defaultsLoaded is true, every rendered field is either hidden by
	// hiddenParams or must have a resolved default. A visible field with no
	// default at that point means the loaded defaults are incomplete for the
	// active model — a bug worth failing loudly on, not silently blanking.
	// Each field is wrapped in its own <svelte:boundary> below, so this only
	// takes down the one field, not the whole panel.
	function resolvedPlaceholder(key: keyof VersionGenerationParams): number | string | boolean {
		const value = placeholders[key];
		if (value === undefined || value === null) {
			throw new Error(`${DEFAULT_MISSING_PREFIX} ${key}`);
		}
		return value;
	}

	function fieldErrorMessage(error: unknown): string {
		return error instanceof Error ? error.message : DEFAULT_MISSING_PREFIX;
	}

	function reportFieldError(error: unknown): void {
		console.error(error);
		addToast(fieldErrorMessage(error), 'error');
	}
</script>

{#snippet fieldError(f: { key: keyof VersionGenerationParams; label: string }, error: unknown)}
	<div class="setting param-error" title={tooltip(f.key)}>
		<span>{f.label}</span>
		<p class="param-error-text">{fieldErrorMessage(error)}</p>
	</div>
{/snippet}

{#snippet numberField(f: NumberParamField)}
	<svelte:boundary onerror={reportFieldError}>
		<label class="setting" title={tooltip(f.key)}>
			<span>{f.label}</span>
			<input
				type="number"
				min={f.min}
				max={f.max}
				step={f.step}
				value={values[f.key] ?? ''}
				placeholder={defaultsLoaded ? String(resolvedPlaceholder(f.key)) : ''}
				title={tooltip(f.key)}
				oninput={(e) => handleNumber(f.key, e.currentTarget.value)}
			/>
		</label>
		{#snippet failed(error)}
			{@render fieldError(f, error)}
		{/snippet}
	</svelte:boundary>
{/snippet}

{#snippet selectField(f: SelectParamField)}
	<svelte:boundary onerror={reportFieldError}>
		<label class="setting" title={tooltip(f.key)}>
			<span>{f.label}</span>
			<select
				value={values[f.key] ?? ''}
				title={tooltip(f.key)}
				onchange={(e) => setParam(f.key, e.currentTarget.value || undefined)}
			>
				<option value=""
					>{defaultsLoaded ? `default (${resolvedPlaceholder(f.key)})` : 'default'}</option
				>
				{#each f.options as opt (opt)}
					<option value={opt}>{opt}</option>
				{/each}
			</select>
		</label>
		{#snippet failed(error)}
			{@render fieldError(f, error)}
		{/snippet}
	</svelte:boundary>
{/snippet}

{#snippet boolField(f: BoolParamField)}
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

			<label class="setting full-width" title={tooltip(LM_TEXT_FIELDS[0].key)}>
				<span>{LM_TEXT_FIELDS[0].label}</span>
				<input
					type="text"
					value={values.lm_negative_prompt ?? ''}
					placeholder="e.g. bad quality, noise"
					title={tooltip(LM_TEXT_FIELDS[0].key)}
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

	.param-error-text {
		margin: 0;
		color: #d34;
		font-size: 1rem;
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
