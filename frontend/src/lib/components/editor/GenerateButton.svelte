<script lang="ts">
	import { resolve } from '$app/paths';
	import { isAdmin } from '$lib/stores/auth';
	import { followAppPageLink } from '$lib/stores/navigation';
	import {
		EDITOR_GENERATE_CANCEL_LABEL,
		EDITOR_GENERATE_CANCEL_OFFLINE_LABEL,
		EDITOR_GENERATE_LABEL,
		EDITOR_OPEN_WORKER_POOL_LABEL,
		ADMIN_WORKER_POOL_HREF
	} from '$lib/constants';
	import {
		cancelGeneration,
		generate,
		generateAction,
		isGenerateBusy,
		offersCancel,
		type GenerateState
	} from '$lib/stores/generateAction';
	import Icon from '../Icon.svelte';

	interface Props {
		// The phone's Generate bar is one slim row (#1011): a disabled Generate
		// explains itself inside its own outline box instead of on a line below.
		reasonInside?: boolean;
	}

	let { reasonInside = false }: Props = $props();

	const presentation: GenerateState = $derived($generateAction);
	const reconnecting: boolean = $derived(isGenerateBusy(presentation) && presentation.reconnecting);
	const cancelUnreachable: boolean = $derived(isGenerateBusy(presentation) && presentation.offline);
	const progressLabel: string | null = $derived(
		presentation.kind === 'generating'
			? [presentation.takeCounter, presentation.phase, presentation.readout]
					.filter((part) => part !== null)
					.join(' · ')
			: null
	);
	const reasonInsideButton: string | null = $derived(
		reasonInside && presentation.kind === 'disabled' ? presentation.reason : null
	);
</script>

{#snippet disabledReason(reason: string)}
	<span class="reason"><span aria-hidden="true">ⓘ</span> {reason}</span>
{/snippet}

<div class="generate-action">
	{#if isGenerateBusy(presentation)}
		<div class="progress-button" class:reconnecting role="status">
			{#if presentation.kind === 'queued'}
				<span class="progress-label">{presentation.label}</span>
			{:else}
				<span
					class="progress-fill"
					class:indeterminate={presentation.indeterminate}
					style:width={presentation.indeterminate ? undefined : `${presentation.progress}%`}
					aria-hidden="true"
				></span>
				<span class="progress-label"
					>{progressLabel}{#if presentation.indeterminate}<span
							class="elapsed-time"
							aria-hidden="true"
						>
							{presentation.elapsedLabel ? ` ${presentation.elapsedLabel}` : ''}</span
						>{/if}</span
				>
			{/if}
		</div>
		{#if offersCancel(presentation)}
			{@const jobId = presentation.jobId}
			<button
				type="button"
				class="icon-button"
				class:unreachable={cancelUnreachable}
				data-hitbox="frequent"
				aria-label={cancelUnreachable
					? EDITOR_GENERATE_CANCEL_OFFLINE_LABEL
					: EDITOR_GENERATE_CANCEL_LABEL}
				aria-disabled={cancelUnreachable}
				onclick={() => {
					if (!cancelUnreachable) void cancelGeneration(jobId);
				}}
			>
				<Icon name="x" />
			</button>
		{/if}
		{#if presentation.kind === 'queued' && presentation.reason}
			<p class="reason reason-below">{presentation.reason}</p>
		{/if}
	{:else}
		<button
			type="button"
			class="primary-button"
			class:failed={presentation.kind === 'failed'}
			disabled={presentation.kind === 'disabled'}
			title={presentation.kind === 'disabled' ? (presentation.reason ?? undefined) : undefined}
			aria-label={reasonInsideButton === null
				? undefined
				: `${EDITOR_GENERATE_LABEL} — ${reasonInsideButton}`}
			onclick={() => void generate()}
		>
			{#if reasonInsideButton !== null}
				{@render disabledReason(reasonInsideButton)}
			{:else}
				{#if presentation.kind === 'failed'}<Icon name="triangle-alert" />{/if}
				{EDITOR_GENERATE_LABEL}
			{/if}
		</button>
		{#if presentation.kind === 'disabled' && presentation.reason !== null && reasonInsideButton === null}
			<p class="reason-below">{@render disabledReason(presentation.reason)}</p>
		{:else if presentation.kind === 'failed'}
			<p class="failure">
				{presentation.cause}{#if presentation.unavailable && $isAdmin}
					<a
						href={resolve(ADMIN_WORKER_POOL_HREF)}
						onclick={(event) => followAppPageLink(event, ADMIN_WORKER_POOL_HREF)}
						>{EDITOR_OPEN_WORKER_POOL_LABEL}</a
					>
				{/if}
			</p>
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

	/* While nothing about the take can arrive the readout stops looking live:
	   its last state, in grey. Offline a cancel cannot leave, so it greys too. */
	.progress-button.reconnecting {
		border-color: var(--border);
		color: var(--text-subtle);
	}

	.reconnecting .progress-fill {
		background: color-mix(in srgb, var(--text-disabled) 20%, transparent);
	}

	.icon-button.unreachable {
		color: var(--text-disabled);
		cursor: default;
	}

	.progress-label {
		position: relative;
		text-align: center;
	}

	.elapsed-time {
		display: inline-block;
		min-width: 6ch;
		font-variant-numeric: tabular-nums;
		white-space: pre;
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

	.primary-button .reason {
		min-width: 0;
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
	}

	.reason-below,
	.failure {
		flex: 0 0 100%;
		min-width: 0;
		margin: 0;
		font-size: var(--label-font-size);
		color: var(--text-muted);
		overflow-wrap: anywhere;
	}

	.failure {
		margin-bottom: var(--row-gap);
		color: var(--score-bad);
		white-space: pre-wrap;
	}

	.failure a {
		color: var(--text-muted);
		margin-inline-start: var(--row-gap);
		white-space: normal;
		text-decoration: underline;
	}

	.progress-fill.indeterminate {
		width: 35%;
		background: linear-gradient(
			90deg,
			transparent,
			color-mix(in srgb, var(--score-ok) 38%, transparent),
			transparent
		);
		transform: translateX(95%);
		animation: stage-sweep 2.6s ease-in-out infinite;
	}

	@keyframes stage-sweep {
		from {
			transform: translateX(-100%);
		}
		to {
			transform: translateX(290%);
		}
	}

	.reconnecting .progress-fill.indeterminate {
		animation: none;
		background: color-mix(in srgb, var(--text-disabled) 20%, transparent);
	}

	@media (prefers-reduced-motion: reduce) {
		.progress-fill.indeterminate {
			animation: none;
		}
	}
</style>
