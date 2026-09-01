<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import {
		listWorkers,
		loadModelOnWorker,
		evictModelOnWorker,
		restartWorker,
		pinModelOnWorker,
		unpinModelOnWorker
	} from '$lib/api/client';
	import { createPollingStore } from '$lib/stores/adminPolling';
	import { activeJobs, trackJob } from '$lib/stores/jobs';
	import { addToast } from '$lib/stores/toast';
	import { ApiError } from '$lib/api/fetch';
	import type { WorkerPoolResponse, WorkerInfoItem } from '$lib/api/types';

	const POLL_INTERVAL_MS = 3000;
	const LOAD_JOB_TYPE = 'load_model_on_worker';

	interface Props {
		availableModes: string[];
	}

	let { availableModes }: Props = $props();

	const store = createPollingStore<WorkerPoolResponse>(listWorkers, POLL_INTERVAL_MS);
	const data = store.data;
	const error = store.error;

	const workers = $derived($data?.workers ?? []);

	let selectedMode = $state<Record<string, string>>({});
	let actionError = $state('');
	let busyAction = $state<Record<string, boolean>>({});
	let trackedLoadJobIds = new Set<string>();

	const loadingByWorker = $derived(
		new Map(
			$activeJobs
				.filter((j) => j.job.type === LOAD_JOB_TYPE && j.workerId)
				.map((j) => [j.workerId as string, j])
		)
	);

	const forbidden = $derived($error instanceof ApiError && $error.status === 403);

	$effect(() => {
		const currentLoadJobIds = new Set(
			$activeJobs.filter((j) => j.job.type === LOAD_JOB_TYPE && j.workerId).map((j) => j.job.id)
		);
		let disappeared = false;
		for (const id of trackedLoadJobIds) {
			if (!currentLoadJobIds.has(id)) {
				disappeared = true;
				break;
			}
		}
		if (disappeared) {
			void store.refresh();
		}
		trackedLoadJobIds = currentLoadJobIds;
	});

	$effect(() => {
		if (forbidden) {
			store.stop();
		}
	});

	onMount(() => store.start());
	onDestroy(() => store.stop());

	function statusIcon(status: WorkerInfoItem['status']): string {
		if (status === 'online') return '●';
		if (status === 'loading') return '⚠';
		return '✗';
	}

	function statusClass(status: WorkerInfoItem['status']): string {
		return `status-dot status-${status}`;
	}

	function formatElapsed(iso: string | null | undefined): string | null {
		if (!iso) return null;
		const then = new Date(iso).getTime();
		if (Number.isNaN(then)) return null;
		const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
		if (seconds < 60) return `${seconds}s`;
		const minutes = Math.floor(seconds / 60);
		const remSeconds = seconds % 60;
		if (minutes < 60) return `${minutes}m ${remSeconds}s`;
		const hours = Math.floor(minutes / 60);
		const remMinutes = minutes % 60;
		return `${hours}h ${remMinutes}m`;
	}

	function describeStatus(worker: WorkerInfoItem): string {
		const state = worker.state;
		if (!state) return 'Offline (no heartbeat)';
		if (state.target_loading) {
			const elapsed = formatElapsed(state.loading_started_at);
			return elapsed
				? `Loading ${state.target_loading}… (${elapsed} elapsed)`
				: `Loading ${state.target_loading}…`;
		}
		if (state.loaded.length === 0) return 'No model loaded';
		if (state.queue_depth > 0) return `Busy (${state.queue_depth} in queue)`;
		return 'Idle';
	}

	function formatLastSeen(iso: string | null | undefined): string {
		if (!iso) return 'never';
		const then = new Date(iso).getTime();
		if (Number.isNaN(then)) return iso;
		const deltaMs = Date.now() - then;
		if (deltaMs < 0) return 'just now';
		const seconds = Math.floor(deltaMs / 1000);
		if (seconds < 60) return `${seconds}s ago`;
		const minutes = Math.floor(seconds / 60);
		if (minutes < 60) return `${minutes}m ago`;
		const hours = Math.floor(minutes / 60);
		if (hours < 24) return `${hours}h ago`;
		const days = Math.floor(hours / 24);
		return `${days}d ago`;
	}

	function formatVram(
		state: WorkerInfoItem['state'],
		identity: WorkerInfoItem['identity']
	): string {
		const total = state?.vram_total_gb ?? identity.vram_total_gb;
		if (total == null) return '?';
		return `${total.toFixed(0)} GB`;
	}

	function formatVramUsage(state: WorkerInfoItem['state']): string | null {
		if (!state || state.vram_used_gb == null || state.vram_total_gb == null) return null;
		const isEstimate = state.vram_measured === false;
		const estimatePrefix = isEstimate ? '~' : '';
		const estimateSuffix = isEstimate ? ' est.' : '';
		return `${estimatePrefix}${state.vram_used_gb.toFixed(1)} / ${state.vram_total_gb.toFixed(1)} GB${estimateSuffix}`;
	}

	function isCardBusy(worker: WorkerInfoItem): boolean {
		if (worker.state?.target_loading) return true;
		if (loadingByWorker.has(worker.identity.id)) return true;
		return false;
	}

	async function handleLoad(workerId: string): Promise<void> {
		const mode = selectedMode[workerId];
		if (!mode) {
			actionError = 'Select a model to load';
			return;
		}
		actionError = '';
		busyAction = { ...busyAction, [workerId]: true };
		try {
			const job = await loadModelOnWorker(workerId, mode);
			trackJob(job, { workerId, mode });
			addToast(`Loading ${mode} on ${workerId}…`, 'info');
		} catch (e) {
			actionError = e instanceof Error ? e.message : 'Failed to enqueue load';
		} finally {
			busyAction = { ...busyAction, [workerId]: false };
		}
	}

	async function handleEvict(workerId: string, mode: string): Promise<void> {
		actionError = '';
		const key = `${workerId}:${mode}`;
		busyAction = { ...busyAction, [key]: true };
		try {
			await evictModelOnWorker(workerId, mode);
			addToast(`Evicted ${mode} from ${workerId}`, 'success');
			await store.refresh();
		} catch (e) {
			actionError = e instanceof Error ? e.message : 'Failed to evict model';
		} finally {
			busyAction = { ...busyAction, [key]: false };
		}
	}

	async function handleRestart(workerId: string): Promise<void> {
		if (
			typeof window !== 'undefined' &&
			!window.confirm(`Restart worker ${workerId}? In-flight generations will fail.`)
		) {
			return;
		}
		actionError = '';
		const key = `${workerId}:restart`;
		busyAction = { ...busyAction, [key]: true };
		try {
			await restartWorker(workerId);
			addToast(`Restart requested for ${workerId}`, 'info');
		} catch (e) {
			actionError = e instanceof Error ? e.message : 'Restart failed';
		} finally {
			busyAction = { ...busyAction, [key]: false };
		}
	}

	async function handleTogglePin(workerId: string, mode: string, isPinned: boolean): Promise<void> {
		actionError = '';
		const key = `${workerId}:pin:${mode}`;
		busyAction = { ...busyAction, [key]: true };
		try {
			if (isPinned) {
				await unpinModelOnWorker(workerId, mode);
				addToast(`Unpinned ${mode} on ${workerId}`, 'success');
			} else {
				await pinModelOnWorker(workerId, mode);
				addToast(`Pinned ${mode} on ${workerId}`, 'success');
			}
			await store.refresh();
		} catch (e) {
			actionError = e instanceof Error ? e.message : 'Pin toggle failed';
		} finally {
			busyAction = { ...busyAction, [key]: false };
		}
	}
</script>

<section class="panel">
	<h2>Worker Pool</h2>

	{#if forbidden}
		<p class="panel-error">Admin access required.</p>
	{:else if $error && workers.length === 0}
		<p class="panel-error">Cannot reach the worker pool API. {$error.message}</p>
	{:else if workers.length === 0}
		<p class="hint">
			No workers registered. Start the <code>songmaker-acestep-worker-0</code> container and wait a few
			seconds.
		</p>
	{:else}
		{#if actionError}
			<p class="panel-error">{actionError}</p>
		{/if}
		{#if $error}
			<p class="banner-error">⚠ Connection lost — retrying…</p>
		{/if}

		<div class="cards">
			{#each workers as worker (worker.identity.id)}
				{@const busy = isCardBusy(worker)}
				{@const trackedJob = loadingByWorker.get(worker.identity.id)}
				{@const offline = worker.state === null}
				{@const vramUsage = formatVramUsage(worker.state)}
				<div class="card" class:busy>
					<div class="card-header">
						<span class={statusClass(worker.status)}>{statusIcon(worker.status)}</span>
						<span class="worker-id">{worker.identity.id}</span>
						<span class="header-meta">
							GPU {worker.identity.gpu_id ?? '?'} • {formatVram(worker.state, worker.identity)}
						</span>
					</div>

					{#if worker.state}
						<div class="card-row">
							<span class="row-label">Loaded:</span>
							{#if worker.state.loaded.length === 0}
								<span class="row-value dim">(none)</span>
							{:else}
								<span class="row-value">
									{worker.state.loaded
										.map((m) => `${m.mode} (~${m.size_gb.toFixed(0)} GB est.)`)
										.join(', ')}
								</span>
							{/if}
						</div>
						<div class="card-row">
							<span class="row-label">Status:</span>
							<span class="row-value">
								{describeStatus(worker)}
								{#if trackedJob || worker.state.target_loading}
									<span class="spinner" aria-label="loading">⏳</span>
								{/if}
							</span>
						</div>
						{#if worker.state.target_loading && worker.state.loading_last_log_line}
							<div class="card-row">
								<span class="row-label">Log:</span>
								<span class="row-value log-line">{worker.state.loading_last_log_line}</span>
							</div>
						{/if}
						<div class="card-row">
							<span class="row-label">Queue:</span>
							<span class="row-value">{worker.state.queue_depth} jobs</span>
						</div>
						{#if vramUsage}
							<div class="card-row">
								<span class="row-label">VRAM:</span>
								<span
									class="row-value"
									title={worker.state.vram_measured === false ? 'Estimated VRAM usage' : undefined}
								>
									{vramUsage}
								</span>
							</div>
						{/if}
						<div class="card-row">
							<span class="row-label">Last seen:</span>
							<span class="row-value">{formatLastSeen(worker.state.last_heartbeat_at)}</span>
						</div>
					{:else}
						<div class="card-row">
							<span class="row-value dim">Offline (no heartbeat)</span>
						</div>
					{/if}

					<div class="card-actions">
						<select
							class="mode-select"
							bind:value={selectedMode[worker.identity.id]}
							disabled={busy || offline || availableModes.length === 0}
						>
							<option value="" disabled selected>Load model…</option>
							{#each availableModes as mode (mode)}
								<option value={mode}>{mode}</option>
							{/each}
						</select>
						<button
							class="action-btn"
							onclick={() => handleLoad(worker.identity.id)}
							disabled={busy ||
								offline ||
								!selectedMode[worker.identity.id] ||
								busyAction[worker.identity.id]}
						>
							{busyAction[worker.identity.id] ? 'Loading…' : 'Load'}
						</button>
						{#if worker.state && worker.state.loaded.length > 0}
							{#each worker.state.loaded as loadedDetail (loadedDetail.mode)}
								{@const isPinned = (worker.state?.pinned ?? []).includes(loadedDetail.mode)}
								<button
									class="action-btn"
									onclick={() => handleTogglePin(worker.identity.id, loadedDetail.mode, isPinned)}
									disabled={busy || busyAction[`${worker.identity.id}:pin:${loadedDetail.mode}`]}
								>
									{isPinned ? 'Unpin' : 'Pin'}
									{loadedDetail.mode}
								</button>
								<button
									class="action-btn"
									onclick={() => handleEvict(worker.identity.id, loadedDetail.mode)}
									disabled={busy || busyAction[`${worker.identity.id}:${loadedDetail.mode}`]}
								>
									Evict {loadedDetail.mode}
								</button>
							{/each}
						{/if}
						<button
							class="action-btn danger"
							onclick={() => handleRestart(worker.identity.id)}
							disabled={busyAction[`${worker.identity.id}:restart`]}
						>
							{busyAction[`${worker.identity.id}:restart`] ? 'Restarting…' : 'Restart'}
						</button>
					</div>
				</div>
			{/each}
		</div>
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
		margin-bottom: 0.5rem;
	}

	.banner-error {
		color: var(--text-muted);
		font-size: 0.75rem;
		margin-bottom: 0.5rem;
	}

	.cards {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.card {
		background: var(--surface-hover, rgba(255, 255, 255, 0.03));
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 0.75rem 1rem;
		font-size: 0.85rem;
	}

	.card.busy {
		opacity: 0.85;
	}

	.card-header {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 0.5rem;
	}

	.status-dot {
		font-size: 1rem;
		line-height: 1;
	}

	.status-online {
		color: rgb(0, 200, 100);
	}

	.status-loading {
		color: rgb(220, 180, 50);
	}

	.status-offline {
		color: rgb(220, 80, 80);
	}

	.worker-id {
		font-family: var(--font-mono, monospace);
		font-weight: 600;
		flex: 1 1 auto;
		min-width: 0;
		overflow-wrap: anywhere;
	}

	.header-meta {
		color: var(--text-muted);
		font-size: 0.75rem;
		min-width: 0;
		overflow-wrap: anywhere;
	}

	.card-row {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		padding: 0.15rem 0;
	}

	.row-label {
		color: var(--text-muted);
		min-width: 5.5rem;
	}

	.row-value {
		color: var(--text);
		min-width: 0;
		overflow-wrap: anywhere;
	}

	.row-value.dim {
		color: var(--text-muted);
		opacity: 0.6;
	}

	.spinner {
		display: inline-block;
		margin-left: 0.5rem;
	}

	.log-line {
		font-family: var(--font-mono, monospace);
		font-size: 0.7rem;
		color: var(--text-muted);
		white-space: pre-wrap;
		word-break: break-all;
	}

	.card-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
		margin-top: 0.6rem;
		max-width: 100%;
	}

	.mode-select {
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 3px;
		color: var(--text);
		padding: 0.2rem 0.4rem;
		font-size: 0.75rem;
		font-family: var(--font-body);
		max-width: 100%;
		min-width: 0;
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

	.action-btn.danger {
		border-color: rgb(220, 80, 80);
		color: rgb(220, 80, 80);
	}

	code {
		background: var(--surface-hover);
		padding: 0.05rem 0.3rem;
		border-radius: 2px;
		font-size: 0.8rem;
	}
</style>
