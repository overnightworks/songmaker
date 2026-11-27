<script lang="ts">
	import type { Snippet } from 'svelte';

	// The phone keeps its transport on the first screen: the title row, the
	// words in a region that scrolls on its own, then the card, the progress
	// bar and the transport.
	let {
		cover,
		meta,
		lyrics,
		judging,
		progress,
		transport
	}: {
		cover: Snippet;
		meta: Snippet;
		lyrics: Snippet;
		judging?: Snippet;
		progress: Snippet;
		transport: Snippet;
	} = $props();
</script>

<div class="phone-body">
	<div class="title-row">{@render cover()}{@render meta()}</div>
	<section class="lyrics-region">{@render lyrics()}</section>
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
		gap: 0.7rem;
		padding: 0.5rem 1rem 0.8rem;
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
		min-width: 0;
		align-items: flex-start;
		--ai-row-justify: flex-start;
		text-align: left;
	}
	.title-row :global(.cover-title) {
		overflow-wrap: anywhere;
	}
	/* The words take what the rest leaves and scroll inside it; below the floor
	   the body scrolls instead, so the lyrics never spill over the transport. */
	.lyrics-region {
		flex: 1 1 0;
		min-height: 6rem;
		display: flex;
		flex-direction: column;
	}
</style>
