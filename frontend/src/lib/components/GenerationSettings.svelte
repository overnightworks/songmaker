<script lang="ts">
	import { onMount } from 'svelte';
	import { editGenParams } from '$lib/stores/editor';
	import { loadPresets, loadBuiltins, builtinDefaults } from '$lib/stores/presets';
	import { fetchGenerationDefaults } from '$lib/api/client';
	import type { VersionGenerationParams } from '$lib/api/types';
	import { FALLBACK_DEFAULTS } from '$lib/defaults';
	import ParamControls from './ParamControls.svelte';
	import PresetChips from './PresetChips.svelte';

	let open = $state(false);
	let globalDefaults = $state<Record<string, VersionGenerationParams>>({});

	const builtins = $derived.by((): Record<string, Required<VersionGenerationParams>> => {
		const b = $builtinDefaults;
		return {
			turbo: {
				...FALLBACK_DEFAULTS.turbo,
				...(b.turbo ?? {})
			} as Required<VersionGenerationParams>,
			sft: {
				...FALLBACK_DEFAULTS.sft,
				...(b.sft ?? {})
			} as Required<VersionGenerationParams>
		};
	});

	const effectiveDefaults = $derived.by((): Required<VersionGenerationParams> => {
		return {
			...builtins.turbo,
			...(globalDefaults.turbo ?? {})
		} as Required<VersionGenerationParams>;
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

<div class="gen-settings">
	<button class="toggle" onclick={() => (open = !open)} aria-expanded={open}>
		<span class="toggle-icon">{open ? '▾' : '▸'}</span>
		<span>Generation Settings</span>
		{#if hasOverrides}
			<span class="override-badge">custom</span>
		{/if}
	</button>

	{#if open}
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
	{/if}
</div>

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
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		font-size: 10px;
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 1px;
	}

	.toggle:hover {
		color: var(--text);
	}

	.toggle-icon {
		font-size: 10px;
		width: 10px;
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
