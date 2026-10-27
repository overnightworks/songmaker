<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { onMount } from 'svelte';
	import {
		editBpm,
		editAudioDuration,
		editKeyScale,
		editGenParams,
		setDraftBpm,
		setDraftAudioDuration,
		setDraftKeyScale,
		setDraftGenParams
	} from '$lib/stores/editor';
	import { recipeModel, takesPerGenerate } from '$lib/stores/recipe';
	import {
		activeModels,
		builtinDefaults,
		loadActiveModels,
		loadBuiltins,
		loadPresets,
		presets,
		savePreset,
		sharedPresets,
		userPresets
	} from '$lib/stores/presets';
	import { fetchGenerationDefaults, uploadReferenceAudio } from '$lib/api/client';
	import { describeFailure } from '$lib/api/fetch';
	import type { VersionGenerationParams } from '$lib/api/types';
	import { followAppPageLink } from '$lib/stores/navigation';
	import { addToast } from '$lib/stores/toast';
	import {
		RECIPE_COLLAPSE_LABEL,
		RECIPE_GROUP_SOUND_LABEL,
		RECIPE_GROUP_TEXT_LABEL,
		RECIPE_MANAGE_PRESETS_LABEL,
		RECIPE_PANEL_LABEL,
		RECIPE_PRESET_DEFAULT_OPTION,
		RECIPE_PRESET_LABEL,
		RECIPE_SAVED_HINT,
		RECIPE_SAVE_AS_PRESET_LABEL,
		RECIPE_USES_LABEL
	} from '$lib/constants';
	import ParamControls from '../ParamControls.svelte';
	import VoicePicker from '../VoicePicker.svelte';

	interface Props {
		onclose: () => void;
	}

	let { onclose }: Props = $props();

	let globalDefaults = $state<Record<string, VersionGenerationParams>>({});
	let savingPresetName = $state('');
	let showSavePresetInput = $state(false);
	let referenceFilename = $state<string | null>(null);
	let referenceUploading = $state(false);

	const activeMode = $derived($recipeModel ?? '');
	const activeModelData = $derived($activeModels.find((m) => m.id === activeMode));
	const hiddenParams = $derived(activeModelData?.capabilities?.hidden_params ?? []);
	const maxInferenceSteps = $derived(activeModelData?.capabilities?.max_inference_steps ?? 200);
	const effectiveDefaults = $derived.by((): Required<VersionGenerationParams> => {
		const builtin = activeMode ? ($builtinDefaults[activeMode] ?? {}) : {};
		const global = activeMode ? (globalDefaults[activeMode] ?? {}) : {};
		return { ...builtin, ...global } as Required<VersionGenerationParams>;
	});

	const filteredUserPresets = $derived(
		$recipeModel ? $userPresets.filter((p) => p.model_mode === $recipeModel) : $userPresets
	);
	const filteredSharedPresets = $derived(
		$recipeModel ? $sharedPresets.filter((p) => p.model_mode === $recipeModel) : $sharedPresets
	);
	const selectedPresetId = $derived(
		$presets.find(
			(p) => p.model_mode === $recipeModel && paramsEqual(p.params, $editGenParams ?? {})
		)?.id ?? ''
	);

	const referenceAudioPath = $derived(($editGenParams ?? {}).reference_audio_path ?? null);

	function paramsEqual(a: VersionGenerationParams, b: VersionGenerationParams): boolean {
		const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
		for (const key of keys) {
			if ((a as Record<string, unknown>)[key] !== (b as Record<string, unknown>)[key]) return false;
		}
		return true;
	}

	function selectPreset(presetId: string): void {
		if (!presetId) {
			setDraftGenParams(null);
			return;
		}
		const preset = $presets.find((p) => p.id === presetId);
		if (preset) setDraftGenParams({ ...preset.params });
	}

	async function confirmSavePreset(): Promise<void> {
		const name = savingPresetName.trim();
		if (!name) return;
		try {
			await savePreset(name, activeMode, $editGenParams ?? {}, false);
			addToast('Preset saved', 'success');
			showSavePresetInput = false;
			savingPresetName = '';
		} catch (e) {
			addToast(describeFailure(e, 'Failed to save preset'), 'error');
		}
	}

	async function handleReferenceUpload(e: Event): Promise<void> {
		const input = e.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		referenceUploading = true;
		try {
			const result = await uploadReferenceAudio(file);
			setDraftGenParams({ ...($editGenParams ?? {}), reference_audio_path: result.path });
			referenceFilename = result.filename;
		} catch (err) {
			addToast(describeFailure(err, 'Upload failed'), 'error');
		} finally {
			referenceUploading = false;
			input.value = '';
		}
	}

	function clearReference(): void {
		const { reference_audio_path: _removed, ...rest } = $editGenParams ?? {};
		setDraftGenParams(Object.keys(rest).length > 0 ? rest : null);
		referenceFilename = null;
	}

	onMount(async () => {
		await Promise.all([
			loadBuiltins(),
			loadPresets(),
			loadActiveModels(),
			fetchGenerationDefaults()
				.then((d) => (globalDefaults = d))
				.catch(() => {})
		]);
	});
</script>

<div class="recipe-panel" role="region" aria-label={RECIPE_PANEL_LABEL}>
	<div class="recipe-panel-header">
		<span class="recipe-hint">{RECIPE_SAVED_HINT}</span>
		<button type="button" class="collapse-btn" data-hitbox="frequent" onclick={onclose}
			>{RECIPE_COLLAPSE_LABEL} ˄</button
		>
	</div>

	<div class="preset-row">
		<label class="preset-select-label">
			<span>{RECIPE_PRESET_LABEL}</span>
			<select value={selectedPresetId} onchange={(e) => selectPreset(e.currentTarget.value)}>
				<option value="">{RECIPE_PRESET_DEFAULT_OPTION}</option>
				{#each filteredUserPresets as preset (preset.id)}
					<option value={preset.id}>{preset.name}</option>
				{/each}
				{#each filteredSharedPresets as preset (preset.id)}
					<option value={preset.id}>{preset.name} (shared)</option>
				{/each}
			</select>
		</label>
		{#if showSavePresetInput}
			<input
				class="preset-name-input"
				type="text"
				placeholder="Preset name"
				bind:value={savingPresetName}
				onkeydown={(e) => e.key === 'Enter' && confirmSavePreset()}
			/>
			<button type="button" class="preset-save-confirm" onclick={confirmSavePreset}>Save</button>
			<button type="button" class="preset-save-cancel" onclick={() => (showSavePresetInput = false)}
				>Cancel</button
			>
		{:else}
			<button
				type="button"
				class="preset-save-btn"
				data-hitbox="frequent"
				onclick={() => (showSavePresetInput = true)}
			>
				{RECIPE_SAVE_AS_PRESET_LABEL}
			</button>
		{/if}
		<a
			class="preset-manage-link"
			href="/settings/generation"
			onclick={(event) => followAppPageLink(event, '/settings/generation')}
			>{RECIPE_MANAGE_PRESETS_LABEL}</a
		>
	</div>

	<div class="recipe-groups">
		<section class="recipe-group">
			<h4 class="group-title">{RECIPE_GROUP_SOUND_LABEL}</h4>
			<div class="group-grid">
				<label class="field">
					<span>BPM <small class="hint">(0 = auto)</small></span>
					<input
						type="number"
						min="0"
						max="999"
						value={$editBpm}
						oninput={(e) => setDraftBpm(Number(e.currentTarget.value))}
					/>
				</label>
				<label class="field">
					<span>Duration <small class="hint">(0 = auto)</small></span>
					<input
						type="number"
						min="0"
						max="600"
						value={$editAudioDuration}
						oninput={(e) => setDraftAudioDuration(Number(e.currentTarget.value))}
					/>
				</label>
				<label class="field">
					<span>Key</span>
					<input
						type="text"
						value={$editKeyScale}
						oninput={(e) => setDraftKeyScale(e.currentTarget.value)}
					/>
				</label>
				<label class="field">
					<span>Model</span>
					<select
						value={$recipeModel ?? ''}
						onchange={(e) => recipeModel.set(e.currentTarget.value)}
					>
						{#each $activeModels as m (m.id)}
							<option value={m.id}>{m.id.toUpperCase()}</option>
						{/each}
					</select>
				</label>
				<label class="field">
					<span>Takes per Generate</span>
					<select
						value={$takesPerGenerate}
						onchange={(e) => takesPerGenerate.set(Number(e.currentTarget.value))}
					>
						{#each [1, 2, 3, 5, 10] as n (n)}
							<option value={n}>×{n}</option>
						{/each}
					</select>
				</label>
			</div>
			<VoicePicker />
			<div class="reference-section">
				<span class="ref-label">Reference Track</span>
				{#if referenceAudioPath}
					<div class="ref-active">
						<span class="ref-name">{referenceFilename ?? referenceAudioPath}</span>
						<button type="button" class="ref-clear" onclick={clearReference}>x</button>
					</div>
				{:else}
					<label class="ref-upload">
						<input
							type="file"
							accept=".mp3,.wav,.flac,.ogg"
							onchange={handleReferenceUpload}
							disabled={referenceUploading}
						/>
						{referenceUploading ? 'Uploading...' : 'Upload audio'}
					</label>
				{/if}
			</div>
		</section>

		<section class="recipe-group">
			<h4 class="group-title">{RECIPE_GROUP_TEXT_LABEL}</h4>
			<ParamControls
				values={$editGenParams ?? {}}
				placeholders={effectiveDefaults}
				onchange={(p) => setDraftGenParams(Object.keys(p).length > 0 ? p : null)}
				{hiddenParams}
				{maxInferenceSteps}
			/>
		</section>
	</div>

	<p class="recipe-footer-hint">{RECIPE_USES_LABEL}</p>
</div>

<style>
	.recipe-panel {
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		padding: 0.9rem;
		background: var(--surface);
		border: 1px solid var(--primary);
		border-radius: var(--card-radius);
	}

	.recipe-panel-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.7rem;
	}

	.recipe-hint {
		font-size: 0.75rem;
		color: var(--text-subtle);
	}

	.collapse-btn {
		background: none;
		border: none;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: var(--label-font-size);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		cursor: pointer;
	}

	.collapse-btn:hover {
		color: var(--primary);
	}

	.preset-row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.55rem;
		padding-bottom: 0.7rem;
		border-bottom: 1px solid var(--border);
	}

	.preset-select-label {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		font-size: var(--label-font-size);
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.preset-select-label select,
	.preset-name-input,
	.field select,
	.field input {
		padding: 0.35rem 0.55rem;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 0.85rem;
	}

	.preset-save-btn,
	.preset-save-confirm,
	.preset-save-cancel {
		padding: 0.3rem 0.7rem;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: none;
		color: var(--text-muted);
		font-size: 0.75rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.4px;
		cursor: pointer;
	}

	.preset-save-btn:hover,
	.preset-save-confirm:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.preset-manage-link {
		margin-left: auto;
		font-size: 0.75rem;
		color: var(--text-subtle);
	}

	.preset-manage-link:hover {
		color: var(--primary);
	}

	/* Sound / Text / Reproduce are three equal groups, so they need no
	   threshold at all: as many as fit the width the panel actually has, one
	   below a readable 13rem each (#185). This also holds in the compact
	   sheet, which renders outside the editor's size container. */
	.recipe-groups {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr));
		gap: 1rem;
	}

	.recipe-group {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
		min-width: 0;
	}

	.group-title {
		margin: 0;
		font-family: var(--font-display);
		font-size: 0.72rem;
		color: var(--primary);
		text-transform: uppercase;
		letter-spacing: 1px;
	}

	.group-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 0.55rem;
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}

	.field span {
		font-size: var(--label-font-size);
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.field .hint {
		text-transform: none;
		letter-spacing: 0;
		opacity: 0.7;
	}

	.reference-section {
		display: flex;
		align-items: center;
		gap: 0.55rem;
	}

	.ref-label {
		font-size: var(--label-font-size);
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.ref-active {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: 0.75rem;
		color: var(--text-light);
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 0.15rem 0.4rem;
	}

	.ref-clear {
		background: none;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
	}

	.ref-upload {
		font-size: 0.7rem;
		color: var(--text-muted);
		cursor: pointer;
	}

	.ref-upload input[type='file'] {
		display: none;
	}

	.recipe-footer-hint {
		margin: 0;
		text-align: right;
		font-size: 0.7rem;
		color: var(--text-subtle);
	}
</style>
