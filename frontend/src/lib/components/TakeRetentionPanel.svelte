<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { Marked } from 'overnightworks-design';
	import { describeFailure } from '#lib/api/fetch.ts';
	import { reloadWhileUnreachable } from '#lib/stores/connectivity.ts';
	import { addToast } from '#lib/stores/toast.ts';
	import {
		previewGenerationRetention,
		runGenerationRetention,
		type GenerationRetentionReport
	} from '#lib/api/client.ts';
	import { formatDecimal } from '#lib/utils/format.ts';
	import { pageParts, pageText } from '#lib/utils/page-words.ts';

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

	async function refreshPreview(): Promise<boolean> {
		loading = true;
		try {
			report = await previewGenerationRetention();
			previewReloads.stop();
			return true;
		} catch (e) {
			const failure = previewReloads.nameLoadFailure(e, pageText('takeRetention.previewFailed'));
			if (failure !== null) addToast(failure, 'error');
			return false;
		} finally {
			loading = false;
		}
	}

	async function askToRun(): Promise<void> {
		if ((await refreshPreview()) && !nothingDue) confirming = true;
	}

	async function execute(): Promise<void> {
		running = true;
		try {
			const outcome = await runGenerationRetention();
			addToast(
				pageText('takeRetention.outcome', {
					archived: formatDecimal(outcome.archived_count, 0),
					deleted: formatDecimal(outcome.deleted_count, 0)
				}),
				'success'
			);
			await refreshPreview();
		} catch (e) {
			addToast(describeFailure(e, pageText('takeRetention.runFailed')), 'error');
		} finally {
			running = false;
			confirming = false;
		}
	}
</script>

<section class="retention">
	<div class="head">
		<h2>{pageText('takeRetention.heading')}</h2>
		<span
			class="info-wrap"
			onmouseenter={() => (explaining = true)}
			onmouseleave={() => (explaining = false)}
			role="presentation"
		>
			<button
				type="button"
				class="info"
				aria-label={pageText('takeRetention.whatThisDoes')}
				aria-expanded={explaining}
				aria-describedby={explaining ? 'retention-explanation' : undefined}
				onclick={() => (explaining = !explaining)}>i</button
			>
			{#if explaining}
				<span id="retention-explanation" role="tooltip" class="explanation"
					>{pageText('takeRetention.explanation')}</span
				>
			{/if}
		</span>
		{#if report}
			<span class="auto">↻ {pageText('takeRetention.schedule', { hour: scheduleHour })}</span>
		{/if}
	</div>

	{#if loading && !report}
		<p class="dim">{pageText('takeRetention.loading')}</p>
	{:else if report}
		<div class="cards">
			<div class="card">
				<div class="number">{pageText('takeRetention.days', report.retention_days)}</div>
				<div class="label">{pageText('takeRetention.archiveAfter')}</div>
			</div>
			<div class="card">
				<div class="number">{pageText('takeRetention.days', report.hard_delete_days)}</div>
				<div class="label">{pageText('takeRetention.hardDeleteAfter')}</div>
			</div>
			<div class="card">
				<div class="number">{formatDecimal(report.archived_count, 0)}</div>
				<div class="label">{pageText('takeRetention.toArchive')}</div>
			</div>
			<div class="card danger">
				<div class="number">
					<span aria-hidden="true">▲</span>
					{formatDecimal(report.deleted_count, 0)}
				</div>
				<div class="label">{pageText('takeRetention.toHardDelete')}</div>
			</div>
		</div>

		{#if nothingDue}
			<p class="dim"><span aria-hidden="true">✓</span> {pageText('takeRetention.nothingDue')}</p>
		{:else if !confirming}
			<div class="actions">
				<button type="button" class="btn" onclick={refreshPreview} disabled={loading}
					>{pageText('takeRetention.refresh')}</button
				>
				<button type="button" class="btn danger" onclick={askToRun} disabled={loading}
					>{pageText('takeRetention.runNow')}</button
				>
			</div>
		{:else}
			<div class="confirm">
				<p>
					<Marked
						parts={pageParts('takeRetention.confirm', report.archived_count, {
							deleted: formatDecimal(report.deleted_count, 0)
						})}
						marked={{ strong }}
					/>
				</p>
				<div class="actions">
					<button type="button" class="btn" onclick={() => (confirming = false)} disabled={running}>
						{pageText('takeRetention.cancel')}
					</button>
					<button type="button" class="btn danger solid" onclick={execute} disabled={running}>
						{running
							? pageText('takeRetention.running')
							: pageText('takeRetention.delete', { count: report.deleted_count })}
					</button>
				</div>
			</div>
		{/if}
	{/if}
</section>

{#snippet strong({ text }: { text: string })}<strong>{text}</strong>{/snippet}

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
		border-color: var(--border);
	}

	.number {
		font-size: 1.3rem;
		font-weight: 600;
	}

	.card.danger .number {
		color: var(--text);
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
		border-color: var(--fail);
		color: var(--fail);
	}

	.btn.danger.solid {
		background: var(--fail);
		color: var(--on-fail);
	}

	.confirm {
		margin-top: 1.2rem;
		padding: 1rem;
		background: var(--fail-soft);
		border: 1px solid var(--fail);
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
