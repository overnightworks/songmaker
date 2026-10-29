<script lang="ts">
	import type { WorkerInfoItem } from '#lib/api/types.ts';
	import {
		WORKER_POOL_VRAM_LABEL,
		WORKER_POOL_VRAM_OFFLINE,
		WORKER_POOL_VRAM_UNKNOWN,
		WORKER_POOL_VRAM_ESTIMATE,
		WORKER_POOL_VRAM_FREE,
		WORKER_POOL_VRAM_ESTIMATE_REASON,
		WORKER_POOL_VRAM_NO_HEARTBEAT,
		WORKER_POOL_VRAM_NO_FIELDS,
		WORKER_POOL_VRAM_NO_TOTAL
	} from '#lib/constants.ts';

	let { state, offline }: { state: WorkerInfoItem['state']; offline: boolean } = $props();
	const used = $derived(state?.vram_used_gb);
	const total = $derived(state?.vram_total_gb);
	const estimated = $derived(state?.vram_measured === false);
	const unknown = $derived(offline || used == null || total == null);
	const percentage = $derived(
		used != null && total != null && total > 0
			? Math.min(100, Math.max(0, (used / total) * 100))
			: 0
	);
</script>

<div class="vram-row" role="group" aria-label={WORKER_POOL_VRAM_LABEL}>
	<span class="label">{WORKER_POOL_VRAM_LABEL}:</span>
	<div class="vram">
		<div class="bar" class:estimated class:unknown aria-hidden="true">
			{#if !unknown}<span style:width={`${percentage}%`}></span>{/if}
		</div>
		{#if !unknown && used != null && total != null}
			<div class="numbers">
				<span
					>{estimated ? '~' : ''}{used.toFixed(1)} / {total.toFixed(1)} GB{estimated
						? ` ${WORKER_POOL_VRAM_ESTIMATE}`
						: ''}</span
				>
				{#if !estimated}<span class="free"
						>{Math.max(0, total - used).toFixed(1)} {WORKER_POOL_VRAM_FREE}</span
					>{/if}
			</div>
			{#if estimated}<span class="reason">{WORKER_POOL_VRAM_ESTIMATE_REASON}</span>{/if}
		{:else}
			<span class="unknown-text"
				><span class="ring" aria-hidden="true"></span>{WORKER_POOL_VRAM_UNKNOWN}</span
			>
			<span class="reason"
				>{!state
					? WORKER_POOL_VRAM_NO_HEARTBEAT
					: offline
						? WORKER_POOL_VRAM_OFFLINE
						: used != null && total == null
							? WORKER_POOL_VRAM_NO_TOTAL
							: WORKER_POOL_VRAM_NO_FIELDS}</span
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
