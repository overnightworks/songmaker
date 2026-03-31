<script lang="ts">
	import { onMount } from 'svelte';
	import {
		presets,
		userPresets,
		sharedPresets,
		loadPresets,
		loadBuiltins,
		loadActiveModels,
		activeModels,
		activeModelIds,
		builtinDefaults,
		defaultConfig,
		loadDefaultConfig,
		saveDefaultConfig,
		savePreset,
		updateExistingPreset,
		setDefault,
		unsetDefault,
		deletePreset
	} from '$lib/stores/presets';
	import { fetchGenerationDefaults } from '$lib/api/client';
	import type { VersionGenerationParams } from '$lib/api/types';
	import ParamControls from '$lib/components/ParamControls.svelte';

	let globalDefaults = $state<Record<string, VersionGenerationParams>>({});
	const activeIds = $derived($activeModelIds);
	let error = $state('');

	let showPresetForm = $state(false);
	let editingPresetId = $state<string | null>(null);
	let presetName = $state('');
	let presetModel = $state('');
	let presetParams = $state<VersionGenerationParams>({});
	let presetAsDefault = $state(false);
	let savingPreset = $state(false);

	const modelModes = $derived($activeModels.map((m) => m.id));

	function fullParams(mode: string, overrides: VersionGenerationParams): VersionGenerationParams {
		const builtin = $builtinDefaults[mode] ?? {};
		const global = globalDefaults[mode] ?? {};
		return { ...builtin, ...global, ...overrides };
	}

	onMount(async () => {
		await Promise.all([
			loadBuiltins(),
			loadPresets(),
			loadActiveModels(),
			loadDefaultConfig(),
			fetchGenerationDefaults()
				.then((d) => {
					globalDefaults = d;
				})
				.catch(() => {})
		]);
		if (modelModes.length > 0) {
			presetModel = modelModes[0];
		}
	});

	async function handleSetDefaultConfig(config: string | null): Promise<void> {
		try {
			await saveDefaultConfig(config);
		} catch {
			error = 'Failed to set default config';
		}
	}

	function openNewPreset(): void {
		editingPresetId = null;
		presetName = '';
		presetModel = modelModes[0] ?? '';
		presetParams = {};
		presetAsDefault = false;
		showPresetForm = true;
	}

	function openEditPreset(presetId: string): void {
		const preset = $presets.find((p) => p.id === presetId);
		if (!preset) return;
		editingPresetId = preset.id;
		presetName = preset.name;
		presetModel = preset.model_mode;
		presetParams = { ...preset.params };
		presetAsDefault = preset.is_default;
		showPresetForm = true;
	}

	function closePresetForm(): void {
		showPresetForm = false;
		editingPresetId = null;
	}

	async function handleSavePreset(): Promise<void> {
		if (!presetName.trim()) return;
		savingPreset = true;
		try {
			const merged = fullParams(presetModel, presetParams);
			if (editingPresetId) {
				await updateExistingPreset(editingPresetId, {
					name: presetName.trim(),
					params: merged,
					is_default: presetAsDefault
				});
			} else {
				await savePreset(presetName.trim(), presetModel, merged, presetAsDefault);
			}
			closePresetForm();
		} catch {
			error = editingPresetId ? 'Failed to update preset' : 'Failed to save preset';
		} finally {
			savingPreset = false;
		}
	}

	async function handleToggleDefault(presetId: string, isDefault: boolean): Promise<void> {
		try {
			if (isDefault) {
				await unsetDefault(presetId);
			} else {
				await setDefault(presetId);
			}
		} catch {
			error = 'Failed to update default';
		}
	}

	async function handleDeletePreset(presetId: string): Promise<void> {
		try {
			await deletePreset(presetId);
		} catch {
			error = 'Failed to delete preset';
		}
	}
</script>

<div class="page">
	<h1>Generation</h1>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	<section>
		<h2>Default for New Songs</h2>
		<p class="hint">When you create a song, this config is applied automatically.</p>
		<div class="default-chips">
			<button
				class="default-chip"
				class:active={$defaultConfig === null}
				onclick={() => handleSetDefaultConfig(null)}
			>
				Inherit
			</button>
			{#each $userPresets as preset (preset.id)}
				<button
					class="default-chip"
					class:active={$defaultConfig === preset.id}
					class:unavailable={!activeIds.has(preset.model_mode)}
					onclick={() => handleSetDefaultConfig(preset.id)}
				>
					{preset.name}
				</button>
			{/each}
			{#each $sharedPresets as preset (preset.id)}
				<button
					class="default-chip shared"
					class:active={$defaultConfig === preset.id}
					class:unavailable={!activeIds.has(preset.model_mode)}
					onclick={() => handleSetDefaultConfig(preset.id)}
				>
					{preset.name}
				</button>
			{/each}
		</div>
	</section>

	<section>
		<div class="section-header">
			<h2>My Presets</h2>
			<button class="add-btn" onclick={openNewPreset}>New Preset</button>
		</div>

		{#if showPresetForm}
			<div class="panel">
				<div class="save-preset-form">
					<input
						type="text"
						placeholder="Preset name"
						bind:value={presetName}
						class="preset-name-input"
					/>
					{#if !editingPresetId}
						<select class="model-select" bind:value={presetModel}>
							{#each modelModes as mode (mode)}
								<option value={mode}>{mode.toUpperCase()}</option>
							{/each}
						</select>
					{:else}
						<span class="model-badge">{presetModel.toUpperCase()}</span>
					{/if}
				</div>
				<ParamControls
					values={presetParams}
					placeholders={($builtinDefaults[presetModel] ?? {}) as Required<VersionGenerationParams>}
					onchange={(p) => (presetParams = p)}
				/>
				<div class="actions-row">
					<button
						class="save-btn"
						onclick={handleSavePreset}
						disabled={savingPreset || !presetName.trim()}
					>
						{savingPreset ? 'Saving...' : editingPresetId ? 'Update' : 'Save'}
					</button>
					<button class="reset-btn" onclick={closePresetForm}>Cancel</button>
				</div>
			</div>
		{/if}

		{#if $userPresets.length > 0}
			<div class="preset-list">
				{#each $userPresets as preset (preset.id)}
					<div class="preset-row">
						<span class="preset-name">{preset.name}</span>
						<span class="preset-mode-tag">{preset.model_mode}</span>
						<button
							class="preset-action"
							onclick={() => handleToggleDefault(preset.id, preset.is_default)}
						>
							{preset.is_default ? 'unset default' : 'set default'}
						</button>
						<button class="preset-action" onclick={() => openEditPreset(preset.id)}> edit </button>
						<button class="preset-action delete" onclick={() => handleDeletePreset(preset.id)}>
							delete
						</button>
					</div>
				{/each}
			</div>
		{:else}
			<p class="empty">No presets saved yet.</p>
		{/if}
	</section>

	{#if $sharedPresets.length > 0}
		<section>
			<h2>Shared Presets</h2>
			<div class="preset-list">
				{#each $sharedPresets as preset (preset.id)}
					<div class="preset-row">
						<span class="preset-name">{preset.name}</span>
						<span class="preset-mode-tag">{preset.model_mode}</span>
						{#if preset.is_default}
							<span class="preset-default-tag">default</span>
						{/if}
					</div>
				{/each}
			</div>
		</section>
	{/if}
</div>

<style>
	.page {
		padding: 2rem;
		max-width: 700px;
	}

	h1 {
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.1em;
		background: linear-gradient(90deg, var(--primary), var(--accent));
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
		font-size: 1.5rem;
		margin-bottom: 1.5rem;
	}

	h2 {
		font-size: 1rem;
		color: var(--text-muted);
		margin-bottom: 0.5rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.hint {
		color: var(--text-dim);
		font-size: 0.85rem;
		margin-bottom: 1rem;
	}

	.error {
		color: var(--score-bad);
		font-size: 0.85rem;
		margin-bottom: 1rem;
	}

	section {
		margin-bottom: 2rem;
	}

	.default-chips {
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
	}

	.default-chip {
		padding: 0.4rem 0.8rem;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: transparent;
		color: var(--text-muted);
		font-size: 0.8rem;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.default-chip:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.default-chip.active {
		border-color: transparent;
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: #fff;
	}

	.default-chip.shared {
		border-style: dotted;
	}

	.default-chip.unavailable {
		opacity: 0.4;
		text-decoration: line-through;
	}

	.actions-row {
		display: flex;
		gap: 0.5rem;
	}

	.save-btn {
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: white;
		border: none;
		border-radius: 16px;
		padding: 0.5rem 1.2rem;
		font-size: 0.85rem;
		font-weight: 600;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		transition: box-shadow 0.2s;
	}

	.save-btn:hover:not(:disabled) {
		box-shadow: 0 0 16px rgba(160, 32, 240, 0.3);
	}

	.save-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.reset-btn {
		background: transparent;
		color: var(--text-muted);
		border: 1px solid var(--border);
		border-radius: 16px;
		padding: 0.5rem 1.2rem;
		font-size: 0.85rem;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.reset-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.section-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 0.75rem;
	}

	.section-header h2 {
		margin-bottom: 0;
	}

	.add-btn {
		padding: 3px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: transparent;
		color: var(--text-muted);
		font-size: 0.75rem;
		cursor: pointer;
		font-family: var(--font-display);
	}

	.add-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.panel {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		padding: 1rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 6px;
		margin-bottom: 1rem;
	}

	.save-preset-form {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		flex-wrap: wrap;
	}

	.preset-name-input {
		padding: 0.5rem 0.7rem;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 0.85rem;
		flex: 1;
		min-width: 150px;
		font-family: var(--font-body);
	}

	.preset-name-input:focus {
		border-color: var(--accent);
		outline: none;
		box-shadow: 0 0 8px rgba(160, 32, 240, 0.2);
	}

	.model-select {
		padding: 0.5rem 0.7rem;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 0.85rem;
		font-family: var(--font-body);
	}

	.model-select:focus {
		border-color: var(--accent);
		outline: none;
		box-shadow: 0 0 8px rgba(160, 32, 240, 0.2);
	}

	.model-badge {
		padding: 0.3rem 0.6rem;
		border: 1px solid var(--accent);
		border-radius: 4px;
		color: var(--accent);
		font-size: 0.8rem;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.preset-list {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.preset-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.5rem 0.75rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
	}

	.preset-name {
		flex: 1;
		font-size: 0.9rem;
		color: var(--text);
	}

	.preset-mode-tag {
		font-size: 0.7rem;
		color: var(--text-dim);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.preset-default-tag {
		font-size: 0.7rem;
		padding: 1px 6px;
		border-radius: 3px;
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: #fff;
		letter-spacing: 0.5px;
	}

	.preset-action {
		padding: 3px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: transparent;
		color: var(--text-muted);
		font-size: 0.75rem;
		cursor: pointer;
		font-family: var(--font-body);
	}

	.preset-action:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.preset-action.delete:hover {
		border-color: var(--score-bad);
		color: var(--score-bad);
	}

	.empty {
		color: var(--text-dim);
		font-size: 0.85rem;
	}
</style>
