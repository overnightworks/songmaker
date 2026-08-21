<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { getRegistry, downloadModel } from '$lib/api/client';
	import { createPollingStore } from '$lib/stores/adminPolling';
	import { activeJobs, trackJob } from '$lib/stores/jobs';
	import { addToast } from '$lib/stores/toast';
	import { ApiError } from '$lib/api/fetch';
	import type { RegistryResponse } from '$lib/api/types';
	import { COMPACT_STACK_CLASS, ensureCompactUiStyles } from '$lib/styles/compact-ui';
	import { subscribeCompactLayout } from '$lib/utils/compact-layout';

	const POLL_INTERVAL_MS = 5000;
	const DOWNLOAD_JOB_TYPE = 'download_model_on_worker';

	interface Props {
		onModesChange?: (modes: string[]) => void;
	}

	let { onModesChange }: Props = $props();

	const store = createPollingStore<RegistryResponse>(getRegistry, POLL_INTERVAL_MS);
	const data = store.data;
	const error = store.error;

	const models = $derived($data?.models ?? []);
	const forbidden = $derived($error instanceof ApiError && $error.status === 403);

	const downloadingByMode = $derived(
		new Map(
			$activeJobs
				.filter((j) => j.job.type === DOWNLOAD_JOB_TYPE && j.mode)
				.map((j) => [j.mode as string, j])
		)
	);

	let busyMode = $state<Record<string, boolean>>({});
	let actionError = $state('');
	let compact = $state(false);

	$effect(() => {
		ensureCompactUiStyles();
		return subscribeCompactLayout((value) => (compact = value));
	});

	let trackedDownloadJobIds = new Set<string>();
	$effect(() => {
		const current = new Set(
			$activeJobs.filter((j) => j.job.type === DOWNLOAD_JOB_TYPE && j.mode).map((j) => j.job.id)
		);
		let disappeared = false;
		for (const id of trackedDownloadJobIds) {
			if (!current.has(id)) {
				disappeared = true;
				break;
			}
		}
		if (disappeared) void store.refresh();
		trackedDownloadJobIds = current;
	});

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

	async function handleDownload(mode: string): Promise<void> {
		actionError = '';
		busyMode = { ...busyMode, [mode]: true };
		try {
			const job = await downloadModel(mode);
			trackJob(job, { mode });
			addToast(`Downloading ${mode}…`, 'info');
		} catch (e) {
			actionError = e instanceof Error ? e.message : 'Failed to start download';
		} finally {
			busyMode = { ...busyMode, [mode]: false };
		}
	}

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
		{#if actionError}
			<p class="panel-error">{actionError}</p>
		{/if}
		<table class="registry-table {compact ? COMPACT_STACK_CLASS : ''}">
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
					{@const dlJob = downloadingByMode.get(model.mode)}
					<tr>
						<td class="mode-cell" data-label="Mode">{model.mode}</td>
						<td data-label="Status">
							{#if model.downloaded}
								<span class="badge ok">downloaded</span>
							{:else}
								<span class="badge missing">not downloaded</span>
							{/if}
						</td>
						<td class="count-cell" data-label="Loaded">×{model.loaded_on.length}</td>
						<td class="count-cell" data-label="Loading">
							{#if model.loading_on.length > 0}
								×{model.loading_on.length}
							{:else}
								<span class="dim">—</span>
							{/if}
						</td>
						<td class="actions-col">
							{#if dlJob}
								<span class="dl-progress">
									Downloading… {Math.round((dlJob.job.progress ?? 0) * 100)}%
								</span>
							{:else if model.downloaded}
								<span class="dim">—</span>
							{:else}
								<button
									class="action-btn"
									onclick={() => handleDownload(model.mode)}
									disabled={busyMode[model.mode]}
								>
									{busyMode[model.mode] ? 'Starting…' : 'Download'}
								</button>
							{/if}
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
		max-width: 100%;
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

	.dl-progress {
		font-size: 0.75rem;
		color: var(--text-muted);
		font-variant-numeric: tabular-nums;
	}
</style>
