<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { describeFailure } from '$lib/api/fetch';
	import { reloadWhileUnreachable } from '$lib/stores/connectivity';
	import { addToast } from '$lib/stores/toast';
	import {
		previewGenerationRetention,
		runGenerationRetention,
		type GenerationRetentionReport
	} from '$lib/api/client';

	const RETENTION_EXPLANATION =
		'Takes that are neither picked nor kept are archived after the retention window, then permanently deleted after the hard-delete window.';

	let report = $state<GenerationRetentionReport | null>(null);
	let loading = $state(false);
	let running = $state(false);
	let confirming = $state(false);
	let explaining = $state(false);
	const previewReloads = reloadWhileUnreachable(() => void refreshPreview());

	const nothingDue = $derived(
		report !== null && report.archived_count + report.deleted_count === 0
	);
	const scheduleHour = $derived(String(report?.scheduled_hour_utc ?? 0).padStart(2, '0'));

	onMount(() => void refreshPreview());
	onDestroy(() => previewReloads.stop());

	function takes(count: number): string {
		return `${count} take${count === 1 ? '' : 's'}`;
	}

	async function refreshPreview(): Promise<void> {
		loading = true;
		try {
			report = await previewGenerationRetention();
			previewReloads.stop();
		} catch (e) {
			const failure = previewReloads.nameLoadFailure(e, 'Preview failed');
			if (failure !== null) addToast(failure, 'error');
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
			addToast(describeFailure(e, 'Cleanup failed'), 'error');
		} finally {
			running = false;
			confirming = false;
		}
	}
</script>

<section class="retention">
	<div class="head">
		<h2>Take Retention</h2>
		<span
			class="info-wrap"
			onmouseenter={() => (explaining = true)}
			onmouseleave={() => (explaining = false)}
			role="presentation"
		>
			<button
				type="button"
				class="info"
				aria-label="What this does"
				aria-expanded={explaining}
				aria-describedby={explaining ? 'retention-explanation' : undefined}
				onclick={() => (explaining = !explaining)}>i</button
			>
			{#if explaining}
				<span id="retention-explanation" role="tooltip" class="explanation"
					>{RETENTION_EXPLANATION}</span
				>
			{/if}
		</span>
		{#if report}
			<span class="auto">↻ Auto · daily {scheduleHour}:00 UTC</span>
		{/if}
	</div>

	{#if loading && !report}
		<p class="dim">Loading preview…</p>
	{:else if report}
		<div class="cards">
			<div class="card">
				<div class="number">{report.retention_days} days</div>
				<div class="label">Archive after</div>
			</div>
			<div class="card">
				<div class="number">{report.hard_delete_days} days</div>
				<div class="label">Hard-delete after archive</div>
			</div>
			<div class="card">
				<div class="number">{report.archived_count}</div>
				<div class="label">to archive now</div>
			</div>
			<div class="card danger">
				<div class="number"><span aria-hidden="true">▲</span> {report.deleted_count}</div>
				<div class="label">to hard-delete now</div>
			</div>
		</div>

		{#if nothingDue}
			<p class="dim"><span aria-hidden="true">✓</span> Nothing to clean up right now</p>
		{:else if !confirming}
			<div class="actions">
				<button type="button" class="btn" onclick={refreshPreview} disabled={loading}
					>Refresh</button
				>
				<button type="button" class="btn danger" onclick={() => (confirming = true)}>Run now</button
				>
			</div>
		{:else}
			<div class="confirm">
				<p>
					Archive <strong>{takes(report.archived_count)}</strong> and permanently delete
					<strong>{report.deleted_count}</strong>. Deleting cannot be undone.
				</p>
				<div class="actions">
					<button type="button" class="btn" onclick={() => (confirming = false)} disabled={running}>
						Cancel
					</button>
					<button type="button" class="btn danger solid" onclick={execute} disabled={running}>
						{running ? 'Running…' : `Delete ${report.deleted_count}`}
					</button>
				</div>
			</div>
		{/if}
	{/if}
</section>

<style>
	.head {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.6rem;
	}

	h2 {
		margin: 0;
		font-size: 1.1rem;
	}

	.info-wrap {
		position: relative;
		display: inline-flex;
	}

	.info {
		width: 1.4rem;
		height: 1.4rem;
		padding: 0;
		border: 1px solid var(--border);
		border-radius: 50%;
		background: none;
		color: var(--text-muted);
		font-size: 0.75rem;
		font-style: italic;
		cursor: pointer;
	}

	.explanation {
		position: absolute;
		top: 1.9rem;
		left: 0;
		z-index: 5;
		width: min(18rem, 80vw);
		padding: 0.6rem 0.8rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 0.8rem;
		line-height: 1.4;
	}

	.auto {
		margin-left: auto;
		padding: 0.15rem 0.55rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		color: var(--text-muted);
		font-size: 0.75rem;
	}

	.dim {
		color: var(--text-muted);
	}

	.cards {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
		gap: 0.8rem;
		margin: 1.2rem 0;
	}

	.card {
		padding: 0.8rem 1rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
	}

	.card.danger {
		border-color: var(--score-bad);
	}

	.number {
		font-size: 1.3rem;
		font-weight: 600;
	}

	.card.danger .number {
		color: var(--score-bad);
	}

	.label {
		margin-top: 0.2rem;
		font-size: 0.75rem;
		color: var(--text-muted);
	}

	.actions {
		display: flex;
		gap: 0.8rem;
		justify-content: flex-end;
		margin-top: 1rem;
	}

	.btn {
		min-height: var(--hitbox-frequent);
		padding: 0 1rem;
		border: 1px solid var(--border);
		background: var(--surface);
		color: var(--text);
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.85rem;
	}

	.btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.btn.danger {
		border-color: var(--score-bad);
		color: var(--score-bad);
	}

	.btn.danger.solid {
		background: var(--score-bad);
		color: var(--bg);
	}

	.confirm {
		margin-top: 1.2rem;
		padding: 1rem;
		background: var(--score-bad-bg);
		border: 1px solid var(--score-bad);
		border-radius: 4px;
	}

	.confirm p {
		margin: 0;
		font-size: 0.9rem;
	}

	@media (max-width: 600px) {
		.actions .btn {
			flex: 1;
		}

		.cards {
			grid-template-columns: repeat(2, 1fr);
		}
	}
</style>
