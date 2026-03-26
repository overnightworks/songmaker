<script lang="ts">
	import type { Snippet } from 'svelte';
	import { presets, savePreset, setDefault, deletePreset } from '$lib/stores/presets';
	import type { VersionGenerationParams } from '$lib/api/types';

	interface Props {
		hasOverrides: boolean;
		currentParams: VersionGenerationParams;
		onload: (params: VersionGenerationParams) => void;
		onreset: () => void;
		onopendefaults: () => void;
		children?: Snippet;
	}

	let { hasOverrides, currentParams, onload, onreset, onopendefaults, children }: Props = $props();

	let showSavePreset = $state(false);
	let presetName = $state('');
	let presetModel = $state<'turbo' | 'sft'>('turbo');
	let presetAsDefault = $state(false);
	let savingPreset = $state(false);

	function loadPresetParams(presetId: string): void {
		const preset = $presets.find((p) => p.id === presetId);
		if (preset) onload({ ...preset.params });
	}

	async function handleSavePreset(): Promise<void> {
		if (!presetName.trim()) return;
		savingPreset = true;
		try {
			await savePreset(presetName.trim(), presetModel, currentParams, presetAsDefault);
			showSavePreset = false;
			presetName = '';
			presetModel = 'turbo';
			presetAsDefault = false;
		} catch {
			/* save failed */
		} finally {
			savingPreset = false;
		}
	}

	async function handleSetDefault(presetId: string): Promise<void> {
		try {
			await setDefault(presetId);
		} catch {
			/* failed */
		}
	}

	async function handleDeletePreset(presetId: string): Promise<void> {
		try {
			await deletePreset(presetId);
		} catch {
			/* failed */
		}
	}
</script>

{#if $presets.length > 0}
	<div class="presets-row">
		<span class="presets-label">Presets:</span>
		{#each $presets as preset (preset.id)}
			<button
				class="preset-chip"
				class:is-default={preset.is_default}
				onclick={() => loadPresetParams(preset.id)}
				title="{preset.model_mode} preset"
			>
				{preset.name}
				<span class="preset-mode-tag">{preset.model_mode}</span>
			</button>
		{/each}
	</div>
{/if}

{#if children}
	{@render children()}
{/if}

<div class="actions-row">
	{#if hasOverrides}
		<button class="action-btn" onclick={onreset}>Reset to defaults</button>
		<button class="action-btn" onclick={() => (showSavePreset = true)}>Save as preset</button>
	{/if}
	<button class="action-btn" onclick={onopendefaults}>Edit global defaults</button>
</div>

{#if showSavePreset}
	<div class="panel">
		<div class="panel-header">
			<span>Save Preset</span>
		</div>
		<div class="save-preset-form">
			<input
				type="text"
				placeholder="Preset name"
				bind:value={presetName}
				class="preset-name-input"
			/>
			<select class="model-select" bind:value={presetModel}>
				<option value="turbo">Turbo</option>
				<option value="sft">SFT</option>
			</select>
			<label class="preset-default-label">
				<input type="checkbox" bind:checked={presetAsDefault} />
				<span>Set as default</span>
			</label>
		</div>
		<div class="actions-row">
			<button
				class="save-btn"
				onclick={handleSavePreset}
				disabled={savingPreset || !presetName.trim()}
			>
				{savingPreset ? 'Saving...' : 'Save'}
			</button>
			<button class="action-btn" onclick={() => (showSavePreset = false)}>Cancel</button>
		</div>
	</div>
{/if}

{#if $presets.length > 0}
	<div class="panel">
		<div class="panel-header">
			<span>Saved Presets</span>
		</div>
		<div class="preset-list">
			{#each $presets as preset (preset.id)}
				<div class="preset-row">
					<span class="preset-name">{preset.name}</span>
					<span class="preset-mode-tag">{preset.model_mode}</span>
					{#if !preset.is_default}
						<button
							class="preset-action"
							onclick={() => handleSetDefault(preset.id)}
							title="Set as default"
						>
							set default
						</button>
					{:else}
						<span class="preset-default-tag">default</span>
					{/if}
					<button
						class="preset-action delete"
						onclick={() => handleDeletePreset(preset.id)}
						title="Delete preset"
					>
						delete
					</button>
				</div>
			{/each}
		</div>
	</div>
{/if}

<style>
	.presets-row {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-wrap: wrap;
	}

	.presets-label {
		font-size: 10px;
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
	}

	.preset-chip {
		padding: 2px 8px;
		border: 1px solid var(--border);
		border-radius: 3px;
		background: transparent;
		color: var(--text-muted);
		font-size: 10px;
		cursor: pointer;
		font-family: var(--font-display);
	}

	.preset-chip:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.preset-chip.is-default {
		border-color: var(--primary);
		color: var(--primary);
	}

	.preset-mode-tag {
		font-size: 8px;
		opacity: 0.6;
		text-transform: uppercase;
		margin-left: 2px;
	}

	.actions-row {
		display: flex;
		gap: 8px;
	}

	.action-btn {
		padding: 3px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: transparent;
		color: var(--text-muted);
		font-size: 10px;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.action-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.panel {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 10px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
	}

	.panel-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.panel-header span {
		font-size: 10px;
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 1px;
	}

	.save-btn {
		padding: 3px 10px;
		border: 1px solid var(--primary);
		border-radius: 4px;
		background: var(--primary);
		color: #fff;
		font-size: 10px;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.save-btn:disabled {
		opacity: 0.4;
	}

	.model-select {
		padding: 5px 8px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 12px;
	}

	.model-select:focus {
		border-color: var(--primary);
		outline: none;
	}

	.save-preset-form {
		display: flex;
		gap: 8px;
		align-items: center;
	}

	.preset-name-input {
		padding: 5px 8px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 12px;
		flex: 1;
	}

	.preset-name-input:focus {
		border-color: var(--primary);
		outline: none;
	}

	.preset-default-label {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: 10px;
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
		gap: 8px;
		padding: 4px 0;
	}

	.preset-name {
		flex: 1;
		font-size: 12px;
		color: var(--text);
	}

	.preset-default-tag {
		font-size: 9px;
		padding: 1px 5px;
		border-radius: 3px;
		background: var(--primary);
		color: #fff;
		letter-spacing: 0.5px;
	}

	.preset-action {
		padding: 1px 6px;
		border: 1px solid var(--border);
		border-radius: 3px;
		background: transparent;
		color: var(--text-muted);
		font-size: 9px;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
	}

	.preset-action:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.preset-action.delete:hover {
		border-color: var(--danger, #e74c3c);
		color: var(--danger, #e74c3c);
	}
</style>
