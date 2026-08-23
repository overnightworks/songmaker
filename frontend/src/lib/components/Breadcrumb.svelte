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
		font-size: 0.8rem;
		color: var(--text-muted);
	}

	/* A crumb shrinks to its ellipsis; a linked one stops at the hitbox
	   primitive's target, which stays clickable however narrow the trail. */
	.crumb:not(.crumb-link) {
		min-width: 0;
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

	/* The room a narrow trail needs comes off the path the reader has already
	   walked, not off the current crumb, which is the one they need — so a
	   link yields many times faster than the trail's destination. Saying it at
	   all is what matters: the hitbox primitive pins every `frequent` target,
	   so a link kept its full width and squeezed the current crumb out of the
	   trail entirely (#185). */
	.crumb-link {
		flex-shrink: 20;
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

	/* The destination the reader is already headed to must never lose
	   characters under normal pressure: it stops shrinking and caps its own
	   width instead, so a long title ellipsizes in place rather than
	   surrendering the room a link already gives up ahead of it (#185/2). */
	.crumb-current {
		color: var(--text);
		flex-shrink: 0;
		max-width: 60%;
	}
</style>
