<script lang="ts">
	import type { JobItem } from '$lib/api/types';
	import { cancelJob } from '$lib/api/client';
	import {
		EDITOR_GENERATE_CANCEL_FAILED,
		EDITOR_GENERATE_CANCEL_LABEL,
		EDITOR_GENERATE_QUEUED_TEMPLATE,
		EDITOR_GENERATE_TAKE_TEMPLATE,
		EDITOR_GENERATING_LABEL,
		EDITOR_QUEUED_LABEL
	} from '$lib/constants';
	import { addToast } from '$lib/stores/toast';
	import { formatTime } from '$lib/utils/format';
	import Icon from '../Icon.svelte';

	interface Props {
		job: JobItem | null;
		latestVersionNumber: number;
	}

	let { job, latestVersionNumber }: Props = $props();

	const running = $derived(job !== null && (job.status === 'queued' || job.status === 'running'));
	const percent = $derived(job ? Math.round(job.progress * 100) : 0);
	const queueLabel = $derived.by(() => {
		const position = job?.queue_position ?? null;
		return position === null
			? EDITOR_QUEUED_LABEL
			: EDITOR_GENERATE_QUEUED_TEMPLATE.replace('{position}', String(position));
	});
	const takeCounter = $derived.by(() => {
		if (job?.take_index == null || job?.take_count == null || job.take_count <= 1) return null;
		return EDITOR_GENERATE_TAKE_TEMPLATE.replace('{index}', String(job.take_index)).replace(
			'{count}',
			String(job.take_count)
		);
	});

	async function cancel(): Promise<void> {
		if (!job) return;
		try {
			await cancelJob(job.id);
		} catch (error) {
			addToast(error instanceof Error ? error.message : EDITOR_GENERATE_CANCEL_FAILED, 'error');
		}
	}
</script>

{#if job && running}
	<div class="status-slot" role="status">
		<div class="status-head">
			<span class="status-title">
				v{latestVersionNumber} ·
				<b>{job.status === 'queued' ? EDITOR_QUEUED_LABEL : EDITOR_GENERATING_LABEL}</b>
			</span>
			<button
				type="button"
				class="icon-button"
				data-hitbox="frequent"
				aria-label={EDITOR_GENERATE_CANCEL_LABEL}
				onclick={() => void cancel()}
			>
				<Icon name="x" />
			</button>
		</div>
		<div
			class="bar"
			role="progressbar"
			aria-valuenow={percent}
			aria-valuemin={0}
			aria-valuemax={100}
		>
			<span style:width={`${percent}%`}></span>
		</div>
		<p class="status-line">
			{#if job.status === 'queued'}
				{queueLabel}
			{:else}
				{takeCounter ?? EDITOR_GENERATING_LABEL} · {percent}%{#if typeof job.remaining_time_estimate === 'number'}
					{` · ~${formatTime(job.remaining_time_estimate)}`}
				{/if}
			{/if}
		</p>
		{#if job.queue_reason}
			<p class="status-line reason">{job.queue_reason}</p>
		{/if}
	</div>
{/if}

<style>
	.status-slot {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		padding: 0.4rem 0.6rem;
		background: var(--surface);
		border: 1px dashed var(--border);
		border-radius: var(--card-radius);
	}

	.status-head {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.status-title {
		flex: 1;
		min-width: 0;
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		font-family: var(--font-display);
		letter-spacing: 0.4px;
		font-size: var(--btn-font-size-sm);
		color: var(--text-muted);
	}

	.status-title b {
		font-weight: 500;
		color: var(--score-ok);
	}

	.icon-button {
		width: var(--hitbox-frequent);
		height: var(--hitbox-frequent);
		flex-shrink: 0;
		padding: 0;
		border: none;
		background: none;
		color: var(--text-muted);
		cursor: pointer;
	}

	.bar {
		height: 4px;
		background: var(--border);
		border-radius: 2px;
		overflow: hidden;
	}

	.bar span {
		display: block;
		height: 100%;
		background: var(--score-ok);
		transition: width 0.3s ease;
	}

	.status-line {
		margin: 0;
		font-size: var(--label-font-size);
		color: var(--text-muted);
	}

	.status-line.reason {
		color: var(--text-subtle);
	}
</style>
