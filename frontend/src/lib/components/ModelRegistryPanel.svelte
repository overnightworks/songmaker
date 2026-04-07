<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getRegistry } from '$lib/api/client';
	import { createPollingStore } from '$lib/stores/adminPolling';
	import { ApiError } from '$lib/api/fetch';
	import type { RegistryResponse } from '$lib/api/types';

	const POLL_INTERVAL_MS = 5000;

	interface Props {
		onModesChange?: (modes: string[]) => void;
	}

	let { onModesChange }: Props = $props();

	const store = createPollingStore<RegistryResponse>(getRegistry, POLL_INTERVAL_MS);
	const data = store.data;
	const error = store.error;

	const models = $derived($data?.models ?? []);
	const forbidden = $derived($error instanceof ApiError && $error.status === 403);

	let lastModesKey = '';

	$effect(() => {
		if (!onModesChange || models.length === 0) return;
		const modes = models.map((m) => m.mode);
		const key = modes.join('|');
		if (key === lastModesKey) return;
		lastModesKey = key;
		onModesChange(modes);
	});

	$effect(() => {
		if (forbidden) {
			store.stop();
		}
	});

	onMount(() => store.start());
	onDestroy(() => store.stop());
</script>

<section class="panel">
	<h2>Model Registry</h2>

	{#if forbidden}
		<p class="panel-error">Admin access required.</p>
	{:else if $error && models.length === 0}
		<p class="panel-error">Cannot reach the registry API. {$error.message}</p>
	{:else if models.length === 0}
		<p class="hint">Loading registry…</p>
	{:else}
		<table class="registry-table">
			<thead>
				<tr>
					<th>Mode</th>
					<th>Status</th>
					<th>Loaded</th>
					<th>Loading</th>
					<th class="actions-col">Actions</th>
				</tr>
			</thead>
			<tbody>
				{#each models as model (model.mode)}
					<tr>
						<td class="mode-cell">{model.mode}</td>
						<td>
							{#if model.downloaded}
								<span class="badge ok">downloaded</span>
							{:else}
								<span class="badge missing">not downloaded</span>
							{/if}
						</td>
						<td class="count-cell">×{model.loaded_on.length}</td>
						<td class="count-cell">
							{#if model.loading_on.length > 0}
								×{model.loading_on.length}
							{:else}
								<span class="dim">—</span>
							{/if}
						</td>
						<td class="actions-col">
							<button class="action-btn" disabled title="Coming in Phase 5"> Download </button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
		{#if $error}
			<p class="banner-error">⚠ Connection lost — retrying…</p>
		{/if}
	{/if}
</section>

<style>
	.panel {
		margin-top: 1.5rem;
	}

	h2 {
		font-size: 1rem;
		color: var(--text-muted);
		margin-bottom: 0.8rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.hint {
		color: var(--text-muted);
		font-size: 0.85rem;
	}

	.panel-error {
		color: var(--score-bad);
		font-size: 0.85rem;
	}

	.banner-error {
		color: var(--text-muted);
		font-size: 0.75rem;
		margin-top: 0.5rem;
	}

	.registry-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.85rem;
	}

	.registry-table th {
		text-align: left;
		color: var(--text-muted);
		font-weight: 600;
		padding: 0.5rem;
		border-bottom: 1px solid var(--border);
	}

	.registry-table td {
		padding: 0.5rem;
		border-bottom: 1px solid var(--border);
	}

	.mode-cell {
		font-family: var(--font-mono, monospace);
		font-weight: 600;
	}

	.count-cell {
		font-variant-numeric: tabular-nums;
	}

	.dim {
		color: var(--text-muted);
		opacity: 0.5;
	}

	.actions-col {
		text-align: right;
	}

	.badge {
		display: inline-block;
		padding: 0.1rem 0.5rem;
		border-radius: 3px;
		font-size: 0.75rem;
	}

	.badge.ok {
		background: rgba(0, 200, 100, 0.15);
		color: rgb(0, 200, 100);
	}

	.badge.missing {
		background: rgba(220, 80, 80, 0.15);
		color: rgb(220, 80, 80);
	}

	.action-btn {
		background: var(--surface-hover);
		color: var(--text);
		border: 1px solid var(--border);
		border-radius: 3px;
		padding: 0.2rem 0.6rem;
		font-size: 0.75rem;
		cursor: pointer;
		font-family: var(--font-body);
	}

	.action-btn:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
</style>
