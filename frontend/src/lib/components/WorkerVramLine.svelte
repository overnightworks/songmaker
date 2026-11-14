<script lang="ts">
	import type { WorkerInfoItem } from '#lib/api/types.ts';
	import { formatDecimal } from '#lib/utils/format.ts';
	import { pageText } from '#lib/utils/page-words.ts';

	let { state, offline }: { state: WorkerInfoItem['state']; offline: boolean } = $props();
	const used = $derived(state?.vram_used_gb);
	const total = $derived(state?.vram_total_gb);
	const estimated = $derived(state?.vram_measured === false);
	const unknown = $derived(offline || used == null || total == null);
	const gigabytes = (usedGb: number, totalGb: number) => ({
		used: formatDecimal(usedGb, 1),
		total: formatDecimal(totalGb, 1)
	});
	const percentage = $derived(
		used != null && total != null && total > 0
			? Math.min(100, Math.max(0, (used / total) * 100))
			: 0
	);
</script>

<div class="vram-row" role="group" aria-label={pageText('workerPool.vram')}>
	<span class="label">{pageText('workerPool.vramLabel')}</span>
	<div class="vram">
		<div class="bar" class:estimated class:unknown aria-hidden="true">
			{#if !unknown}<span style:width={`${percentage}%`}></span>{/if}
		</div>
		{#if !unknown && used != null && total != null}
			<div class="numbers">
				<span
					>{pageText(
						estimated ? 'workerPool.vramUsedEstimated' : 'workerPool.vramUsed',
						gigabytes(used, total)
					)}</span
				>
				{#if !estimated}<span class="free"
						>{pageText('workerPool.vramFree', {
							free: formatDecimal(Math.max(0, total - used), 1)
						})}</span
					>{/if}
			</div>
			{#if estimated}<span class="reason">{pageText('workerPool.vramEstimateReason')}</span>{/if}
		{:else}
			<span class="unknown-text"
				><span class="ring" aria-hidden="true"></span>{pageText('workerPool.vramUnknown')}</span
			>
			<span class="reason"
				>{!state
					? pageText('workerPool.vramNoHeartbeat')
					: offline
						? pageText('workerPool.vramOffline')
						: used != null && total == null
							? pageText('workerPool.vramNoTotal')
							: pageText('workerPool.vramNoFields')}</span
			>
		{/if}
	</div>
</div>

<style>
	.vram-row {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		padding: 0.15rem 0;
	}
	.label {
		color: var(--text-muted);
		min-width: 5.5rem;
	}
	.vram {
		display: flex;
		flex-direction: column;
		flex: 1 1 12rem;
		min-width: 0;
		gap: 0.25rem;
	}
	.bar {
		height: 8px;
		border: 1px solid var(--border);
		border-radius: 2px;
		overflow: hidden;
		background: var(--surface);
	}
	.bar span {
		display: block;
		height: 100%;
		background: var(--text-muted);
	}
	.bar.estimated span {
		background: repeating-linear-gradient(135deg, var(--text-muted) 0 3px, transparent 3px 6px);
	}
	.bar.unknown {
		border-style: dashed;
		background: none;
	}
	.numbers {
		display: flex;
		align-items: baseline;
		gap: 0.25rem 0.45rem;
		font-size: 0.82rem;
		font-variant-numeric: tabular-nums;
	}
	.numbers > span {
		white-space: nowrap;
	}
	.free,
	.reason {
		color: var(--text-muted);
		font-size: 0.74rem;
	}
	.reason {
		overflow-wrap: anywhere;
	}
	.unknown-text {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		color: var(--text-muted);
	}
	.ring {
		width: 0.7rem;
		height: 0.7rem;
		border: 1px solid var(--text-muted);
		border-radius: 50%;
	}
</style>
