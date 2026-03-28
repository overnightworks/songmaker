<script lang="ts">
	import { onMount } from 'svelte';
	import { isAdmin } from '$lib/stores/auth';
	import {
		presets,
		loadPresets,
		loadBuiltins,
		builtinDefaults,
		savePreset,
		setDefault,
		deletePreset
	} from '$lib/stores/presets';
	import { fetchGenerationDefaults, updateGenerationDefaults } from '$lib/api/client';
	import type { VersionGenerationParams } from '$lib/api/types';
	import ParamControls from '$lib/components/ParamControls.svelte';

	const admin = $derived($isAdmin);

	let globalDefaults = $state<Record<string, VersionGenerationParams>>({});
	let editModel = $state('');
	let editDefaults = $state<VersionGenerationParams>({});
	let saving = $state(false);
	let error = $state('');

	let showSavePreset = $state(false);
	let presetName = $state('');
	let presetModel = $state('');
	let presetParams = $state<VersionGenerationParams>({});
	let presetAsDefault = $state(false);
	let savingPreset = $state(false);

	const modelModes = $derived(Object.keys($builtinDefaults));

	onMount(async () => {
		await Promise.all([
			loadBuiltins(),
			loadPresets(),
			fetchGenerationDefaults()
				.then((d) => {
					globalDefaults = d;
				})
				.catch(() => {})
		]);
		const modes = Object.keys($builtinDefaults);
		if (modes.length > 0) {
			editModel = modes[0];
			presetModel = modes[0];
			editDefaults = { ...(globalDefaults[modes[0]] ?? {}) };
		}
	});

	function switchModel(model: string): void {
		editModel = model;
		editDefaults = { ...(globalDefaults[model] ?? {}) };
	}

	async function handleSaveDefaults(): Promise<void> {
		saving = true;
		error = '';
		try {
			const cleaned = Object.keys(editDefaults).length > 0 ? editDefaults : {};
			globalDefaults = await updateGenerationDefaults({ ...globalDefaults, [editModel]: cleaned });
			editDefaults = { ...(globalDefaults[editModel] ?? {}) };
		} catch {
			error = 'Failed to save defaults';
		} finally {
			saving = false;
		}
	}

	function handleResetDefaults(): void {
		editDefaults = { ...(globalDefaults[editModel] ?? {}) };
	}

	async function handleSavePreset(): Promise<void> {
		if (!presetName.trim()) return;
		savingPreset = true;
		try {
			await savePreset(presetName.trim(), presetModel, presetParams, presetAsDefault);
			showSavePreset = false;
			presetName = '';
			presetModel = modelModes[0] ?? '';
			presetParams = {};
			presetAsDefault = false;
		} catch {
			error = 'Failed to save preset';
		} finally {
			savingPreset = false;
		}
	}

	async function handleSetDefault(presetId: string): Promise<void> {
		try {
			await setDefault(presetId);
		} catch {
			error = 'Failed to set default';
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

{#if !admin}
	<div class="denied">Admin access required.</div>
{:else}
	<div class="page">
		<h1>Generation</h1>

		{#if error}
			<p class="error">{error}</p>
		{/if}

		<section>
			<h2>Global Defaults</h2>
			<p class="hint">
				Default generation parameters applied to all new songs. Per-song overrides take precedence.
			</p>

			<div class="model-tabs">
				{#each modelModes as mode (mode)}
					<button
						class="model-tab"
						class:active={editModel === mode}
						onclick={() => switchModel(mode)}
					>
						{mode.toUpperCase()}
					</button>
				{/each}
			</div>

			<div class="defaults-controls">
				<ParamControls
					values={editDefaults}
					placeholders={($builtinDefaults[editModel] ?? {}) as Required<VersionGenerationParams>}
					onchange={(p) => (editDefaults = p)}
				/>
			</div>

			<div class="actions-row">
				<button class="save-btn" onclick={handleSaveDefaults} disabled={saving}>
					{saving ? 'Saving...' : 'Save Defaults'}
				</button>
				<button class="reset-btn" onclick={handleResetDefaults}>Reset</button>
			</div>
		</section>

		<section>
			<div class="section-header">
				<h2>Presets</h2>
				<button class="add-btn" onclick={() => (showSavePreset = true)}>New Preset</button>
			</div>

			{#if showSavePreset}
				<div class="panel">
					<div class="save-preset-form">
						<input
							type="text"
							placeholder="Preset name"
							bind:value={presetName}
							class="preset-name-input"
						/>
						<select class="model-select" bind:value={presetModel}>
							{#each modelModes as mode (mode)}
								<option value={mode}>{mode.toUpperCase()}</option>
							{/each}
						</select>
						<label class="preset-default-label">
							<input type="checkbox" bind:checked={presetAsDefault} />
							<span>Set as default</span>
						</label>
					</div>
					<ParamControls
						values={presetParams}
						placeholders={($builtinDefaults[presetModel] ??
							{}) as Required<VersionGenerationParams>}
						onchange={(p) => (presetParams = p)}
					/>
					<div class="actions-row">
						<button
							class="save-btn"
							onclick={handleSavePreset}
							disabled={savingPreset || !presetName.trim()}
						>
							{savingPreset ? 'Saving...' : 'Save'}
						</button>
						<button class="reset-btn" onclick={() => (showSavePreset = false)}>Cancel</button>
					</div>
				</div>
			{/if}

			{#if $presets.length > 0}
				<div class="preset-list">
					{#each $presets as preset (preset.id)}
						<div class="preset-row">
							<span class="preset-name">{preset.name}</span>
							<span class="preset-mode-tag">{preset.model_mode}</span>
							{#if preset.is_default}
								<span class="preset-default-tag">default</span>
							{:else}
								<button class="preset-action" onclick={() => handleSetDefault(preset.id)}>
									set default
								</button>
							{/if}
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
	</div>
{/if}

<style>
	.page {
		padding: 2rem;
		max-width: 700px;
	}

	.denied {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		color: var(--text-muted);
		font-size: 1.1rem;
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

	.model-tabs {
		display: flex;
		gap: 4px;
		margin-bottom: 1rem;
	}

	.model-tab {
		padding: 0.4rem 1rem;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: transparent;
		color: var(--text-muted);
		font-size: 0.85rem;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.model-tab.active {
		border-color: var(--primary);
		color: var(--primary);
	}

	.defaults-controls {
		margin-bottom: 1rem;
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
		border-radius: 4px;
		padding: 0.5rem 1.2rem;
		font-size: 0.85rem;
		cursor: pointer;
		font-family: var(--font-body);
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
		padding: 0.35rem 0.8rem;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: transparent;
		color: var(--text-muted);
		font-size: 0.8rem;
		cursor: pointer;
		font-family: var(--font-body);
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
		border-radius: 4px;
		margin-bottom: 1rem;
	}

	.save-preset-form {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		flex-wrap: wrap;
	}

	.preset-name-input {
		padding: 0.4rem 0.6rem;
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
		padding: 0.4rem 0.6rem;
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

	.preset-default-label {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: 0.8rem;
		color: var(--text-muted);
		cursor: pointer;
		white-space: nowrap;
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
		background: var(--primary);
		color: #fff;
		letter-spacing: 0.5px;
	}

	.preset-action {
		padding: 2px 8px;
		border: 1px solid var(--border);
		border-radius: 3px;
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
