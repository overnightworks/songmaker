<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { isAdmin } from '$lib/stores/auth';
	import { addToast } from '$lib/stores/toast';
	import {
		previewGenerationRetention,
		runGenerationRetention,
		type GenerationRetentionReport
	} from '$lib/api/client';

	let report = $state<GenerationRetentionReport | null>(null);
	let loading = $state(false);
	let running = $state(false);
	let confirming = $state(false);

	onMount(() => {
		if (!$isAdmin) {
			goto('/settings');
			return;
		}
		refreshPreview();
	});

	async function refreshPreview(): Promise<void> {
		loading = true;
		try {
			report = await previewGenerationRetention();
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Preview failed', 'error');
		} finally {
			loading = false;
		}
	}

	async function execute(): Promise<void> {
		running = true;
		try {
			report = await runGenerationRetention();
			addToast(`Archived ${report.archived_count}, deleted ${report.deleted_count}`, 'success');
		} catch (e) {
			addToast(e instanceof Error ? e.message : 'Cleanup failed', 'error');
		} finally {
			running = false;
			confirming = false;
		}
	}
</script>

<div class="page">
	<h1>Generation Retention</h1>
	<p class="hint">
		Generations that are neither <strong>picked</strong> nor <strong>kept</strong> are auto-archived after
		the retention window, then permanently deleted after the hard-delete window. This cleanup also runs
		automatically every day at 03:00 UTC.
	</p>

	{#if loading && !report}
		<p class="dim">Loading preview…</p>
	{:else if report}
		<div class="windows">
			<div class="window-card">
				<div class="window-label">Archive after</div>
				<div class="window-value">{report.retention_days} days</div>
			</div>
			<div class="window-card">
				<div class="window-label">Hard-delete after archive</div>
				<div class="window-value">{report.hard_delete_days} days</div>
			</div>
		</div>

		<div class="counts">
			<div class="count-card">
				<div class="count-number">{report.archived_count}</div>
				<div class="count-label">to archive now</div>
			</div>
			<div class="count-card danger">
				<div class="count-number">{report.deleted_count}</div>
				<div class="count-label">to hard-delete now</div>
			</div>
		</div>

		{#if report.archived_count === 0 && report.deleted_count === 0}
			<p class="dim">Nothing to clean up right now.</p>
		{:else if !confirming}
			<div class="actions">
				<button class="btn" onclick={refreshPreview} disabled={loading}>Refresh preview</button>
				<button class="btn danger" onclick={() => (confirming = true)}> Run cleanup now </button>
			</div>
		{:else}
			<div class="confirm">
				<p>
					Archive <strong>{report.archived_count}</strong> generation{report.archived_count === 1
						? ''
						: 's'}
					and permanently delete <strong>{report.deleted_count}</strong> archived one{report.deleted_count ===
					1
						? ''
						: 's'}? Hard-deletion is not reversible.
				</p>
				<div class="actions">
					<button class="btn" onclick={() => (confirming = false)} disabled={running}>
						Cancel
					</button>
					<button class="btn danger" onclick={execute} disabled={running}>
						{running ? 'Running…' : 'Confirm cleanup'}
					</button>
				</div>
			</div>
		{/if}

		{#if report.deleted_ids.length > 0}
			<details class="ids">
				<summary>{report.deleted_ids.length} generation ids to hard-delete</summary>
				<ul>
					{#each report.deleted_ids as id (id)}
						<li><code>{id}</code></li>
					{/each}
				</ul>
			</details>
		{/if}

		{#if report.archived_ids.length > 0}
			<details class="ids">
				<summary>{report.archived_ids.length} generation ids to archive</summary>
				<ul>
					{#each report.archived_ids as id (id)}
						<li><code>{id}</code></li>
					{/each}
				</ul>
			</details>
		{/if}
	{/if}
</div>

<style>
	.page {
		padding: 1.5rem 2rem;
		max-width: 800px;
	}

	h1 {
		margin-top: 0;
	}

	.hint {
		color: var(--text-muted);
		font-size: 0.9rem;
		line-height: 1.5;
	}

	.dim {
		color: var(--text-muted);
	}

	.windows {
		display: flex;
		flex-wrap: wrap;
		gap: 1rem;
		margin: 1.5rem 0;
	}

	.window-card {
		flex: 1 1 8rem;
		min-width: 0;
		padding: 0.8rem 1rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
	}

	.window-label {
		font-size: 0.7rem;
		text-transform: uppercase;
		color: var(--text-muted);
		letter-spacing: 0.5px;
	}

	.window-value {
		font-size: 1.2rem;
		font-weight: 600;
		margin-top: 0.2rem;
	}

	.counts {
		display: flex;
		flex-wrap: wrap;
		gap: 1rem;
		margin: 1.5rem 0;
	}

	.count-card {
		flex: 1 1 8rem;
		min-width: 0;
		padding: 1rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		text-align: center;
	}

	.count-card.danger {
		border-color: rgba(200, 60, 60, 0.5);
	}

	.count-number {
		font-size: 2rem;
		font-weight: 600;
	}

	.count-card.danger .count-number {
		color: #e07070;
	}

	.count-label {
		font-size: 0.8rem;
		color: var(--text-muted);
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.8rem;
		justify-content: flex-end;
		margin-top: 1rem;
	}

	.btn {
		padding: 0.5rem 1rem;
		border: 1px solid var(--border);
		background: var(--surface);
		color: var(--text);
		border-radius: 3px;
		cursor: pointer;
		font-size: 0.85rem;
	}

	.btn:hover:not(:disabled) {
		border-color: var(--accent);
	}

	.btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.btn.danger {
		border-color: rgba(200, 60, 60, 0.6);
		color: #e07070;
	}

	.btn.danger:hover:not(:disabled) {
		background: rgba(200, 60, 60, 0.1);
	}

	.confirm {
		margin-top: 1.5rem;
		padding: 1rem;
		background: rgba(200, 60, 60, 0.08);
		border: 1px solid rgba(200, 60, 60, 0.4);
		border-radius: 4px;
	}

	.confirm p {
		margin: 0 0 1rem 0;
		font-size: 0.9rem;
	}

	.ids {
		margin-top: 1.5rem;
		font-size: 0.8rem;
	}

	.ids summary {
		cursor: pointer;
		color: var(--text-muted);
	}

	.ids ul {
		list-style: none;
		padding-left: 0;
		margin-top: 0.5rem;
		max-height: 300px;
		overflow-y: auto;
	}

	.ids li {
		padding: 0.2rem 0;
		font-family: monospace;
		color: var(--text-muted);
	}
</style>
