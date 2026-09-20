<script lang="ts">
	import { onMount } from 'svelte';
	import type { VersionGenerationParams } from '$lib/api/types';
	import { fetchGenerationDefaults, uploadReferenceAudio } from '$lib/api/client';
	import {
		editBpm,
		editAudioDuration,
		editKeyScale,
		editGenParams,
		savedSongData,
		setDraftBpm,
		setDraftAudioDuration,
		setDraftKeyScale,
		setDraftGenParams,
		pinnedSeed
	} from '$lib/stores/editor';
	import {
		recipeChips,
		recipeModel,
		recipeOpen,
		takesPerGenerate,
		sourceGeneration,
		sourceMode,
		repaintStart,
		repaintEnd,
		repaintMode,
		repaintStrength,
		coverStrength,
		coverNoiseStrength,
		clearSource
	} from '$lib/stores/recipe';
	import {
		activeModels,
		activeModelsLoading,
		activeModelsError,
		loadActiveModels,
		builtinDefaults,
		loadBuiltins,
		presets,
		loadPresets
	} from '$lib/stores/presets';
	import { loras } from '$lib/stores/loras';
	import {
		RECIPE_PANEL_LABEL,
		RECIPE_SOURCE_LABEL,
		RECIPE_GROUP_SOUND_LABEL,
		RECIPE_GROUP_TEXT_LABEL,
		RECIPE_GROUP_REPRODUCE_LABEL,
		RECIPE_PRESET_LABEL,
		RECIPE_PRESET_DEFAULT_OPTION,
		RECIPE_SEED_RANDOM_LABEL,
		RECIPE_SEED_PINNED_LABEL,
		RECIPE_DEFAULT_PINNED_SEED,
		RECIPE_REPAINT_OFF_LABEL,
		RECIPE_USES_LABEL,
		TAKE_REPAINT_LABEL,
		TAKE_COVER_LABEL,
		VOICE_PICKER_NONE_LABEL,
		VOICE_PICKER_DELETED_LABEL,
		PHONE_RECIPE_LOADING,
		PHONE_RECIPE_LOADED,
		PHONE_RECIPE_RETRY,
		PHONE_RECIPE_PARAMETERS,
		PHONE_RECIPE_CUSTOM,
		PHONE_RECIPE_REFERENCE,
		PHONE_RECIPE_UPLOAD,
		PHONE_RECIPE_UPLOAD_ERROR,
		PHONE_RECIPE_REMOVE,
		PHONE_RECIPE_DEFAULTS_ERROR,
		PHONE_RECIPE_REPAINT_STRENGTH,
		PHONE_RECIPE_COVER_STRENGTH,
		PHONE_RECIPE_NOISE_STRENGTH,
		PHONE_RECIPE_REPAINT_MODES
	} from '$lib/constants';
	import VoicePicker from '../VoicePicker.svelte';
	import ParamControls from '../ParamControls.svelte';
	import WaveformRangePicker from '../WaveformRangePicker.svelte';

	let openField = $state<string | null>(null);
	let globalDefaults = $state<Record<string, VersionGenerationParams>>({});
	let defaultsError = $state(false);
	let referenceUploading = $state(false);
	let referenceError = $state<string | null>(null);
	let referenceFilename = $state<string | null>(null);
	const voice = $derived($loras.find((item) => item.id === $editGenParams?.user_lora_id));
	const voiceLabel = $derived(
		voice
			? `${voice.name}${voice.deleted_at ? ` — ${VOICE_PICKER_DELETED_LABEL}` : ''}`
			: $editGenParams?.user_lora_id
				? PHONE_RECIPE_CUSTOM
				: VOICE_PICKER_NONE_LABEL
	);
	const chips = $derived(
		recipeChips({
			model: $recipeModel,
			takes: $takesPerGenerate,
			bpm: $editBpm,
			audioDuration: $editAudioDuration,
			keyScale: $editKeyScale,
			voiceLabel,
			pinnedSeed: $pinnedSeed,
			genParams: $editGenParams,
			sourceGeneration: $sourceGeneration,
			sourceMode: $sourceMode,
			repaintMode: $repaintMode,
			savedBpm: $savedSongData.bpm,
			savedAudioDuration: $savedSongData.audio_duration,
			savedKeyScale: $savedSongData.key_scale,
			savedGenParams: $savedSongData.genParams
		})
	);
	const soundOrder = ['model', 'duration', 'bpm', 'key', 'takes', 'voice'];
	const soundChips = $derived(
		chips
			.filter((chip) => soundOrder.includes(chip.key))
			.toSorted((a, b) => soundOrder.indexOf(a.key) - soundOrder.indexOf(b.key))
	);
	const parameterChips = $derived(chips.filter((chip) => chip.key === 'lm' || chip.key === 'dit'));
	const summary = $derived(
		soundChips
			.filter((chip) => chip.key !== 'voice')
			.map((chip) => (chip.key === 'bpm' ? `${chip.value} ${chip.label}` : chip.value))
			.join(' · ')
	);
	const modelData = $derived($activeModels.find((model) => model.id === $recipeModel));
	const modelValue = $derived(
		$activeModelsLoading
			? PHONE_RECIPE_LOADING
			: ($activeModelsError ?? (modelData ? modelData.id.toUpperCase() : VOICE_PICKER_NONE_LABEL))
	);
	const effectiveDefaults = $derived({
		...($builtinDefaults[$recipeModel ?? ''] ?? {}),
		...(globalDefaults[$recipeModel ?? ''] ?? {})
	} as Required<VersionGenerationParams>);
	const referencePath = $derived($editGenParams?.reference_audio_path ?? null);
	const matchingPresets = $derived($presets.filter((preset) => preset.model_mode === $recipeModel));
	const selectedPreset = $derived(
		matchingPresets.find((preset) => {
			const params = $editGenParams ?? {};
			const keys = new Set([...Object.keys(preset.params), ...Object.keys(params)]);
			return [...keys].every(
				(key) =>
					preset.params[key as keyof VersionGenerationParams] ===
					params[key as keyof VersionGenerationParams]
			);
		})
	);
	const groups = $derived([
		{
			label: RECIPE_GROUP_SOUND_LABEL,
			rows: [
				...soundChips.map((chip) => ({
					...chip,
					value: chip.key === 'model' ? modelValue : chip.value
				})),
				{
					key: 'reference',
					label: PHONE_RECIPE_REFERENCE,
					value: referenceFilename ?? referencePath ?? VOICE_PICKER_NONE_LABEL,
					changed: false
				}
			]
		},
		{
			label: RECIPE_GROUP_TEXT_LABEL,
			rows: [
				{
					key: 'preset',
					label: RECIPE_PRESET_LABEL,
					value:
						selectedPreset?.name ??
						($editGenParams ? PHONE_RECIPE_CUSTOM : RECIPE_PRESET_DEFAULT_OPTION),
					changed: false
				},
				{
					key: 'parameters',
					label: PHONE_RECIPE_PARAMETERS,
					value: parameterChips.map((chip) => chip.value).join(' / '),
					changed: parameterChips.some((chip) => chip.changed)
				}
			]
		},
		{
			label: RECIPE_GROUP_REPRODUCE_LABEL,
			rows: chips.filter((chip) => chip.key === 'seed' || chip.key === 'repaint')
		}
	]);

	async function loadDefaults(): Promise<void> {
		defaultsError = false;
		try {
			globalDefaults = await fetchGenerationDefaults();
		} catch {
			defaultsError = true;
		}
	}

	async function uploadReference(event: Event): Promise<void> {
		const input = event.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		referenceUploading = true;
		referenceError = null;
		try {
			const result = await uploadReferenceAudio(file);
			setDraftGenParams({ ...($editGenParams ?? {}), reference_audio_path: result.path });
			referenceFilename = result.filename;
		} catch (error) {
			referenceError = error instanceof Error ? error.message : PHONE_RECIPE_UPLOAD_ERROR;
		} finally {
			referenceUploading = false;
			input.value = '';
		}
	}

	onMount(() => {
		void loadBuiltins();
		void loadPresets();
		void loadDefaults();
	});
</script>

<section class="phone-recipe" aria-label={RECIPE_PANEL_LABEL}>
	<button
		type="button"
		class="recipe-heading"
		data-hitbox="text"
		aria-label={RECIPE_PANEL_LABEL}
		aria-expanded={$recipeOpen}
		aria-controls="phone-recipe-fields"
		onclick={() => recipeOpen.update((open) => !open)}
	>
		<span class="heading-copy"
			><span class="label">{RECIPE_PANEL_LABEL}</span><span class="summary">{summary}</span></span
		>
		<span class="chevron" aria-hidden="true">{$recipeOpen ? '⌃' : '⌄'}</span>
	</button>
	{#if $recipeOpen}
		<div id="phone-recipe-fields">
			{#each groups as group (group.label)}
				<h3>{group.label}</h3>
				{#each group.rows as row (row.key)}
					<button
						type="button"
						class="recipe-row"
						data-hitbox="text"
						aria-label={row.label}
						aria-expanded={openField === row.key}
						aria-controls={`phone-recipe-${row.key}`}
						onclick={() => (openField = openField === row.key ? null : row.key)}
					>
						<span class="row-label">{row.label}</span>
						<span class="row-value"
							>{row.value}{#if row.changed}<span aria-hidden="true"> *</span>{/if}
							{#if row.key === 'model' && modelData && !$activeModelsLoading && !$activeModelsError}
								<span class="model-ready">● {PHONE_RECIPE_LOADED}</span>
							{/if}
						</span>
						<span class="chevron" aria-hidden="true">{openField === row.key ? '⌄' : '›'}</span>
					</button>
					{#if openField === row.key}
						<div class="field-editor" id={`phone-recipe-${row.key}`}>
							{#if row.key === 'model'}
								{#if $activeModelsError}<p role="alert">{$activeModelsError}</p>
									<button type="button" onclick={loadActiveModels}>{PHONE_RECIPE_RETRY}</button
									>{/if}
								<select
									aria-label={row.label}
									value={$recipeModel ?? ''}
									disabled={$activeModelsLoading || !$activeModels.length}
									onchange={(event) => recipeModel.set(event.currentTarget.value)}
								>
									{#if !modelData}<option value="">{VOICE_PICKER_NONE_LABEL}</option>{/if}
									{#each $activeModels as model (model.id)}<option value={model.id}
											>{model.id.toUpperCase()}</option
										>{/each}
								</select>
							{:else if row.key === 'bpm' || row.key === 'duration'}
								<input
									aria-label={row.label}
									type="number"
									min="0"
									max={row.key === 'bpm' ? 999 : 600}
									value={row.key === 'bpm' ? $editBpm : $editAudioDuration}
									oninput={(event) =>
										(row.key === 'bpm' ? setDraftBpm : setDraftAudioDuration)(
											Number(event.currentTarget.value)
										)}
								/>
							{:else if row.key === 'key'}
								<input
									aria-label={row.label}
									value={$editKeyScale}
									oninput={(event) => setDraftKeyScale(event.currentTarget.value)}
								/>
							{:else if row.key === 'takes'}
								<select
									aria-label={row.label}
									value={$takesPerGenerate}
									onchange={(event) => takesPerGenerate.set(Number(event.currentTarget.value))}
								>
									{#each [1, 2, 3, 5, 10] as count (count)}<option value={count}>×{count}</option
										>{/each}
								</select>
							{:else if row.key === 'voice'}
								<VoicePicker />
							{:else if row.key === 'reference'}
								{#if referencePath}
									<button
										type="button"
										onclick={() => {
											const { reference_audio_path: _removed, ...rest } = $editGenParams ?? {};
											setDraftGenParams(Object.keys(rest).length ? rest : null);
											referenceFilename = null;
										}}>{PHONE_RECIPE_REMOVE}</button
									>
								{:else}
									<label
										>{referenceUploading ? PHONE_RECIPE_LOADING : PHONE_RECIPE_UPLOAD}<input
											type="file"
											accept=".mp3,.wav,.flac,.ogg"
											disabled={referenceUploading}
											onchange={uploadReference}
										/></label
									>
								{/if}
								{#if referenceError}<p role="alert">{referenceError}</p>{/if}
							{:else if row.key === 'preset'}
								<select
									aria-label={row.label}
									value={selectedPreset?.id ?? ($editGenParams ? 'custom' : '')}
									onchange={(event) =>
										setDraftGenParams(
											matchingPresets.find((preset) => preset.id === event.currentTarget.value)
												?.params ?? null
										)}
								>
									{#if !selectedPreset && $editGenParams}
										<option value="custom" disabled>{PHONE_RECIPE_CUSTOM}</option>
									{/if}
									<option value="">{RECIPE_PRESET_DEFAULT_OPTION}</option>
									{#each matchingPresets as preset (preset.id)}<option value={preset.id}
											>{preset.name}</option
										>{/each}
								</select>
							{:else if row.key === 'parameters'}
								{#if defaultsError}<p role="alert">{PHONE_RECIPE_DEFAULTS_ERROR}</p>
									<button type="button" onclick={loadDefaults}>{PHONE_RECIPE_RETRY}</button>{/if}
								<ParamControls
									values={$editGenParams ?? {}}
									placeholders={effectiveDefaults}
									onchange={(params) =>
										setDraftGenParams(Object.keys(params).length ? params : null)}
									hiddenParams={modelData?.capabilities?.hidden_params ?? []}
									maxInferenceSteps={modelData?.capabilities?.max_inference_steps ?? 200}
								/>
							{:else if row.key === 'seed'}
								<div class="choices">
									<button
										type="button"
										aria-pressed={$pinnedSeed === null}
										onclick={() => pinnedSeed.set(null)}>{RECIPE_SEED_RANDOM_LABEL}</button
									>
									<button
										type="button"
										aria-pressed={$pinnedSeed !== null}
										onclick={() => pinnedSeed.set($pinnedSeed ?? RECIPE_DEFAULT_PINNED_SEED)}
										>{RECIPE_SEED_PINNED_LABEL}</button
									>
								</div>
								{#if $pinnedSeed !== null}<input
										type="number"
										min="0"
										aria-label={row.label}
										value={$pinnedSeed}
										oninput={(event) => pinnedSeed.set(Number(event.currentTarget.value))}
									/>{/if}
							{:else if row.key === 'repaint'}
								<button type="button" onclick={clearSource}>{RECIPE_REPAINT_OFF_LABEL}</button>
								{#if $sourceGeneration}
									<select aria-label={RECIPE_SOURCE_LABEL} bind:value={$sourceMode}
										><option value="repaint">{TAKE_REPAINT_LABEL}</option><option value="cover"
											>{TAKE_COVER_LABEL}</option
										></select
									>
									{#if $sourceMode === 'repaint'}
										<select aria-label={TAKE_REPAINT_LABEL} bind:value={$repaintMode}
											>{#each PHONE_RECIPE_REPAINT_MODES as mode (mode.value)}<option
													value={mode.value}>{mode.label}</option
												>{/each}</select
										>
										<WaveformRangePicker
											audioUrl={`/audio/${$sourceGeneration.mp3_path}`}
											duration={$sourceGeneration.generation_params?.audio_duration ?? 180}
											startPercent={$repaintStart}
											endPercent={$repaintEnd}
											onchange={(start, end) => {
												repaintStart.set(start);
												repaintEnd.set(end);
											}}
										/>
										{#if $repaintMode === 'balanced'}<label
												>{PHONE_RECIPE_REPAINT_STRENGTH}<input
													type="range"
													min="0"
													max="1"
													step="0.01"
													bind:value={$repaintStrength}
												/><output>{Math.round($repaintStrength * 100)}%</output></label
											>{/if}
									{:else}
										<label
											>{PHONE_RECIPE_COVER_STRENGTH}<input
												type="range"
												min="0"
												max="1"
												step="0.01"
												bind:value={$coverStrength}
											/><output>{Math.round($coverStrength * 100)}%</output></label
										>
										<label
											>{PHONE_RECIPE_NOISE_STRENGTH}<input
												type="range"
												min="0"
												max="1"
												step="0.01"
												bind:value={$coverNoiseStrength}
											/><output>{Math.round($coverNoiseStrength * 100)}%</output></label
										>
									{/if}
								{/if}
							{/if}
						</div>
					{/if}
				{/each}
			{/each}
			<p class="footer">{RECIPE_USES_LABEL}</p>
		</div>
	{/if}
</section>

<style>
	.phone-recipe {
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface);
		min-width: 0;
	}
	.recipe-heading,
	.recipe-row {
		display: flex;
		align-items: center;
		gap: var(--row-gap);
		width: 100%;
		padding: var(--row-padding);
		border: none;
		background: none;
		color: var(--text);
		text-align: left;
		cursor: pointer;
		font: inherit;
	}
	.heading-copy {
		display: flex;
		flex-direction: column;
		min-width: 0;
		flex: 1;
		gap: var(--row-gap);
	}
	.label,
	h3 {
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		text-transform: uppercase;
		color: var(--text-muted);
	}
	.summary {
		font-size: var(--label-font-size);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	h3 {
		margin: 0;
		padding: var(--row-padding);
		border-top: 1px solid var(--border);
	}
	.recipe-row {
		border-top: 1px solid var(--border);
		font-size: var(--label-font-size);
	}
	.row-label {
		color: var(--text-muted);
		flex: 1;
	}
	.row-value {
		min-width: 0;
		max-width: 65%;
		overflow-wrap: anywhere;
		text-align: right;
	}
	.model-ready {
		color: var(--success);
		white-space: nowrap;
	}
	.chevron {
		flex-shrink: 0;
	}
	.field-editor {
		padding: var(--row-padding);
		display: flex;
		flex-direction: column;
		gap: var(--row-gap);
		min-width: 0;
	}
	.field-editor label {
		display: flex;
		flex-direction: column;
		gap: var(--row-gap);
	}
	.field-editor input,
	.field-editor select {
		box-sizing: border-box;
		min-width: 0;
		width: 100%;
		min-height: var(--hitbox-frequent);
		padding: var(--input-padding);
		border: 1px solid var(--border);
		border-radius: var(--input-radius);
		background: var(--bg);
		color: var(--text);
		font-size: var(--input-font-size);
	}
	.field-editor button {
		min-height: var(--hitbox-frequent);
		padding: var(--btn-padding-sm);
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: none;
		color: var(--text);
		font-size: var(--btn-font-size-sm);
		cursor: pointer;
	}
	.field-editor button[aria-pressed='true'] {
		border-color: var(--primary);
	}
	.choices {
		display: flex;
		gap: var(--row-gap);
	}
	.footer {
		margin: 0;
		padding: var(--row-padding);
		text-align: right;
		color: var(--text-muted);
		font-size: var(--label-font-size);
	}
</style>
