<script lang="ts">
	import { onMount } from 'svelte';
	import { editGenParams, setDraftGenParams } from '$lib/stores/editor';
	import {
		loadPresets,
		loadBuiltins,
		loadActiveModels,
		activeModels,
		builtinDefaults
	} from '$lib/stores/presets';
	import { fetchGenerationDefaults, uploadReferenceAudio } from '$lib/api/client';
	import type { VersionGenerationParams } from '$lib/api/types';
	import { addToast } from '$lib/stores/toast';
	import ParamControls from './ParamControls.svelte';
	import PresetChips from './PresetChips.svelte';

	interface Props {
		selectedModel?: string | null;
	}

	let { selectedModel = null }: Props = $props();

	let globalDefaults = $state<Record<string, VersionGenerationParams>>({});

	const activeMode = $derived(
		selectedModel ?? $activeModels[0]?.id ?? Object.keys($builtinDefaults)[0] ?? ''
	);

	const activeModelData = $derived($activeModels.find((m) => m.id === activeMode));

	const hiddenParams = $derived(activeModelData?.capabilities?.hidden_params ?? []);
	const maxInferenceSteps = $derived(activeModelData?.capabilities?.max_inference_steps ?? 200);

	const effectiveDefaults = $derived.by((): Required<VersionGenerationParams> => {
		const builtin = activeMode ? ($builtinDefaults[activeMode] ?? {}) : {};
		const global = activeMode ? (globalDefaults[activeMode] ?? {}) : {};
		return { ...builtin, ...global } as Required<VersionGenerationParams>;
	});

	const hasOverrides = $derived(
		$editGenParams !== null && Object.keys($editGenParams ?? {}).length > 0
	);

	const referenceAudioPath = $derived(($editGenParams ?? {}).reference_audio ?? null);
	let referenceFilename = $state<string | null>(null);
	let uploading = $state(false);

	async function handleReferenceUpload(e: Event): Promise<void> {
		const input = e.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		uploading = true;
		try {
			const result = await uploadReferenceAudio(file);
			setDraftGenParams({ ...($editGenParams ?? {}), reference_audio: result.path });
			referenceFilename = result.filename;
		} catch (err) {
			addToast(err instanceof Error ? err.message : 'Upload failed', 'error');
		} finally {
			uploading = false;
			input.value = '';
		}
	}

	function clearReference(): void {
		const { reference_audio: _, ...rest } = $editGenParams ?? {};
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
			{selectedModel}
			onload={(p) => setDraftGenParams({ ...p })}
			onreset={() => setDraftGenParams(null)}
		/>

		<ParamControls
			values={$editGenParams ?? {}}
			placeholders={effectiveDefaults}
			onchange={(p) => setDraftGenParams(Object.keys(p).length > 0 ? p : null)}
			{hiddenParams}
			{maxInferenceSteps}
		/>

		<div class="reference-section">
			<span class="ref-label">Reference Track</span>
			{#if referenceAudioPath}
				<div class="ref-active">
					<span class="ref-name">{referenceFilename ?? referenceAudioPath}</span>
					<button class="ref-clear" onclick={clearReference}>x</button>
				</div>
			{:else}
				<label class="ref-upload">
					<input
						type="file"
						accept=".mp3,.wav,.flac,.ogg"
						onchange={handleReferenceUpload}
						disabled={uploading}
					/>
					{uploading ? 'Uploading...' : 'Upload audio'}
				</label>
			{/if}
		</div>
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

	.reference-section {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.ref-label {
		font-size: 10px;
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
		white-space: nowrap;
	}

	.ref-active {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: 11px;
		color: var(--text-light);
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 2px 6px;
	}

	.ref-name {
		max-width: 150px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.ref-clear {
		background: none;
		border: none;
		color: var(--text-muted);
		cursor: pointer;
		font-size: 12px;
		padding: 0 2px;
	}

	.ref-upload {
		font-size: 10px;
		color: var(--text-muted);
		cursor: pointer;
	}

	.ref-upload input[type='file'] {
		display: none;
	}

	.ref-upload:hover {
		color: var(--primary);
	}
</style>
