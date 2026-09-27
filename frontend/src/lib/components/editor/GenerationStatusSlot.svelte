<script lang="ts">
	import {
		EDITOR_GENERATE_CANCEL_LABEL,
		EDITOR_GENERATE_CANCEL_OFFLINE_LABEL,
		EDITOR_GENERATE_LAST_SEEN_PROGRESS_LABEL
	} from '$lib/constants';
	import {
		cancelGeneration,
		generateAction,
		isGenerateJobActive
	} from '$lib/stores/generateAction';
	import Icon from '../Icon.svelte';

	interface Props {
		latestVersionNumber: number;
	}

	let { latestVersionNumber }: Props = $props();

	const presentation = $derived($generateAction);
	const reconnecting = $derived(isGenerateJobActive(presentation) && presentation.reconnecting);
	const percent = $derived(presentation.kind === 'generating' ? presentation.progress : 0);
	const statusLineText = $derived.by(() => {
		if (presentation.kind !== 'generating') return null;
		const parts = [presentation.takeCounter, presentation.readout].filter((part) => part !== null);
		return parts.length > 0 ? parts.join(' · ') : null;
	});
</script>

{#if isGenerateJobActive(presentation)}
	<div class="status-slot" class:reconnecting>
		<div class="status-head">
			<span class="status-title">
				v{latestVersionNumber} ·
				<b>{presentation.kind === 'queued' ? presentation.label : presentation.phase}</b>
			</span>
			<button
				type="button"
				class="icon-button"
				data-hitbox="frequent"
				aria-label={reconnecting
					? EDITOR_GENERATE_CANCEL_OFFLINE_LABEL
					: EDITOR_GENERATE_CANCEL_LABEL}
				aria-disabled={reconnecting}
				onclick={() => {
					if (!reconnecting) void cancelGeneration(presentation.jobId);
				}}
			>
				<Icon name="x" />
			</button>
		</div>
		<div
			class="bar"
			role="progressbar"
			aria-label={reconnecting ? EDITOR_GENERATE_LAST_SEEN_PROGRESS_LABEL : undefined}
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

	/* Offline nothing about the take can arrive and a cancel cannot leave, so
	   the card stops looking live: its last state, in grey. */
	.reconnecting .status-title b {
		color: var(--text-light);
	}

	.reconnecting .bar span {
		background: var(--text-disabled);
	}

	.reconnecting .status-line {
		color: var(--text-subtle);
	}

	.reconnecting .icon-button {
		color: var(--text-disabled);
		cursor: default;
	}
</style>
