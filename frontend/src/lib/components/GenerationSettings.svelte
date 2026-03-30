<script lang="ts">
	import { onMount } from 'svelte';
	import { editGenParams } from '$lib/stores/editor';
	import { loadPresets, loadBuiltins, builtinDefaults } from '$lib/stores/presets';
	import { fetchGenerationDefaults } from '$lib/api/client';
	import type { VersionGenerationParams } from '$lib/api/types';
	import ParamControls from './ParamControls.svelte';
	import PresetChips from './PresetChips.svelte';

	let globalDefaults = $state<Record<string, VersionGenerationParams>>({});

	const firstMode = $derived(Object.keys($builtinDefaults)[0] ?? '');

	const effectiveDefaults = $derived.by((): Required<VersionGenerationParams> => {
		const builtin = firstMode ? ($builtinDefaults[firstMode] ?? {}) : {};
		const global = firstMode ? (globalDefaults[firstMode] ?? {}) : {};
		return { ...builtin, ...global } as Required<VersionGenerationParams>;
	});

	const hasOverrides = $derived(
		$editGenParams !== null && Object.keys($editGenParams ?? {}).length > 0
	);

	onMount(async () => {
		await Promise.all([
			loadBuiltins(),
			loadPresets(),
			fetchGenerationDefaults()
				.then((d) => (globalDefaults = d))
				.catch(() => {})
		]);
	});
</script>

<details class="gen-settings">
	<summary class="toggle">
		Generation Settings
		{#if hasOverrides}
			<span class="override-badge">custom</span>
		{/if}
	</summary>

	<div class="settings-body">
		<PresetChips
			{hasOverrides}
			onload={(p) => ($editGenParams = { ...p })}
			onreset={() => ($editGenParams = null)}
		/>

		<ParamControls
			values={$editGenParams ?? {}}
			placeholders={effectiveDefaults}
			onchange={(p) => ($editGenParams = Object.keys(p).length > 0 ? p : null)}
		/>
	</div>
</details>

<style>
	.gen-settings {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.toggle {
		display: flex;
		align-items: center;
		gap: 6px;
		cursor: pointer;
		font-size: 10px;
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 1px;
		list-style: disclosure-closed;
	}

	.gen-settings[open] > .toggle {
		list-style: disclosure-open;
	}

	.toggle:hover {
		color: var(--text);
	}

	.toggle::marker {
		color: var(--text-muted);
		font-size: 10px;
	}

	.toggle:hover::marker {
		color: var(--text);
	}

	.settings-body {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.override-badge {
		font-size: 9px;
		padding: 1px 5px;
		border-radius: 3px;
		background: var(--primary);
		color: #fff;
		letter-spacing: 0.5px;
	}
</style>
