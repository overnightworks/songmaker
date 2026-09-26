<script lang="ts">
	import {
		EDITOR_GENERATE_CANCEL_LABEL,
		EDITOR_GENERATE_FAILURE_COLLAPSE_LABEL,
		EDITOR_GENERATE_FAILURE_EXPAND_LABEL,
		EDITOR_GENERATE_MODE_LABELS,
		EDITOR_GENERATING_LABEL
	} from '$lib/constants';
	import {
		cancelGeneration,
		generate,
		generateAction,
		isGenerateBusy,
		type GenerateState
	} from '$lib/stores/generateAction';
	import { formatTime } from '$lib/utils/format';
	import Icon from '../Icon.svelte';

	const presentation: GenerateState = $derived($generateAction);
	let expanded = $state(false);
	const failureId = $props.id();

	$effect(() => {
		if (presentation.kind !== 'failed') expanded = false;
	});
</script>

<div class="generate-action">
	{#if isGenerateBusy(presentation)}
		<div class="progress-button" role="status">
			{#if presentation.kind === 'queued'}
				<span class="progress-label">{presentation.label}</span>
			{:else}
				<span class="progress-fill" style:width={`${presentation.progress}%`} aria-hidden="true"
				></span>
				<span class="progress-label">
					{presentation.takeCounter ?? EDITOR_GENERATING_LABEL}
					· {presentation.progress}%{#if typeof presentation.remaining === 'number'}
						{` · ~${formatTime(presentation.remaining)}`}
					{/if}
				</span>
			{/if}
		</div>
		{#if presentation.jobId !== null}
			{@const jobId = presentation.jobId}
			<button
				type="button"
				class="icon-button"
				data-hitbox="frequent"
				aria-label={EDITOR_GENERATE_CANCEL_LABEL}
				onclick={() => void cancelGeneration(jobId)}
			>
				<Icon name="x" />
			</button>
		{/if}
		{#if presentation.kind === 'queued' && presentation.reason}
			<p class="reason">{presentation.reason}</p>
		{/if}
	{:else}
		<button
			type="button"
			class="primary-button"
			class:failed={presentation.kind === 'failed'}
			disabled={presentation.kind === 'disabled'}
			title={presentation.kind === 'disabled' ? presentation.reason : undefined}
			onclick={() => void generate()}
		>
			{#if presentation.kind === 'failed'}<Icon name="triangle-alert" />{/if}
			{EDITOR_GENERATE_MODE_LABELS[presentation.mode]}
		</button>
		{#if presentation.kind === 'disabled'}
			<p class="reason"><span aria-hidden="true">ⓘ</span> {presentation.reason}</p>
		{:else if presentation.kind === 'failed'}
			<div class="failure" class:expanded>
				<p id={failureId} class="cause">{presentation.cause}</p>
				<button
					type="button"
					class="icon-button"
					data-hitbox="frequent"
					aria-label={expanded
						? EDITOR_GENERATE_FAILURE_COLLAPSE_LABEL
						: EDITOR_GENERATE_FAILURE_EXPAND_LABEL}
					aria-expanded={expanded}
					aria-controls={failureId}
					onclick={() => (expanded = !expanded)}
				>
					<Icon name={expanded ? 'chevron-up' : 'chevron-down'} />
				</button>
			</div>
		{/if}
	{/if}
</div>

<style>
	.generate-action {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--row-gap);
		min-width: 0;
		width: 100%;
	}

	.primary-button,
	.progress-button {
		display: flex;
		align-items: center;
		justify-content: center;
		flex: 1;
		min-width: 0;
		min-height: var(--hitbox-frequent);
		padding: var(--btn-padding-sm);
		border: 1px solid var(--primary);
		border-radius: var(--btn-radius-sm);
		font-family: var(--font-display);
		font-size: var(--btn-font-size);
		letter-spacing: var(--btn-letter-spacing);
	}

	.primary-button {
		gap: var(--row-gap);
		background: var(--primary);
		color: var(--surface);
		text-transform: uppercase;
		cursor: pointer;
	}

	.primary-button:disabled {
		background: none;
		border-color: var(--border);
		color: var(--text-disabled);
		cursor: default;
	}

	.primary-button.failed {
		background: none;
		border-color: var(--score-bad);
		color: var(--score-bad);
	}

	.progress-button {
		position: relative;
		overflow: hidden;
		border-color: var(--score-ok);
		background: var(--surface);
		color: var(--text);
	}

	.progress-fill {
		position: absolute;
		inset: 0 auto 0 0;
		background: color-mix(in srgb, var(--score-ok) 20%, transparent);
	}

	.progress-label {
		position: relative;
		text-align: center;
	}

	.icon-button {
		width: var(--hitbox-frequent);
		height: var(--hitbox-frequent);
		padding: 0;
		border: none;
		background: none;
		color: inherit;
		cursor: pointer;
	}

	.reason,
	.failure {
		flex: 0 0 100%;
		min-width: 0;
		margin: 0;
		font-size: var(--label-font-size);
		color: var(--text-muted);
		overflow-wrap: anywhere;
	}

	.failure {
		display: flex;
		align-items: center;
		color: var(--score-bad);
	}

	.cause {
		flex: 1;
		min-width: 0;
		margin: 0;
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
	}

	.failure.expanded {
		align-items: flex-start;
	}

	.expanded .cause {
		white-space: pre-wrap;
	}
</style>
