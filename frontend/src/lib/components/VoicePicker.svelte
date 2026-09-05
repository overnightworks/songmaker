<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { onMount } from 'svelte';
	import { editGenParams, setDraftGenParams } from '$lib/stores/editor';
	import { loras, loadLoras, isLoraActive } from '$lib/stores/loras';
	import { recipeModel } from '$lib/stores/recipe';
	import {
		VOICE_PICKER_CREATE_LABEL,
		VOICE_PICKER_DELETED_LABEL,
		VOICE_PICKER_LABEL,
		VOICE_PICKER_NONE_LABEL,
		VOICE_PICKER_NOT_AVAILABLE_FOR_MODEL,
		voicePickerMobileLabel
	} from '$lib/constants';
	import type { UserLoraItem, VersionGenerationParams } from '$lib/api/types';

	const NONE_VALUE = '__none__';

	const current = $derived(($editGenParams ?? {}).user_lora_id ?? null);
	const visibleLoras = $derived(
		($loras ?? []).filter((lora) => lora.deleted_at === null || lora.id === current)
	);
	const selectedLora = $derived(($loras ?? []).find((lora) => lora.id === current) ?? null);
	const targetModelMode = $derived($recipeModel ?? '');
	let open = $state(false);

	function isSelectable(lora: UserLoraItem): boolean {
		return (
			lora.status === 'ready' && lora.deleted_at === null && lora.model_mode === targetModelMode
		);
	}

	function unavailableLabel(lora: UserLoraItem): string | null {
		if (lora.deleted_at !== null) return VOICE_PICKER_DELETED_LABEL;
		if (lora.status === 'ready' && lora.model_mode !== targetModelMode) {
			return VOICE_PICKER_NOT_AVAILABLE_FOR_MODEL;
		}
		if (lora.status !== 'ready') return isLoraActive(lora.status) ? 'training' : lora.status;
		return null;
	}

	const selectedLabel = $derived.by(() => {
		if (!selectedLora) return VOICE_PICKER_NONE_LABEL;
		const unavailable = unavailableLabel(selectedLora);
		return unavailable ? `${selectedLora.name} — ${unavailable}` : selectedLora.name;
	});

	function setChoice(value: string) {
		const next = value === NONE_VALUE ? null : value;
		const rest: VersionGenerationParams = { ...($editGenParams ?? {}) };
		if (next === null) {
			delete rest.user_lora_id;
		} else {
			rest.user_lora_id = next;
		}
		setDraftGenParams(Object.keys(rest).length > 0 ? rest : null);
		open = false;
	}

	onMount(() => {
		if ($loras.length === 0) {
			loadLoras().catch(() => {});
		}
	});
</script>

<div class="voice-picker">
	<span class="label desktop-label">{VOICE_PICKER_LABEL}</span>
	<span class="label mobile-label">{voicePickerMobileLabel(targetModelMode)}</span>
	<div class="picker-wrap">
		<button
			type="button"
			class="picker"
			aria-haspopup="listbox"
			aria-expanded={open}
			aria-controls="voice-picker-options"
			onclick={() => (open = !open)}
			onkeydown={(event) => event.key === 'Escape' && (open = false)}
		>
			<span>{selectedLabel}</span>
			<span aria-hidden="true">⌄</span>
		</button>
		{#if open}
			<div class="options" id="voice-picker-options" role="listbox" aria-label={VOICE_PICKER_LABEL}>
				<button
					type="button"
					class="option"
					class:selected={current === null}
					role="option"
					aria-selected={current === null}
					onclick={() => setChoice(NONE_VALUE)}
				>
					{VOICE_PICKER_NONE_LABEL}
				</button>
				{#each visibleLoras as lora (lora.id)}
					{@const selectable = isSelectable(lora)}
					{@const unavailable = unavailableLabel(lora)}
					<button
						type="button"
						class="option"
						class:selected={current === lora.id}
						class:unavailable={!selectable}
						class:deleted={lora.deleted_at !== null}
						role="option"
						aria-selected={current === lora.id}
						disabled={!selectable}
						onclick={() => setChoice(lora.id)}
					>
						<span>{lora.name}</span>
						{#if lora.deleted_at === null}
							<span class="mode-chip">{lora.model_mode}</span>
						{/if}
						{#if unavailable}
							<span class="unavailable-label">— {unavailable}</span>
						{/if}
					</button>
				{/each}
			</div>
		{/if}
	</div>
	{#if $loras.length === 0}
		<a class="hint" href="/settings/voices">{VOICE_PICKER_CREATE_LABEL}</a>
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

	.mobile-label {
		display: none;
	}

	.picker-wrap {
		position: relative;
	}

	.picker {
		width: 100%;
		padding: 0.25rem 0.5rem;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-family: var(--font-body);
		font-size: 0.8rem;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		cursor: pointer;
	}

	.picker:focus {
		outline: none;
		border-color: var(--accent);
	}

	.options {
		position: absolute;
		z-index: 1;
		top: calc(100% + 0.25rem);
		left: 0;
		min-width: max-content;
		padding: 0.25rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		box-shadow: 0 0.5rem 1rem rgb(0 0 0 / 30%);
	}

	.option {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.4rem 0.5rem;
		border: 0;
		border-radius: 3px;
		background: transparent;
		color: var(--text);
		font: inherit;
		text-align: left;
		white-space: nowrap;
		cursor: pointer;
	}

	.option:hover,
	.option.selected {
		background: var(--surface-hover, var(--bg));
	}

	.option.unavailable {
		color: var(--text-subtle);
		cursor: not-allowed;
	}

	.option.deleted {
		color: var(--danger, var(--primary));
		text-decoration: line-through;
	}

	.mode-chip {
		padding: 0.08rem 0.35rem;
		border: 1px solid color-mix(in srgb, var(--accent) 65%, var(--border));
		border-radius: 999px;
		color: var(--text);
		font-size: 0.65rem;
		line-height: 1.2;
		text-decoration: none;
	}

	.unavailable-label {
		font-size: 0.7rem;
		text-decoration: none;
	}

	.hint {
		font-size: 0.75rem;
		color: var(--text-subtle);
		text-decoration: none;
	}

	.hint:hover {
		color: var(--primary);
	}

	@media (max-width: 500px) {
		.desktop-label {
			display: none;
		}

		.mobile-label {
			display: inline;
		}

		.options {
			min-width: 100%;
			max-width: min(20rem, calc(100vw - 2rem));
		}

		.option {
			white-space: normal;
			flex-wrap: wrap;
		}
	}
</style>
