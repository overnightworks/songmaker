<script module lang="ts">
	import type { ListenReadState } from '#lib/stores/libraryOrder.ts';
	import type { WriteReadState } from '#lib/stores/libraryWrite.ts';
	export type HomeListPhase = 'loading' | 'failed' | 'empty' | 'rows';

	export function homeListPhase(
		readState: ListenReadState | WriteReadState,
		rowCount: number
	): HomeListPhase {
		if (readState === 'unread') return 'loading';
		if (readState === 'failed') return 'failed';
		return rowCount === 0 ? 'empty' : 'rows';
	}
</script>

<script lang="ts">
	import type { Snippet } from 'svelte';
	import { LIBRARY_RETRY_LABEL } from '#lib/constants.ts';

	type Props = {
		label: string;
		loadingText: string;
		errorText: string;
		emptyText: string;
		phase: HomeListPhase;
		onretry: () => void;
		// A list whose reader reports a pending read marks itself busy and holds Retry meanwhile.
		busy?: boolean;
		rows: Snippet;
	};
	let { label, loadingText, errorText, emptyText, phase, onretry, busy, rows }: Props = $props();
</script>

<section class="home-list" aria-label={label} aria-busy={busy}>
	<h2>{label}</h2>
	{#if phase === 'loading'}
		<p role="status">{loadingText}</p>
	{:else if phase === 'failed'}
		<div class="home-list-error" role="alert">
			<p>{errorText}</p>
			<button type="button" disabled={busy} onclick={onretry}>{LIBRARY_RETRY_LABEL}</button>
		</div>
	{:else if phase === 'empty'}
		<p>{emptyText}</p>
	{:else}
		{@render rows()}
	{/if}
</section>

<style>
	.home-list {
		padding: 12px 20px;
	}
	h2 {
		margin: 0 0 8px;
		font-size: 13px;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 1px;
	}
	p {
		margin: 0;
		color: var(--text-subtle);
		font-size: var(--label-font-size);
	}
	.home-list-error {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	button {
		border: 1px solid var(--border);
		border-radius: var(--btn-radius-sm);
		background: var(--surface);
		color: var(--text);
		font: inherit;
		padding: 4px 8px;
		cursor: pointer;
	}
	@media (max-width: 768px) {
		.home-list {
			padding: 12px;
		}
	}
</style>
