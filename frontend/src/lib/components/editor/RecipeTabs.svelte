<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { tick, type Snippet } from 'svelte';
	import { uploadReferenceAudio } from '$lib/api/client';
	import { describeFailure } from '$lib/api/fetch';
	import {
		activeModels,
		activeModelsError,
		activeModelsLoading,
		effectiveGenerationDefaults,
		generationDefaultsError,
		loadActiveModels,
		loadGenerationDefaults,
		presets,
		savePreset
	} from '$lib/stores/presets';
	import { followAppPageLink } from '$lib/stores/navigation';
	import {
		changedRecipeFields,
		changedRecipeTabs,
		chooseEnginePreset,
		engineParams,
		isEngineParamKey,
		matchingEnginePreset,
		resetRecipeField,
		resetRecipeTab,
		type RecipeField,
		type RecipeStandard,
		type RecipeTab,
		type RecipeValues
	} from '$lib/utils/recipe-standard';
	import { RECIPE_PANEL_LABEL, VOICE_PICKER_NONE_LABEL } from '$lib/constants';
	import {
		RECIPE_AUTO_LABEL,
		RECIPE_BPM_LABEL,
		RECIPE_BPM_MAX,
		RECIPE_CLOSE_LABEL,
		RECIPE_DEFAULTS_ERROR,
		RECIPE_DURATION_LABEL,
		RECIPE_DURATION_MAX_SECONDS,
		RECIPE_EMPTY_LABEL,
		RECIPE_ENGINE_EMPTY_HINT,
		RECIPE_FIELD_RESET_TITLES,
		RECIPE_KEY_LABEL,
		RECIPE_MANAGE_PRESETS_LABEL,
		RECIPE_MAX_INFERENCE_STEPS_DEFAULT,
		RECIPE_MODEL_LABEL,
		RECIPE_MODEL_LOADED,
		RECIPE_MODEL_LOADING,
		RECIPE_PRESET_CUSTOM_OPTION,
		RECIPE_PRESET_DEFAULT_OPTION,
		RECIPE_PRESET_LABEL,
		RECIPE_PRESET_NAME_PLACEHOLDER,
		RECIPE_PRESET_SAVE_ERROR,
		RECIPE_REFERENCE_LABEL,
		RECIPE_REFERENCE_UPLOAD,
		RECIPE_REFERENCE_UPLOAD_ERROR,
		RECIPE_REFERENCE_UPLOADING,
		RECIPE_RESET_ALL_LABEL,
		RECIPE_RESET_GLYPH,
		RECIPE_RETRY_LABEL,
		RECIPE_SAVED_WITH_VERSION,
		RECIPE_SAVE_AS_PRESET_LABEL,
		RECIPE_TAB_LABELS,
		RECIPE_TABS_LABEL,
		RECIPE_TAKES_LABEL,
		RECIPE_TAKES_OPTIONS
	} from '$lib/constants/recipe';
	import ParamControls from '../ParamControls.svelte';
	import VoicePicker from '../VoicePicker.svelte';

	interface Props {
		values: RecipeValues;
		standard: RecipeStandard;
		onchange: (next: RecipeValues) => void;
		onclose: () => void;
	}

	let { values, standard, onchange, onclose }: Props = $props();

	const TABS = ['song', 'generate', 'engine'] as const satisfies readonly RecipeTab[];
	// Model and Takes are session state, not part of a version.
	const TABS_SAVED_WITH_VERSION: readonly RecipeTab[] = ['song', 'engine'];

	let selected = $state<RecipeTab>('song');
	let referenceFilename = $state<string | null>(null);
	let referenceUploading = $state(false);
	let referenceError = $state<string | null>(null);
	let savingPreset = $state(false);
	let presetName = $state('');
	let presetError = $state<string | null>(null);
	let tablist: HTMLDivElement | undefined = $state();

	const changedFields = $derived(changedRecipeFields(values, standard));
	const changedTabs = $derived(changedRecipeTabs(values, standard));
	const activeModel = $derived($activeModels.find((model) => model.id === values.model));
	const modelsReady = $derived(!$activeModelsLoading && !$activeModelsError);
	const matchingPresets = $derived($presets.filter((preset) => preset.model_mode === values.model));
	const ownPresets = $derived(matchingPresets.filter((preset) => !preset.is_shared));
	const sharedPresets = $derived(matchingPresets.filter((preset) => preset.is_shared));
	const chosenPreset = $derived(matchingEnginePreset(values, $presets));
	const hasEngineChange = $derived(changedFields.has('preset'));
	const referencePath = $derived(values.genParams?.reference_audio_path ?? null);

	function change(field: RecipeField): void {
		onchange(resetRecipeField(values, field, standard));
	}

	function selectTab(tab: RecipeTab): void {
		selected = tab;
	}

	async function onTabKeydown(event: KeyboardEvent): Promise<void> {
		const index = TABS.indexOf(selected);
		let next: RecipeTab;
		switch (event.key) {
			case 'ArrowLeft':
				next = TABS[(index + TABS.length - 1) % TABS.length];
				break;
			case 'ArrowRight':
				next = TABS[(index + 1) % TABS.length];
				break;
			case 'Home':
				next = TABS[0];
				break;
			case 'End':
				next = TABS[TABS.length - 1];
				break;
			default:
				return;
		}
		event.preventDefault();
		selected = next;
		await tick();
		tablist?.querySelector<HTMLButtonElement>(`[data-tab="${next}"]`)?.focus();
	}

	function setNumber(field: 'bpm' | 'audioDuration', raw: string): void {
		onchange({ ...values, [field]: raw === '' ? 0 : Number(raw) });
	}

	async function uploadReference(event: Event): Promise<void> {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		referenceUploading = true;
		referenceError = null;
		try {
			const result = await uploadReferenceAudio(file);
			onchange({
				...values,
				genParams: { ...values.genParams, reference_audio_path: result.path }
			});
			referenceFilename = result.filename;
		} catch (error) {
			referenceError = describeFailure(error, RECIPE_REFERENCE_UPLOAD_ERROR);
		} finally {
			referenceUploading = false;
			input.value = '';
		}
	}

	function choosePreset(presetId: string): void {
		const preset = matchingPresets.find((candidate) => candidate.id === presetId);
		onchange(chooseEnginePreset(values, preset?.params ?? null));
	}

	async function confirmSavePreset(): Promise<void> {
		const name = presetName.trim();
		if (!name || values.model === null) return;
		presetError = null;
		try {
			await savePreset(name, values.model, engineParams(values), false);
			savingPreset = false;
			presetName = '';
		} catch (error) {
			presetError = describeFailure(error, RECIPE_PRESET_SAVE_ERROR);
		}
	}
</script>

{#snippet mark(field: RecipeField, title: string)}
	{#if changedFields.has(field)}
		<i class="dot" data-field-changed aria-hidden="true"></i>
		<button
			type="button"
			class="reset"
			data-field-reset={field}
			{title}
			aria-label={title}
			onclick={() => change(field)}>{RECIPE_RESET_GLYPH}</button
		>
	{/if}
{/snippet}

{#snippet row(field: RecipeField, label: string, control: Snippet)}
	<div class="kv" data-field={field}>
		<span class="k">{label}</span>
		<span class="v">
			{@render control()}
			{@render mark(field, RECIPE_FIELD_RESET_TITLES[field] ?? '')}
		</span>
	</div>
{/snippet}

{#snippet bpmControl()}
	<input
		type="number"
		min="0"
		max={RECIPE_BPM_MAX}
		aria-label={RECIPE_BPM_LABEL}
		placeholder={RECIPE_AUTO_LABEL}
		value={values.bpm || ''}
		oninput={(event) => setNumber('bpm', event.currentTarget.value)}
	/>
{/snippet}

{#snippet durationControl()}
	<input
		type="number"
		min="0"
		max={RECIPE_DURATION_MAX_SECONDS}
		aria-label={RECIPE_DURATION_LABEL}
		placeholder={RECIPE_AUTO_LABEL}
		value={values.audioDuration || ''}
		oninput={(event) => setNumber('audioDuration', event.currentTarget.value)}
	/>
{/snippet}

{#snippet keyControl()}
	<input
		type="text"
		aria-label={RECIPE_KEY_LABEL}
		placeholder={RECIPE_EMPTY_LABEL}
		value={values.keyScale}
		oninput={(event) => onchange({ ...values, keyScale: event.currentTarget.value })}
	/>
{/snippet}

{#snippet referenceControl()}
	{#if referencePath}
		<span class="reference-name">{referenceFilename ?? referencePath}</span>
	{:else}
		<label class="upload"
			>{referenceUploading ? RECIPE_REFERENCE_UPLOADING : RECIPE_REFERENCE_UPLOAD}<input
				type="file"
				accept=".mp3,.wav,.flac,.ogg"
				disabled={referenceUploading}
				onchange={uploadReference}
			/></label
		>
	{/if}
{/snippet}

{#snippet modelControl()}
	<select
		aria-label={RECIPE_MODEL_LABEL}
		value={values.model ?? ''}
		disabled={$activeModelsLoading || !$activeModels.length}
		onchange={(event) => onchange({ ...values, model: event.currentTarget.value })}
	>
		{#if $activeModelsLoading}
			<option value="">{RECIPE_MODEL_LOADING}</option>
		{:else if !activeModel}
			<option value="">{VOICE_PICKER_NONE_LABEL}</option>
		{/if}
		{#each $activeModels as model (model.id)}
			<option value={model.id}>{model.id.toUpperCase()}</option>
		{/each}
	</select>
	{#if activeModel && modelsReady}
		<span class="loaded">● {RECIPE_MODEL_LOADED}</span>
	{/if}
{/snippet}

{#snippet takesControl()}
	<span class="seg" role="group" aria-label={RECIPE_TAKES_LABEL}>
		{#each RECIPE_TAKES_OPTIONS as count (count)}
			<button
				type="button"
				aria-pressed={values.takes === count}
				onclick={() => onchange({ ...values, takes: count })}>{count}</button
			>
		{/each}
	</span>
{/snippet}

{#snippet presetControl()}
	<select
		aria-label={RECIPE_PRESET_LABEL}
		value={chosenPreset?.id ?? (hasEngineChange ? 'custom' : '')}
		onchange={(event) => choosePreset(event.currentTarget.value)}
	>
		{#if !chosenPreset && hasEngineChange}
			<option value="custom" disabled>{RECIPE_PRESET_CUSTOM_OPTION}</option>
		{/if}
		<option value="">{RECIPE_PRESET_DEFAULT_OPTION}</option>
		{#each ownPresets as preset (preset.id)}
			<option value={preset.id}>{preset.name}</option>
		{/each}
		{#each sharedPresets as preset (preset.id)}
			<option value={preset.id}>{preset.name} (shared)</option>
		{/each}
	</select>
{/snippet}

{#snippet footer(tab: RecipeTab)}
	<div class="foot">
		{#if TABS_SAVED_WITH_VERSION.includes(tab)}
			<span class="saved">{RECIPE_SAVED_WITH_VERSION}</span>
		{/if}
		<button
			type="button"
			class="reset-all"
			disabled={!changedTabs.has(tab)}
			onclick={() => onchange(resetRecipeTab(values, tab, standard))}
			>{RECIPE_RESET_ALL_LABEL}</button
		>
	</div>
{/snippet}

<div class="card" role="region" aria-label={RECIPE_PANEL_LABEL}>
	<div class="tabs">
		<div class="tablist" role="tablist" aria-label={RECIPE_TABS_LABEL} bind:this={tablist}>
			{#each TABS as tab (tab)}
				<button
					type="button"
					role="tab"
					id={`recipe-tab-${tab}`}
					aria-controls={selected === tab ? 'recipe-panel' : undefined}
					aria-selected={selected === tab}
					tabindex={selected === tab ? 0 : -1}
					data-tab={tab}
					class:active={selected === tab}
					onclick={() => selectTab(tab)}
					onkeydown={onTabKeydown}
				>
					{RECIPE_TAB_LABELS[tab]}
					{#if changedTabs.has(tab)}<i class="dot" data-tab-changed aria-hidden="true"></i>{/if}
				</button>
			{/each}
		</div>
		<button
			type="button"
			class="close"
			title={RECIPE_CLOSE_LABEL}
			aria-label={RECIPE_CLOSE_LABEL}
			onclick={onclose}>˄</button
		>
	</div>

	<div id="recipe-panel" role="tabpanel" aria-labelledby={`recipe-tab-${selected}`}>
		{#if selected === 'song'}
			{@render row('bpm', RECIPE_BPM_LABEL, bpmControl)}
			{@render row('duration', RECIPE_DURATION_LABEL, durationControl)}
			{@render row('key', RECIPE_KEY_LABEL, keyControl)}
			<div class="kv" data-field="voice">
				<VoicePicker />
				<span class="v">{@render mark('voice', RECIPE_FIELD_RESET_TITLES.voice ?? '')}</span>
			</div>
			{@render row('reference', RECIPE_REFERENCE_LABEL, referenceControl)}
			{#if referenceError}<p class="error" role="alert">{referenceError}</p>{/if}
		{:else if selected === 'generate'}
			{@render row('model', RECIPE_MODEL_LABEL, modelControl)}
			{#if $activeModelsError}
				<p class="error" role="alert">{$activeModelsError}</p>
				<button type="button" class="retry" onclick={loadActiveModels}>{RECIPE_RETRY_LABEL}</button>
			{/if}
			{@render row('takes', RECIPE_TAKES_LABEL, takesControl)}
		{:else}
			{@render row('preset', RECIPE_PRESET_LABEL, presetControl)}
			<div class="preset-actions">
				{#if savingPreset}
					<input
						type="text"
						aria-label={RECIPE_PRESET_NAME_PLACEHOLDER}
						placeholder={RECIPE_PRESET_NAME_PLACEHOLDER}
						bind:value={presetName}
						onkeydown={(event) => event.key === 'Enter' && confirmSavePreset()}
					/>
					<button type="button" onclick={confirmSavePreset}>Save</button>
					<button type="button" onclick={() => (savingPreset = false)}>Cancel</button>
				{:else}
					<button type="button" onclick={() => (savingPreset = true)}
						>{RECIPE_SAVE_AS_PRESET_LABEL}</button
					>
				{/if}
				<a
					href="/settings/generation"
					onclick={(event) => followAppPageLink(event, '/settings/generation')}
					>{RECIPE_MANAGE_PRESETS_LABEL}</a
				>
			</div>
			{#if presetError}<p class="error" role="alert">{presetError}</p>{/if}
			{#if $generationDefaultsError}
				<p class="error" role="alert">{RECIPE_DEFAULTS_ERROR}</p>
				<button type="button" class="retry" onclick={loadGenerationDefaults}
					>{RECIPE_RETRY_LABEL}</button
				>
			{/if}
			<div class="engine">
				<ParamControls
					values={values.genParams ?? {}}
					placeholders={$effectiveGenerationDefaults}
					onchange={(params) =>
						onchange({ ...values, genParams: Object.keys(params).length > 0 ? params : null })}
					hiddenParams={activeModel?.capabilities?.hidden_params ?? []}
					maxInferenceSteps={activeModel?.capabilities?.max_inference_steps ??
						RECIPE_MAX_INFERENCE_STEPS_DEFAULT}
					changedKeys={changedFields}
					onresetfield={(key) => {
						if (isEngineParamKey(key)) change(key);
					}}
				/>
				<p class="hint">{RECIPE_ENGINE_EMPTY_HINT}</p>
			</div>
		{/if}
		{@render footer(selected)}
	</div>
</div>

<style>
	.card {
		border: 1px solid var(--primary);
		border-radius: var(--card-radius);
		background: var(--surface);
		min-width: 0;
	}

	.tabs {
		display: flex;
		align-items: center;
		border-bottom: 1px solid var(--border);
	}

	.tablist {
		display: flex;
		flex: 1;
		min-width: 0;
	}

	.tablist button,
	.close {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		min-height: var(--hitbox-frequent);
		padding: var(--btn-padding-pill);
		border: none;
		border-bottom: 2px solid transparent;
		background: none;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: var(--btn-font-size-sm);
		letter-spacing: var(--btn-letter-spacing);
		text-transform: uppercase;
		cursor: pointer;
	}

	.tablist button.active {
		color: var(--primary);
		border-color: var(--primary);
	}

	.dot {
		width: 0.45rem;
		height: 0.45rem;
		border-radius: 50%;
		background: var(--primary);
		flex-shrink: 0;
	}

	.kv {
		display: flex;
		align-items: center;
		gap: var(--row-gap);
		min-height: var(--hitbox-frequent);
		padding: 0 var(--row-padding);
		border-bottom: 1px solid var(--border);
	}

	.k {
		flex: 1;
		min-width: 0;
		color: var(--text-muted);
		font-size: var(--label-font-size);
	}

	.v {
		display: inline-flex;
		align-items: center;
		justify-content: flex-end;
		flex-wrap: wrap;
		gap: var(--row-gap);
		min-width: 0;
	}

	.kv input,
	.kv select,
	.preset-actions input {
		box-sizing: border-box;
		min-width: 0;
		min-height: var(--hitbox-frequent);
		padding: var(--input-padding);
		border: 1px solid var(--border);
		border-radius: var(--input-radius);
		background: var(--bg);
		color: var(--text);
		font-size: var(--input-font-size);
	}

	.kv input {
		width: 8rem;
		text-align: right;
	}

	.seg {
		display: inline-flex;
		gap: 0.25rem;
	}

	.seg button {
		min-width: var(--hitbox-frequent);
		min-height: var(--hitbox-frequent);
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: none;
		color: var(--text-muted);
		cursor: pointer;
	}

	.seg button[aria-pressed='true'] {
		border-color: var(--primary);
		color: var(--primary);
	}

	.upload input {
		display: none;
	}

	.upload,
	.reference-name {
		color: var(--text);
		font-size: var(--label-font-size);
		overflow-wrap: anywhere;
		cursor: pointer;
	}

	.loaded {
		color: var(--success);
		white-space: nowrap;
	}

	.reset,
	.close,
	.retry,
	.reset-all,
	.preset-actions button {
		cursor: pointer;
	}

	.reset {
		min-width: var(--hitbox-frequent);
		min-height: var(--hitbox-frequent);
		border: none;
		background: none;
		color: var(--text-muted);
	}

	.reset:hover {
		color: var(--primary);
	}

	.preset-actions,
	.foot {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--row-gap);
		padding: var(--row-padding);
	}

	.preset-actions button,
	.retry,
	.reset-all {
		min-height: var(--hitbox-frequent);
		padding: var(--btn-padding-sm);
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: none;
		color: var(--text);
		font-size: var(--btn-font-size-sm);
	}

	.reset-all:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.preset-actions a {
		margin-left: auto;
		color: var(--text-muted);
		font-size: var(--label-font-size);
	}

	.engine {
		padding: var(--row-padding);
		min-width: 0;
	}

	.foot {
		justify-content: space-between;
		border-top: 1px solid var(--border);
	}

	.saved,
	.hint {
		color: var(--text-muted);
		font-size: var(--label-font-size);
	}

	.hint {
		margin: 0.6rem 0 0;
	}

	.error {
		margin: 0;
		padding: var(--row-padding);
		color: var(--danger, var(--text));
		font-size: var(--label-font-size);
	}
</style>
