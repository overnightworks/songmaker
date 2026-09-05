<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { ApiError } from '$lib/api/client';
	import {
		anyLoraActive,
		createLora,
		isLoraActive,
		loadLoras,
		loras,
		lorasError,
		lorasLoading,
		softDeleteLora
	} from '$lib/stores/loras';
	import { addToast } from '$lib/stores/toast';
	import ToastContainer from '$lib/components/ToastContainer.svelte';
	import LoraDetail from '$lib/components/LoraDetail.svelte';
	import ConfirmDeleteDialog from '$lib/components/ConfirmDeleteDialog.svelte';
	import { APP_NAME, LORA_CREATE_FAILED, LORA_POLL_INTERVAL_MS } from '$lib/constants';
	import type { UserLoraItem } from '$lib/api/types';

	let showCreate = $state(false);
	let creating = $state(false);
	let newName = $state('');
	let createError = $state<string | null>(null);
	let showDeleted = $state(false);
	let expandedId = $state<string | null>(null);
	let loraPendingDelete = $state<UserLoraItem | null>(null);
	let pollHandle: ReturnType<typeof setInterval> | null = null;

	const list = $derived($loras);
	const visible = $derived(showDeleted ? list : list.filter((l) => l.deleted_at === null));
	const hasActive = $derived($anyLoraActive);

	async function refresh() {
		try {
			await loadLoras(showDeleted);
		} catch {
			// store already captured error message
		}
	}

	function startPolling() {
		stopPolling();
		pollHandle = setInterval(() => {
			if (hasActive) refresh();
		}, LORA_POLL_INTERVAL_MS);
	}

	function stopPolling() {
		if (pollHandle) {
			clearInterval(pollHandle);
			pollHandle = null;
		}
	}

	onMount(async () => {
		await refresh();
		startPolling();
	});

	onDestroy(() => {
		stopPolling();
	});

	$effect(() => {
		void showDeleted;
		refresh();
	});

	async function handleCreate() {
		const name = newName.trim();
		if (!name) return;
		creating = true;
		createError = null;
		try {
			const created = await createLora(name);
			newName = '';
			showCreate = false;
			expandedId = created.id;
			addToast('Voice created', 'success');
		} catch (e) {
			const message = e instanceof ApiError ? e.detail || LORA_CREATE_FAILED : LORA_CREATE_FAILED;
			createError = message;
			addToast(message, 'error');
		} finally {
			creating = false;
		}
	}

	function toggleExpand(lora: UserLoraItem) {
		expandedId = expandedId === lora.id ? null : lora.id;
	}

	function askDelete(lora: UserLoraItem) {
		loraPendingDelete = lora;
	}

	async function confirmDelete() {
		if (!loraPendingDelete) return;
		const lora = loraPendingDelete;
		loraPendingDelete = null;
		try {
			await softDeleteLora(lora.id);
			if (expandedId === lora.id) expandedId = null;
			addToast(`Deleted ${lora.name}`, 'info');
		} catch (e) {
			addToast(e instanceof ApiError ? e.detail || 'Delete failed' : 'Delete failed', 'error');
		}
	}

	function statusTone(status: string): string {
		if (status === 'ready') return 'good';
		if (status === 'failed') return 'bad';
		if (isLoraActive(status)) return 'active';
		return 'neutral';
	}
</script>

<svelte:head>
	<title>My Voices — {APP_NAME}</title>
</svelte:head>

<div class="page">
	<header class="page-head">
		<h1>My Voices</h1>
		<div class="head-actions">
			<label class="toggle-deleted">
				<input type="checkbox" bind:checked={showDeleted} />
				Show deleted
			</label>
			<button class="create-btn" onclick={() => (showCreate = !showCreate)}>
				{showCreate ? 'Cancel' : 'New Voice'}
			</button>
		</div>
	</header>

	{#if showCreate}
		<div class="create-panel">
			<input
				type="text"
				placeholder="Voice name (e.g. My Tenor)"
				bind:value={newName}
				onkeydown={(e) => {
					if (e.key === 'Enter') handleCreate();
					if (e.key === 'Escape') showCreate = false;
				}}
			/>
			<button class="primary" disabled={creating || !newName.trim()} onclick={handleCreate}>
				{creating ? 'Creating...' : 'Create'}
			</button>
		</div>
		{#if createError}
			<p class="create-error" role="alert">{createError}</p>
		{/if}
	{/if}

	{#if $lorasError}
		<p class="error">{$lorasError}</p>
	{/if}

	{#if $lorasLoading && list.length === 0}
		<p class="loading">Loading voices...</p>
	{:else if visible.length === 0}
		<p class="empty">No voices yet. Create one to upload samples and train your own vocal style.</p>
	{:else}
		<ul class="lora-list">
			{#each visible as lora (lora.id)}
				{@const tone = statusTone(lora.status)}
				<li class="lora-card" class:deleted={lora.deleted_at !== null}>
					<button
						class="lora-row"
						onclick={() => toggleExpand(lora)}
						aria-expanded={expandedId === lora.id}
					>
						<span class="lora-name">{lora.name}</span>
						<span class="status-badge {tone}">{lora.status}</span>
						{#if lora.status === 'ready'}
							<span class="model-mode">{lora.model_mode}</span>
						{/if}
						<span class="sample-count">{lora.samples.length} samples</span>
						<span class="arrow" class:open={expandedId === lora.id}>▸</span>
					</button>
					<div class="row-actions">
						{#if lora.deleted_at === null}
							<button
								class="danger"
								disabled={isLoraActive(lora.status)}
								onclick={() => askDelete(lora)}
							>
								Delete
							</button>
						{:else}
							<span class="deleted-tag">deleted</span>
						{/if}
					</div>
					{#if expandedId === lora.id}
						<div class="detail-panel">
							<LoraDetail {lora} />
						</div>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</div>

{#if loraPendingDelete}
	<ConfirmDeleteDialog
		title="Delete voice?"
		items={[loraPendingDelete.name]}
		warning={`${loraPendingDelete.name} will be hidden from new generations. Existing takes keep their audio and remain playable; they will show “voice deleted”.`}
		confirmLabel="Delete"
		onconfirm={confirmDelete}
		oncancel={() => (loraPendingDelete = null)}
	/>
{/if}

<ToastContainer />

<style>
	.page-head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 1rem;
		margin-bottom: 1.5rem;
		flex-wrap: wrap;
	}

	h1 {
		margin: 0;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.1em;
		background: linear-gradient(90deg, var(--primary), var(--accent));
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
		font-size: 1.5rem;
	}

	.head-actions {
		display: flex;
		gap: 0.8rem;
		align-items: center;
	}

	.toggle-deleted {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		font-size: 0.8rem;
		color: var(--text-muted);
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.create-btn {
		padding: 0.45rem 1rem;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-pill);
		background: transparent;
		color: var(--text-muted);
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		font-size: 0.8rem;
	}

	.create-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.create-panel {
		margin-bottom: 1rem;
		display: flex;
		gap: 0.5rem;
		align-items: center;
	}

	.create-panel input {
		flex: 1;
		padding: 0.5rem 0.75rem;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 0.9rem;
	}

	.create-panel input:focus {
		outline: none;
		border-color: var(--accent);
	}

	.create-error {
		margin: -0.5rem 0 1rem;
		padding: 0.65rem 0.8rem;
		border: 1px solid var(--score-bad);
		border-radius: 4px;
		color: var(--score-bad);
		font-size: 0.85rem;
		overflow-wrap: anywhere;
		white-space: pre-line;
	}

	.primary {
		padding: 0.5rem 1.1rem;
		border: none;
		border-radius: var(--btn-radius-pill);
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: #fff;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		font-size: 0.8rem;
	}

	.primary:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.error {
		color: var(--score-bad);
		font-size: 0.85rem;
	}

	.loading,
	.empty {
		color: var(--text-subtle);
		font-size: 0.9rem;
	}

	.lora-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.lora-card {
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface);
		display: grid;
		grid-template-columns: 1fr auto;
		gap: 0.5rem;
		align-items: center;
		padding: 0.75rem;
	}

	.lora-card.deleted {
		opacity: 0.5;
	}

	.lora-row {
		display: grid;
		grid-template-columns: 1fr auto auto auto auto;
		gap: 0.8rem;
		align-items: center;
		background: transparent;
		border: none;
		cursor: pointer;
		color: var(--text);
		text-align: left;
		padding: 0;
	}

	.lora-name {
		font-weight: 600;
		color: var(--text);
	}

	.status-badge {
		padding: 0.15rem 0.5rem;
		border-radius: 3px;
		font-size: 0.7rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.status-badge.good {
		background: var(--score-good);
		color: #fff;
	}

	.status-badge.bad {
		background: var(--score-bad);
		color: #fff;
	}

	.status-badge.active {
		background: linear-gradient(135deg, var(--primary), var(--accent));
		color: #fff;
	}

	.status-badge.neutral {
		background: var(--border);
		color: var(--text-muted);
	}

	.model-mode {
		padding: 0.15rem 0.5rem;
		border: 1px solid var(--accent);
		border-radius: 999px;
		background: color-mix(in srgb, var(--accent) 16%, transparent);
		color: var(--text);
		font-family: var(--font-display);
		font-size: 0.7rem;
		letter-spacing: 0.5px;
		text-transform: uppercase;
	}

	.sample-count {
		color: var(--text-subtle);
		font-size: 0.8rem;
	}

	.arrow {
		color: var(--text-decoration);
		font-size: 0.7rem;
		transition: transform 0.15s;
	}

	.arrow.open {
		transform: rotate(90deg);
	}

	.row-actions {
		display: flex;
		gap: 0.4rem;
	}

	.danger {
		padding: 0.3rem 0.7rem;
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: transparent;
		color: var(--text-muted);
		font-size: 0.75rem;
		cursor: pointer;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.danger:hover:not(:disabled) {
		border-color: var(--score-bad);
		color: var(--score-bad);
	}

	.danger:disabled {
		opacity: 0.3;
		cursor: not-allowed;
	}

	.deleted-tag {
		padding: 0.15rem 0.5rem;
		border: 1px dashed var(--score-bad);
		border-radius: 3px;
		font-size: 0.7rem;
		color: var(--score-bad);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		font-family: var(--font-display);
	}

	.detail-panel {
		grid-column: 1 / -1;
		padding-top: 0.75rem;
		border-top: 1px solid var(--border);
		margin-top: 0.25rem;
	}

	@media (max-width: 640px) {
		.lora-row {
			grid-template-columns: 1fr auto auto auto;
			font-size: 0.85rem;
		}

		.sample-count {
			display: none;
		}
	}
</style>
