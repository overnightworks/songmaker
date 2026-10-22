<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve -- external addresses, not app routes */
	import type { Snippet } from 'svelte';
	import { LEGAL_SECTIONS } from '$lib/constants/legal';

	interface Props {
		// A page that must not be left — a share page keeps playing — opens
		// the texts in a new tab.
		newTab?: boolean;
		// What stands before the links in the same row, such as "Powered by".
		lead?: Snippet;
	}

	let { newTab = false, lead }: Props = $props();
</script>

<p class="legal-links">
	{#if lead}<span class="legal-item">{@render lead()}</span>{/if}
	{#each LEGAL_SECTIONS as section (section.label)}
		<span class="legal-item">
			<a
				class="legal-link"
				href={section.href}
				target={newTab ? '_blank' : undefined}
				rel={newTab ? 'noopener' : undefined}>{section.label}</a
			>
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
		font: inherit;
		color: var(--text-muted);
		text-decoration: none;
		transition: color 0.2s;
	}

	.legal-link:hover {
		color: var(--text);
	}
</style>
