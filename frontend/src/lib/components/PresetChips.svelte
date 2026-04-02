<script lang="ts">
	import { userPresets, sharedPresets, activeModelIds } from '$lib/stores/presets';
	import type { VersionGenerationParams } from '$lib/api/types';

	interface Props {
		hasOverrides: boolean;
		onload: (params: VersionGenerationParams) => void;
		onreset: () => void;
		selectedModel?: string | null;
	}

	let { hasOverrides, onload, onreset, selectedModel = null }: Props = $props();

	const filteredUserPresets = $derived(
		selectedModel
			? $userPresets.filter((p) => p.model_mode === selectedModel)
			: $userPresets
	);
	const filteredSharedPresets = $derived(
		selectedModel
			? $sharedPresets.filter((p) => p.model_mode === selectedModel)
			: $sharedPresets
	);
</script>

<div class="presets-row">
	<button
		class="preset-chip inherit"
		class:active={!hasOverrides}
		onclick={onreset}
		title="Use global defaults"
	>
		Inherit
	</button>
	{#each filteredUserPresets as preset (preset.id)}
		{@const unavailable = !$activeModelIds.has(preset.model_mode)}
		<button
			class="preset-chip"
			class:is-default={preset.is_default}
			class:unavailable
			onclick={() => onload({ ...preset.params })}
			title={unavailable
				? `Model "${preset.model_mode}" not available`
				: `My preset: ${preset.name}`}
		>
			{preset.name}
			<span class="preset-mode-tag">{preset.model_mode}</span>
		</button>
	{/each}
	{#each filteredSharedPresets as preset (preset.id)}
		{@const unavailable = !$activeModelIds.has(preset.model_mode)}
		<button
			class="preset-chip shared"
			class:unavailable
			onclick={() => onload({ ...preset.params })}
			title={unavailable ? `Model "${preset.model_mode}" not available` : `Shared: ${preset.name}`}
		>
			{preset.name}
			<span class="preset-mode-tag">{preset.model_mode}</span>
		</button>
	{/each}
</div>

<style>
	.presets-row {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-wrap: wrap;
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
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.preset-chip:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.preset-chip.inherit {
		border-style: dashed;
	}

	.preset-chip.inherit.active {
		border-color: var(--score-ok);
		color: var(--score-ok);
		border-style: solid;
	}

	.preset-chip.is-default {
		border-color: var(--primary);
		color: var(--primary);
	}

	.preset-chip.shared {
		border-style: dotted;
	}

	.preset-chip.unavailable {
		opacity: 0.4;
		text-decoration: line-through;
	}

	.preset-mode-tag {
		font-size: 8px;
		opacity: 0.6;
		margin-left: 2px;
	}
</style>
