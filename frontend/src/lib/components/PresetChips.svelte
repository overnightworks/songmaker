<script lang="ts">
	import { presets } from '$lib/stores/presets';
	import type { VersionGenerationParams } from '$lib/api/types';

	interface Props {
		hasOverrides: boolean;
		onload: (params: VersionGenerationParams) => void;
		onreset: () => void;
	}

	let { hasOverrides, onload, onreset }: Props = $props();

	function loadPresetParams(presetId: string): void {
		const preset = $presets.find((p) => p.id === presetId);
		if (preset) onload({ ...preset.params });
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

{#if hasOverrides}
	<div class="actions-row">
		<button class="action-btn" onclick={onreset}>Reset to defaults</button>
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
</style>
