<script lang="ts">
	export interface BreadcrumbItem {
		label: string;
		onclick?: () => void;
	}

	interface Props {
		items: BreadcrumbItem[];
	}

	let { items }: Props = $props();
</script>

<nav class="breadcrumb" aria-label="Breadcrumb">
	{#each items as item, index (index)}
		{#if index === items.length - 1}
			<span class="crumb crumb-current" aria-current="page"
				><span class="crumb-label">{item.label}</span></span
			>
		{:else if item.onclick}
			<button type="button" class="crumb crumb-link" data-hitbox="frequent" onclick={item.onclick}
				><span class="crumb-label">{item.label}</span></button
			>
		{:else}
			<span class="crumb"><span class="crumb-label">{item.label}</span></span>
		{/if}
	{/each}
</nav>

<style>
	.breadcrumb {
		display: flex;
		align-items: center;
		flex-wrap: nowrap;
		min-width: 0;
		overflow: hidden;
		gap: 0;
	}

	.crumb {
		display: inline-flex;
		align-items: center;
		min-width: 0;
		font-size: 0.8rem;
		color: var(--text-muted);
	}

	/* An inline-flex box cuts its overflow but never ellipsizes it, so the
	   label needs a block of its own to end in "…" rather than mid-letter. */
	.crumb-label {
		display: block;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.crumb:not(:first-child)::before {
		content: '›';
		margin: 0 0.35rem;
		color: var(--text-subtle);
		flex-shrink: 0;
	}

	/* A linked crumb gives room up like any other: pinned at its full width it
	   took the whole line from the current crumb, which is the one the reader
	   needs. The hitbox primitive pins every `frequent` target, so the trail
	   has to say otherwise here — it keeps the 24/44px target either way, and
	   the label ellipsizes into it (#185). */
	.crumb-link {
		flex-shrink: 1;
		background: none;
		border: none;
		padding: 0;
		font: inherit;
		color: var(--text-muted);
		cursor: pointer;
	}

	.crumb-link:hover {
		color: var(--primary);
		text-decoration: underline;
	}

	.crumb-current {
		color: var(--text);
	}
</style>
