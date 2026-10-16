<script module lang="ts">
	// The legal texts LegalContent shows, in the order every page links them.
	export const LEGAL_SECTIONS = [
		{ id: 'impressum', label: 'Impressum' },
		{ id: 'datenschutz', label: 'Datenschutz' },
		{ id: 'nutzungsbedingungen', label: 'Nutzungsbedingungen' }
	] as const;

	export type LegalSection = (typeof LEGAL_SECTIONS)[number]['id'];
</script>

<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- static SPA, no base path */
	import type { Snippet } from 'svelte';

	interface Props {
		// A page that must not be left — a share page keeps playing — opens
		// the text over itself; without this, each link goes to /legal.
		onopen?: (section: LegalSection) => void;
		// What stands before the links in the same row, such as "Powered by".
		lead?: Snippet;
	}

	let { onopen, lead }: Props = $props();
</script>

<p class="legal-links">
	{#if lead}<span class="legal-item">{@render lead()}</span>{/if}
	{#each LEGAL_SECTIONS as section (section.id)}
		<span class="legal-item">
			{#if onopen}
				<button type="button" class="legal-link" onclick={() => onopen(section.id)}
					>{section.label}</button
				>
			{:else}
				<a class="legal-link" href="/legal#{section.id}">{section.label}</a>
			{/if}
		</span>
	{/each}
</p>

<style>
	.legal-links {
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		margin: 0;
	}

	/* The dot is drawn, not written, and only before an item that follows
	   another, so a wrapped row never starts or ends on one. */
	.legal-item:not(:first-child)::before {
		content: '·';
		margin: 0 0.35em;
	}

	.legal-link {
		padding: 0;
		border: none;
		background: none;
		font: inherit;
		color: var(--text-muted);
		text-decoration: none;
		cursor: pointer;
		transition: color 0.2s;
	}

	.legal-link:hover {
		color: var(--text);
	}
</style>
