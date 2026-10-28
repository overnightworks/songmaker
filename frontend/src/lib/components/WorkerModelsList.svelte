<script lang="ts">
	import type { LoadedModelDetailItem } from '$lib/api/types';
	import {
		WORKER_POOL_MODELS_LABEL,
		WORKER_POOL_MODELS_LOADING_TEMPLATE,
		WORKER_POOL_MODELS_OFFLINE_LABEL,
		WORKER_POOL_NO_MODEL_LABEL,
		WORKER_POOL_KEEP_LOADED_LABEL,
		WORKER_POOL_KEEP_LOADED_HINT,
		WORKER_POOL_UNLOAD_LABEL
	} from '$lib/constants';

	interface Props {
		loaded: LoadedModelDetailItem[];
		offline: boolean;
		loadingMode: string | null;
		pinned: string[];
		isPinDisabled: (mode: string) => boolean;
		isUnloadDisabled: (mode: string) => boolean;
		onTogglePin: (mode: string, pinned: boolean) => void;
		onUnload: (mode: string) => void;
	}
	let {
		loaded,
		offline,
		loadingMode,
		pinned,
		isPinDisabled,
		isUnloadDisabled,
		onTogglePin,
		onUnload
	}: Props = $props();
</script>

<div class="models" role="group" aria-label={WORKER_POOL_MODELS_LABEL}>
	<div class="heading">
		<span class="title">{WORKER_POOL_MODELS_LABEL}</span>
		{#if !offline && loaded.length > 0}
			<span class="hint">{WORKER_POOL_KEEP_LOADED_HINT}</span>
		{/if}
	</div>
	{#if offline}
		<p>{WORKER_POOL_MODELS_OFFLINE_LABEL}</p>
	{:else}
		{#each loaded as model (model.mode)}
			{@const kept = pinned.includes(model.mode)}
			<div class="model" role="group" aria-label={model.mode}>
				<span class="name">{model.mode}</span>
				<span class="size">~{model.size_gb.toFixed(0)} GB</span>
				<button
					class="keep"
					role="switch"
					aria-checked={kept}
					aria-label={`${WORKER_POOL_KEEP_LOADED_LABEL} ${model.mode}`}
					disabled={isPinDisabled(model.mode)}
					onclick={() => onTogglePin(model.mode, kept)}
				>
					<span class="check" class:kept aria-hidden="true">{kept ? '✓' : ''}</span>
					{WORKER_POOL_KEEP_LOADED_LABEL}
				</button>
				<button
					class="unload"
					aria-label={`${WORKER_POOL_UNLOAD_LABEL} ${model.mode}`}
					disabled={isUnloadDisabled(model.mode)}
					onclick={() => onUnload(model.mode)}>{WORKER_POOL_UNLOAD_LABEL}</button
				>
			</div>
		{:else}
			<p>
				{loadingMode
					? WORKER_POOL_MODELS_LOADING_TEMPLATE.replace('{mode}', loadingMode)
					: WORKER_POOL_NO_MODEL_LABEL}
			</p>
		{/each}
	{/if}
</div>

<style>
	.models {
		margin-top: 0.35rem;
		border-top: 1px solid var(--border);
		padding-top: 0.45rem;
	}
	p {
		color: var(--text-muted);
		font-size: 0.8rem;
		overflow-wrap: anywhere;
	}
	.heading {
		display: flex;
		flex-wrap: wrap;
		gap: 0.1rem 0.6rem;
		color: var(--text-muted);
		font-size: 0.7rem;
	}
	.title {
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.07em;
	}
	.model {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto auto auto;
		gap: 0.55rem;
		align-items: center;
		min-height: 2rem;
		font-size: 0.8rem;
	}
	.model + .model {
		border-top: 1px dotted var(--border);
	}
	.name {
		font-weight: 600;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.size {
		color: var(--text-muted);
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	button {
		color: var(--text);
		font-family: var(--font-body);
		font-size: 0.74rem;
		cursor: pointer;
	}
	.keep {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		white-space: nowrap;
		background: transparent;
		border: 0;
		padding: 0.2rem 0;
	}
	.check {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 15px;
		height: 15px;
		border: 1px solid var(--border);
		border-radius: 3px;
	}
	.check.kept {
		background: var(--accent);
		color: var(--on-accent);
		border-color: var(--accent);
	}
	.unload {
		background: var(--surface-hover);
		border: 1px solid var(--border);
		border-radius: 3px;
		padding: 0.2rem 0.4rem;
	}
	button:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
</style>
