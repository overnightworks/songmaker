<script lang="ts">
	import { EDITOR_GENERATE_CANCEL_LABEL, EDITOR_GENERATING_LABEL } from '$lib/constants';
	import {
		cancelGeneration,
		generateAction,
		isGenerateJobActive
	} from '$lib/stores/generateAction';
	import { formatTime } from '$lib/utils/format';
	import Icon from '../Icon.svelte';

	interface Props {
		latestVersionNumber: number;
	}

	let { latestVersionNumber }: Props = $props();

	const presentation = $derived($generateAction);
	const percent = $derived(presentation.kind === 'generating' ? presentation.progress : 0);
	const statusLineText = $derived.by(() => {
		if (presentation.kind !== 'generating') return null;
		const parts: string[] = [];
		if (presentation.takeCounter) parts.push(presentation.takeCounter);
		parts.push(`${presentation.progress}%`);
		if (typeof presentation.remaining === 'number') {
			parts.push(`~${formatTime(presentation.remaining)}`);
		}
		return parts.join(' · ');
	});
</script>

{#if isGenerateJobActive(presentation)}
	<div class="status-slot">
		<div class="status-head">
			<span class="status-title">
				v{latestVersionNumber} ·
				<b>{presentation.kind === 'queued' ? presentation.label : EDITOR_GENERATING_LABEL}</b>
			</span>
			<button
				type="button"
				class="icon-button"
				data-hitbox="frequent"
				aria-label={EDITOR_GENERATE_CANCEL_LABEL}
				onclick={() => void cancelGeneration(presentation.jobId)}
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
		{#if presentation.kind === 'queued' && presentation.reason}
			<p class="status-line reason">{presentation.reason}</p>
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
