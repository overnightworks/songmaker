<script lang="ts">
	import { userPresets, sharedPresets, builtinDefaults } from '$lib/stores/presets';
	import type { VersionGenerationParams } from '$lib/api/types';

	interface Props {
		hasOverrides: boolean;
		onload: (params: VersionGenerationParams) => void;
		onreset: () => void;
	}

	let { hasOverrides, onload, onreset }: Props = $props();

	const builtinModes = $derived(Object.entries($builtinDefaults));
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
	{#each builtinModes as [mode, params] (mode)}
		<button
			class="preset-chip builtin"
			onclick={() => onload({ ...params })}
			title="{mode} defaults"
		>
			{mode.toUpperCase()}
		</button>
	{/each}
	{#each $userPresets as preset (preset.id)}
		<button
			class="preset-chip"
			class:is-default={preset.is_default}
			onclick={() => onload({ ...preset.params })}
			title="My preset: {preset.name}"
		>
			{preset.name}
			<span class="preset-mode-tag">{preset.model_mode}</span>
		</button>
	{/each}
	{#if $sharedPresets.length > 0}
		{#each $sharedPresets as preset (preset.id)}
			<button
				class="preset-chip shared"
				onclick={() => onload({ ...preset.params })}
				title="Shared preset: {preset.name}"
			>
				{preset.name}
				<span class="preset-mode-tag">{preset.model_mode}</span>
			</button>
		{/each}
	{/if}
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

	.preset-chip.builtin {
		border-color: var(--accent);
		color: var(--accent);
	}

	.preset-chip.builtin:hover {
		background: color-mix(in srgb, var(--accent) 10%, transparent);
	}

	.preset-chip.is-default {
		border-color: var(--primary);
		color: var(--primary);
	}

	.preset-chip.shared {
		border-style: dotted;
	}

	.preset-mode-tag {
		font-size: 8px;
		opacity: 0.6;
		margin-left: 2px;
	}
</style>
