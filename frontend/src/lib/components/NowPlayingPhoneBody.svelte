<script lang="ts">
	import type { Snippet } from 'svelte';

	// The phone keeps its transport on the first screen: the title row, the
	// words in a region that scrolls on its own, then the scores, the card, the
	// progress bar and the transport.
	let {
		cover,
		meta,
		lyrics,
		judging,
		scores,
		progress,
		transport
	}: {
		cover: Snippet;
		meta: Snippet;
		lyrics: Snippet;
		judging?: Snippet;
		scores?: Snippet;
		progress: Snippet;
		transport: Snippet;
	} = $props();
</script>

<div class="phone-body">
	<div class="title-row">{@render cover()}{@render meta()}</div>
	<section class="lyrics-region">{@render lyrics()}</section>
	{@render scores?.()}
	{@render judging?.()}
	{@render progress()}
	{@render transport()}
</div>

<style>
	.phone-body {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		padding: 0.5rem 1rem 0.5rem;
		overflow-y: auto;
	}
	.title-row {
		flex-shrink: 0;
		display: flex;
		align-items: center;
		gap: 0.8rem;
	}
	.title-row :global(.cover-art) {
		flex-shrink: 0;
		width: 56px;
		box-shadow: none;
	}
	.title-row :global(.cover-meta) {
		flex: 1;
		min-width: 0;
		width: auto;
	}
	/* The words take what the rest leaves and scroll inside it; below the floor
	   the body scrolls instead, so the lyrics never spill over the transport. */
	.lyrics-region {
		flex: 1 1 0;
		min-height: 4rem;
		display: flex;
		flex-direction: column;
	}
	.lyrics-region :global(.np-lyrics) {
		min-height: 0;
	}
	/* The chips stay one row high, however many scores the take has; the row
	   swipes sideways instead of taking a second line from the words. */
	.phone-body :global(.scores.chips) {
		flex-wrap: nowrap;
		overflow-x: auto;
		scrollbar-width: none;
	}
	.phone-body :global(.scores.chips .entries) {
		flex-wrap: nowrap;
	}
	/* The pending word leads the row, so it stands on screen without a swipe. */
	.phone-body :global(.scores.chips .note) {
		order: -1;
	}
	.phone-body :global(.scores.chips > *),
	.phone-body :global(.scores.chips .entry) {
		flex: none;
		white-space: nowrap;
	}
</style>
