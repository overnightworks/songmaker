<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { onMount } from 'svelte';
	import { editGenParams, setDraftGenParams } from '$lib/stores/editor';
	import { loras, loadLoras, isLoraActive } from '$lib/stores/loras';
	import type { VersionGenerationParams } from '$lib/api/types';

	const NONE_VALUE = '__none__';

	const available = $derived(($loras ?? []).filter((l) => l.deleted_at === null));

	const current = $derived(($editGenParams ?? {}).user_lora_id ?? null);

	function setChoice(value: string) {
		const next = value === NONE_VALUE ? null : value;
		const rest: VersionGenerationParams = { ...($editGenParams ?? {}) };
		if (next === null) {
			delete rest.user_lora_id;
		} else {
			rest.user_lora_id = next;
		}
		setDraftGenParams(Object.keys(rest).length > 0 ? rest : null);
	}

	onMount(() => {
		if ($loras.length === 0) {
			loadLoras().catch(() => {});
		}
	});
</script>

<div class="voice-picker">
	<span class="label">Your Voice</span>
	<select
		class="picker"
		value={current ?? NONE_VALUE}
		onchange={(e) => setChoice((e.target as HTMLSelectElement).value)}
	>
		<option value={NONE_VALUE}>None</option>
		{#each available as lora (lora.id)}
			{@const ready = lora.status === 'ready'}
			{@const active = isLoraActive(lora.status)}
			<option value={lora.id} disabled={!ready}>
				{lora.name}{!ready ? ` — ${active ? 'training' : lora.status}` : ''}
			</option>
		{/each}
	</select>
	{#if available.length === 0}
		<a class="hint" href="/loras">Create a voice</a>
	{/if}
</div>

<style>
	.voice-picker {
		display: flex;
		align-items: center;
		gap: 0.55rem;
		flex-wrap: wrap;
	}

	.label {
		font-size: var(--label-font-size);
		color: var(--text-muted);
		text-transform: uppercase;
		font-family: var(--font-display);
		letter-spacing: 0.5px;
		white-space: nowrap;
	}

	.picker {
		padding: 0.25rem 0.5rem;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-family: var(--font-body);
		font-size: 0.8rem;
	}

	.picker:focus {
		outline: none;
		border-color: var(--accent);
	}

	.hint {
		font-size: 0.75rem;
		color: var(--text-dim);
		text-decoration: none;
	}

	.hint:hover {
		color: var(--primary);
	}
</style>
