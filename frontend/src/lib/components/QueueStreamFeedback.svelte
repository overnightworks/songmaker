<script lang="ts">
	import type { QueueStreamSkipItem } from '$lib/api/types';
	import Icon from './Icon.svelte';

	interface Props {
		skipped?: QueueStreamSkipItem[];
		skippedComplete?: boolean;
		windowEnded?: boolean;
	}

	let { skipped = [], skippedComplete = true, windowEnded = false }: Props = $props();
	const grouped = $derived.by(() => ({
		missing_path: skipped.filter((item) => item.reason === 'missing_path').length,
		missing_file: skipped.filter((item) => item.reason === 'missing_file').length,
		unreadable_file: skipped.filter((item) => item.reason === 'unreadable_file').length
	}));
	const hasFeedback = $derived(skipped.length > 0 || !skippedComplete || windowEnded);
	const summaryLabel = $derived(
		[
			skipped.length > 0 ? `${skipped.length} Takes übersprungen` : '',
			!skippedComplete ? 'Prüfung unvollständig' : '',
			windowEnded ? 'Stream-Ende' : ''
		]
			.filter(Boolean)
			.join(', ')
	);
</script>

{#if hasFeedback}
	<details class="feedback">
		<summary aria-label={summaryLabel}>
			{#if skipped.length > 0}
				<Icon name="triangle-alert" size={15} />
				<span>{skipped.length}{skippedComplete ? '' : '+'}</span>
			{:else if !skippedComplete}
				<Icon name="more-horizontal" size={16} />
			{:else if windowEnded}
				<Icon name="square" size={14} />
			{/if}
		</summary>
		<div class="feedback-details">
			{#if skipped.length > 0}
				{#if grouped.missing_path > 0}<span>{grouped.missing_path} ohne Audiodatei</span>{/if}
				{#if grouped.missing_file > 0}<span>{grouped.missing_file} Datei nicht gefunden</span>{/if}
				{#if grouped.unreadable_file > 0}<span>{grouped.unreadable_file} Datei nicht lesbar</span
					>{/if}
			{/if}
			{#if !skippedComplete}<span>Weitere Takes nicht geprüft</span>{/if}
			{#if windowEnded}<span>Weitere Takes nicht geladen</span>{/if}
		</div>
	</details>
{/if}

<style>
	.feedback {
		position: relative;
		min-width: 0;
		color: var(--text-muted);
		font-size: 0.72rem;
	}
	summary {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.28rem;
		min-width: 44px;
		min-height: 44px;
		padding: 0.25rem 0.45rem;
		border: 1px solid color-mix(in srgb, var(--border) 80%, transparent);
		border-radius: 999px;
		background: color-mix(in srgb, var(--surface) 70%, transparent);
		cursor: pointer;
		list-style: none;
	}
	summary::-webkit-details-marker {
		display: none;
	}
	summary span {
		white-space: nowrap;
	}
	summary:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 3px;
	}
	.feedback-details {
		position: fixed;
		right: 0.75rem;
		bottom: calc(var(--player-height, 88px) + 0.5rem);
		z-index: 110;
		display: grid;
		gap: 0.2rem;
		width: max-content;
		max-width: min(300px, calc(100vw - 1.5rem));
		padding: 0.5rem 0.65rem;
		background: var(--card-bg);
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		box-shadow: 0 8px 24px color-mix(in srgb, #000 35%, transparent);
		color: var(--text);
	}
	.feedback-details span {
		overflow-wrap: anywhere;
	}
</style>
