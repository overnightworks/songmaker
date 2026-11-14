<script lang="ts">
	import { onMount, onDestroy, tick } from 'svelte';
	import {
		listWorkers,
		loadModelOnWorker,
		evictModelOnWorker,
		restartWorker,
		pinModelOnWorker,
		unpinModelOnWorker
	} from '#lib/api/client.ts';
	import { createPollingStore } from '#lib/stores/adminPolling.ts';
	import { activeJobs, trackJob } from '#lib/stores/jobs.ts';
	import { addToast } from '#lib/stores/toast.ts';
	import { ApiError, describeFailure } from '#lib/api/fetch.ts';
	import type { WorkerPoolResponse, WorkerInfoItem } from '#lib/api/types.ts';
	import { offline } from '#lib/stores/connectivity.ts';
	import { Marked } from 'overnightworks-design';
	import { pageParts, pageText } from '#lib/utils/page-words.ts';

	import { dialogHistoryLayer } from '#lib/utils/dialog-history-layer.ts';
	import { focusFirstIn, handleFocusTrapKeydown, refocusIfDropped } from '#lib/utils/focus-trap.ts';
	import { formatDecimal, localClockTime } from '#lib/utils/format.ts';

	import WorkerVramLine from './WorkerVramLine.svelte';
	import WorkerModelsList from './WorkerModelsList.svelte';

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
	let confirmation = $state<{
		workerId: string;
		opener: HTMLButtonElement;
		layer: ReturnType<typeof dialogHistoryLayer>;
	} | null>(null);

	function closeConfirmation(): void {
		confirmation = null;
	}

	function openConfirmation(workerId: string, opener: HTMLButtonElement): void {
		confirmation = {
			workerId,
			opener,
			layer: dialogHistoryLayer('worker-restart', closeConfirmation)
		};
	}

	function focusConfirmation(element: HTMLElement): () => void {
		const opener = confirmation?.opener;
		focusFirstIn(element);
		return () => {
			void tick().then(() => refocusIfDropped(opener));
		};
	}

	$effect(() => {
		if (
			confirmation &&
			(forbidden || !workers.some((worker) => worker.identity.id === confirmation?.workerId))
		) {
			closeConfirmation();
		}
	});

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
		if (seconds < 60) {
			return pageText('workerPool.elapsedSeconds', { seconds: formatDecimal(seconds, 0) });
		}
		const minutes = Math.floor(seconds / 60);
		const remSeconds = seconds % 60;
		if (minutes < 60) {
			return pageText('workerPool.elapsedMinutes', {
				minutes: formatDecimal(minutes, 0),
				seconds: formatDecimal(remSeconds, 0)
			});
		}
		const hours = Math.floor(minutes / 60);
		const remMinutes = minutes % 60;
		return pageText('workerPool.elapsedHours', {
			hours: formatDecimal(hours, 0),
			minutes: formatDecimal(remMinutes, 0)
		});
	}

	// Three ways a worker can be non-operable, each needing its own honest
	// sentence (issue #367): no heartbeat at all, a heartbeat reporting a
	// broken GPU (NVML present but unreachable), or an old worker build
	// whose heartbeat predates the GPU health field entirely.
	function describeOffline(worker: WorkerInfoItem): string {
		const state = worker.state;
		if (!state) {
			return pageText('workerPool.offlineSince', {
				lastSeen: formatLastSeen(worker.identity.last_register_at)
			});
		}
		if (state.gpu_healthy === false) {
			return state.gpu_health_detail
				? pageText('workerPool.gpuUnavailableDetail', { detail: state.gpu_health_detail })
				: pageText('workerPool.gpuUnavailable');
		}
		return pageText('workerPool.gpuHealthNotReported');
	}

	// Nothing is listening for /restart once the worker process is gone; a
	// worker whose GPU is broken is a different cause and needs its own
	// sentence — the process is up but restarting it won't fix a missing
	// GPU. A worker that never reports gpu_healthy at all is neither of
	// those: nothing shows the GPU is actually broken, only that this
	// build predates the check, and restarting the same process changes
	// nothing — the container needs the current image.
	function restartDisabledHint(worker: WorkerInfoItem): string {
		const workerId = worker.identity.id;
		const state = worker.state;
		if (!state) {
			return pageText('workerPool.restartNoProcess', { worker: workerId });
		}
		if (state.gpu_healthy === false) {
			return pageText('workerPool.restartBrokenGpu', { worker: workerId });
		}
		return pageText('workerPool.restartNoGpuHealth', { worker: workerId });
	}

	function describeStatus(worker: WorkerInfoItem): string {
		const state = worker.state;
		if (!state) return describeOffline(worker);
		if (state.target_loading) {
			const elapsed = formatElapsed(state.loading_started_at);
			return elapsed
				? pageText('workerPool.statusLoadingElapsed', { mode: state.target_loading, elapsed })
				: pageText('workerPool.statusLoading', { mode: state.target_loading });
		}
		if (state.training_hold_seconds != null) {
			return pageText('workerPool.statusTraining', {
				seconds: formatDecimal(state.training_hold_seconds, 0)
			});
		}
		if (state.loaded.length === 0) return pageText('workerPool.statusNoModel');
		if (state.queue_depth > 0) {
			return pageText('workerPool.statusBusy', { count: state.queue_depth });
		}
		return pageText('workerPool.statusIdle');
	}

	function formatLastSeen(iso: string | null | undefined): string {
		if (!iso) return pageText('workerPool.seenNever');
		const then = new Date(iso).getTime();
		if (Number.isNaN(then)) return iso;
		const deltaMs = Date.now() - then;
		if (deltaMs < 0) return pageText('workerPool.seenJustNow');
		const seconds = Math.floor(deltaMs / 1000);
		if (seconds < 60) return pageText('workerPool.secondsAgo', { count: seconds });
		const minutes = Math.floor(seconds / 60);
		if (minutes < 60) return pageText('workerPool.minutesAgo', { count: minutes });
		const hours = Math.floor(minutes / 60);
		if (hours < 24) return pageText('workerPool.hoursAgo', { count: hours });
		const days = Math.floor(hours / 24);
		return pageText('workerPool.daysAgo', { count: days });
	}

	function formatVram(
		state: WorkerInfoItem['state'],
		identity: WorkerInfoItem['identity']
	): string {
		const total = state?.vram_total_gb ?? identity.vram_total_gb;
		if (total == null) return '?';
		return pageText('workerPool.vramTotal', { total: formatDecimal(total, 0) });
	}

	function isWorkerLoading(worker: WorkerInfoItem): boolean {
		return !!worker.state?.target_loading || loadingByWorker.has(worker.identity.id);
	}

	function isCardBusy(worker: WorkerInfoItem): boolean {
		return isWorkerLoading(worker) || worker.state?.training_hold_seconds != null;
	}

	async function handleLoad(workerId: string): Promise<void> {
		const mode = selectedMode[workerId];
		if (!mode) {
			actionError = pageText('workerPool.selectModel');
			return;
		}
		actionError = '';
		busyAction = { ...busyAction, [workerId]: true };
		try {
			const job = await loadModelOnWorker(workerId, mode);
			trackJob(job, { workerId, mode });
			addToast(pageText('workerPool.loadingToast', { mode, worker: workerId }), 'info');
		} catch (e) {
			actionError = describeFailure(e, pageText('workerPool.enqueueFailed'));
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
			addToast(pageText('workerPool.unloadedToast', { mode, worker: workerId }), 'success');
			await store.refresh();
		} catch (e) {
			actionError = describeFailure(e, pageText('workerPool.unloadFailed'));
		} finally {
			busyAction = { ...busyAction, [key]: false };
		}
	}

	function canRestart(worker: WorkerInfoItem | undefined): boolean {
		return (
			!!worker &&
			worker.status !== 'offline' &&
			!forbidden &&
			!busyAction[`${worker.identity.id}:restart`]
		);
	}

	async function handleRestart(workerId: string): Promise<void> {
		const key = `${workerId}:restart`;
		const worker = workers.find((worker) => worker.identity.id === workerId);
		if (!canRestart(worker)) return;
		actionError = '';
		busyAction = { ...busyAction, [key]: true };
		try {
			await restartWorker(workerId);
			addToast(pageText('workerPool.restartRequested', { worker: workerId }), 'info');
		} catch (e) {
			actionError = describeFailure(e, pageText('workerPool.restartFailed'));
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
				addToast(pageText('workerPool.keepLoadedOff', { mode, worker: workerId }), 'success');
			} else {
				await pinModelOnWorker(workerId, mode);
				addToast(pageText('workerPool.keepLoadedOn', { mode, worker: workerId }), 'success');
			}
			await store.refresh();
		} catch (e) {
			actionError = describeFailure(e, pageText('workerPool.keepLoadedFailed'));
		} finally {
			busyAction = { ...busyAction, [key]: false };
		}
	}
</script>

<section class="panel">
	<h2>{pageText('workerPool.heading')}</h2>

	{#if forbidden}
		<p class="panel-error">{pageText('adminPage.accessRequired')}</p>
	{:else if $error && workers.length === 0}
		{#if !$offline}
			<p class="panel-error">{describeFailure($error, pageText('workerPool.loadFailed'))}</p>
		{/if}
	{:else if workers.length === 0}
		<p class="hint">
			<Marked
				parts={pageParts('workerPool.noWorkers', { container: 'songmaker-acestep-worker-0' })}
				marked={{ code }}
			/>
		</p>
	{:else}
		{#if actionError}
			<p class="panel-error">{actionError}</p>
		{/if}
		{#if $error && !$offline}
			<p class="banner-error">{describeFailure($error, pageText('workerPool.refreshFailed'))}</p>
		{/if}

		<div class="cards">
			{#each workers as worker (worker.identity.id)}
				{@const busy = isCardBusy(worker)}
				{@const trackedJob = loadingByWorker.get(worker.identity.id)}
				{@const offline = worker.status === 'offline'}
				{@const loadingMode = worker.state?.target_loading ?? trackedJob?.mode ?? null}
				{@const loading = isWorkerLoading(worker) || !!busyAction[worker.identity.id]}
				<div class="card" class:busy>
					<div class="card-header">
						<span class={statusClass(worker.status)}>{statusIcon(worker.status)}</span>
						<span class="worker-id">{worker.identity.id}</span>
						<span class="header-meta">
							{pageText('workerPool.cardHeader', {
								gpu: String(worker.identity.gpu_id ?? '?'),
								vram: formatVram(worker.state, worker.identity)
							})}
						</span>
					</div>

					{#if worker.state && !offline}
						<div class="card-row">
							<span class="row-label">{pageText('workerPool.statusLabel')}</span>
							<span class="row-value">
								{describeStatus(worker)}
								{#if trackedJob || worker.state.target_loading || worker.state.training_hold_seconds != null}
									<span class="spinner" aria-label={pageText('workerPool.loadingSpinner')}>⏳</span>
								{/if}
							</span>
						</div>
						{#if worker.state.target_loading && worker.state.loading_last_log_line}
							<div class="card-row">
								<span class="row-label">{pageText('workerPool.logLabel')}</span>
								<span class="row-value log-line">{worker.state.loading_last_log_line}</span>
							</div>
						{/if}
						<div class="card-row">
							<span class="row-label">{pageText('workerPool.queueLabel')}</span>
							<span class="row-value"
								>{pageText('workerPool.queueJobs', worker.state.queue_depth)}</span
							>
						</div>
					{:else}
						<div class="card-row">
							<span class="row-value dim">{describeOffline(worker)}</span>
						</div>
						<div class="card-row">
							<span class="row-value dim">{restartDisabledHint(worker)}</span>
						</div>
					{/if}

					<WorkerVramLine state={worker.state} {offline} />
					{#if worker.state && !offline}
						<div class="card-row">
							<span class="row-label">{pageText('workerPool.lastSeenLabel')}</span>
							<span class="row-value">{formatLastSeen(worker.state.last_heartbeat_at)}</span>
						</div>
					{/if}

					<WorkerModelsList
						loaded={worker.state?.loaded ?? []}
						{offline}
						{loadingMode}
						pinned={worker.state?.pinned ?? []}
						isPinDisabled={(mode) => busy || !!busyAction[`${worker.identity.id}:pin:${mode}`]}
						isUnloadDisabled={(mode) => busy || !!busyAction[`${worker.identity.id}:${mode}`]}
						onTogglePin={(mode, pinned) => handleTogglePin(worker.identity.id, mode, pinned)}
						onUnload={(mode) => handleEvict(worker.identity.id, mode)}
					/>

					<div class="load-row">
						<select
							class="mode-select"
							bind:value={selectedMode[worker.identity.id]}
							disabled={loading || offline || availableModes.length === 0}
						>
							<option value="" disabled selected>{pageText('workerPool.loadModel')}</option>
							{#each availableModes as mode (mode)}
								<option value={mode}>{mode}</option>
							{/each}
						</select>
						<button
							class="action-btn"
							onclick={() => handleLoad(worker.identity.id)}
							disabled={loading ||
								offline ||
								!availableModes.includes(selectedMode[worker.identity.id])}
						>
							{busyAction[worker.identity.id]
								? pageText('workerPool.loadingAction')
								: pageText('workerPool.load')}
						</button>
					</div>
					{#if worker.state?.last_error}
						{@const errorAt = worker.state.last_error_at
							? new Date(worker.state.last_error_at)
							: null}
						<div class="last-error">
							<div class="last-error-heading">
								<strong><span aria-hidden="true">✕</span> {pageText('workerPool.lastError')}</strong
								>
								{#if errorAt && !Number.isNaN(errorAt.getTime())}
									<time datetime={worker.state.last_error_at ?? undefined}
										>{localClockTime(errorAt)} · {formatLastSeen(worker.state.last_error_at)}</time
									>
								{/if}
							</div>
							<p class="error-text">{worker.state.last_error}</p>
							<p class="logs">
								<Marked
									parts={pageParts('workerPool.fullLogs', {
										command: `docker compose logs ${worker.identity.id}`
									})}
									marked={{ code }}
								/>
							</p>
						</div>
					{/if}
					<div class="card-actions">
						<button
							class="action-btn danger"
							onclick={(event) => openConfirmation(worker.identity.id, event.currentTarget)}
							disabled={!canRestart(worker)}
							title={offline ? restartDisabledHint(worker) : undefined}
						>
							{busyAction[`${worker.identity.id}:restart`]
								? pageText('workerPool.restarting')
								: pageText('workerPool.restart')}
						</button>
					</div>
					{#if confirmation?.workerId === worker.identity.id}
						{@const current = confirmation}
						{@const title = pageText('workerPool.restartTitle', { worker: worker.identity.id })}
						<div
							class="restart-confirmation"
							role="dialog"
							aria-label={title}
							tabindex="-1"
							{@attach current.layer.hold}
							{@attach focusConfirmation}
							onkeydown={(event) => handleFocusTrapKeydown(event.currentTarget, event)}
						>
							<strong>{title}</strong>
							<p>{pageText('workerPool.restartWarning')}</p>
							<div class="confirmation-actions">
								<button class="action-btn" onclick={current.layer.answer(closeConfirmation)}
									>{pageText('workerPool.cancel')}</button
								>
								<button
									class="action-btn danger"
									disabled={!canRestart(worker)}
									onclick={current.layer.answer(() => {
										closeConfirmation();
										void handleRestart(worker.identity.id);
									})}>{pageText('workerPool.restartConfirm')}</button
								>
							</div>
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</section>

{#snippet code({ text }: { text: string })}<code>{text}</code>{/snippet}

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
		color: var(--fail);
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
		color: var(--fail);
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

	.load-row,
	.card-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
		margin-top: 0.6rem;
		max-width: 100%;
	}

	.card-actions {
		border-top: 1px solid var(--border);
		padding-top: 0.5rem;
	}

	.last-error {
		margin-top: 0.35rem;
		padding: 0.5rem 0.65rem;
		border-left: 3px solid var(--fail);
		background: color-mix(in srgb, var(--fail) 8%, transparent);
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		overflow-wrap: anywhere;
	}

	.last-error-heading,
	.confirmation-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
		align-items: baseline;
	}

	.last-error-heading strong {
		color: var(--fail);
	}
	.last-error time,
	.logs {
		color: var(--text-muted);
		font-size: 0.72rem;
	}
	.last-error p,
	.restart-confirmation p {
		margin: 0;
	}
	.error-text {
		white-space: pre-wrap;
	}
	.restart-confirmation {
		max-width: 24rem;
		margin-top: 0.9rem;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--surface);
		padding: 0.8rem 0.9rem;
		display: flex;
		flex-direction: column;
		gap: 0.45rem;
		overflow-wrap: anywhere;
	}
	.confirmation-actions {
		justify-content: flex-end;
	}

	.load-row .mode-select {
		flex: 0 1 8.2rem;
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
		border-color: var(--accent);
		color: var(--accent);
	}

	code {
		background: var(--surface-hover);
		padding: 0.05rem 0.3rem;
		border-radius: 2px;
		font-size: 0.8rem;
	}
</style>
