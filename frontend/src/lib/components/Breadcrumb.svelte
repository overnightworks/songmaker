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
			<span class="crumb crumb-current" aria-current="page">{item.label}</span>
		{:else if item.onclick}
			<button type="button" class="crumb crumb-link" onclick={item.onclick}>{item.label}</button>
		{:else}
			<span class="crumb">{item.label}</span>
		{/if}
	{/each}
</nav>

<style>
	.breadcrumb {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		min-width: 0;
		gap: 0;
	}

	.crumb {
		display: inline-flex;
		align-items: center;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 0.8rem;
		color: var(--text-muted);
	}

	.crumb:not(:first-child)::before {
		content: '›';
		margin: 0 0.35rem;
		color: var(--text-subtle);
		flex-shrink: 0;
	}

	.crumb-link {
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
