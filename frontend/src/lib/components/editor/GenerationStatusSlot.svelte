<script lang="ts">
	import type { JobItem } from '$lib/api/types';
	import {
		EDITOR_GENERATE_CANCEL_LABEL,
		EDITOR_GENERATE_TAKE_TEMPLATE,
		EDITOR_GENERATING_LABEL,
		EDITOR_QUEUED_LABEL
	} from '$lib/constants';
	import { cancelGeneration, progressPercent } from '$lib/stores/generateAction';
	import { formatTime } from '$lib/utils/format';
	import Icon from '../Icon.svelte';

	interface Props {
		job: JobItem | null;
		latestVersionNumber: number;
	}

	let { job, latestVersionNumber }: Props = $props();

	const running = $derived(job !== null && (job.status === 'queued' || job.status === 'running'));
	const percent = $derived(progressPercent(job));
	const takeCounter = $derived.by(() => {
		if (job?.take_index == null || job?.take_count == null || job.take_count <= 1) return null;
		return EDITOR_GENERATE_TAKE_TEMPLATE.replace('{index}', String(job.take_index)).replace(
			'{count}',
			String(job.take_count)
		);
	});
	const statusLineText = $derived.by(() => {
		if (!job) return null;
		if (job.status === 'queued') {
			const position = job.queue_position ?? null;
			return position !== null ? `#${position}` : null;
		}
		const parts: string[] = [];
		if (takeCounter) parts.push(takeCounter);
		parts.push(`${percent}%`);
		if (typeof job.remaining_time_estimate === 'number') {
			parts.push(`~${formatTime(job.remaining_time_estimate)}`);
		}
		return parts.join(' · ');
	});
</script>

{#if job && running}
	<div class="status-slot">
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
				onclick={() => void cancelGeneration(job.id)}
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
		{#if statusLineText}
			<p class="status-line">{statusLineText}</p>
		{/if}
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
