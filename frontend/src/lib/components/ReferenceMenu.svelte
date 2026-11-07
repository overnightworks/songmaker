<script lang="ts">
	import { COLLECTION_MENU_CLOSE_LABEL } from '#lib/constants.ts';
	import Icon from './Icon.svelte';
	import MenuPopover from './MenuPopover.svelte';

	const MENU_LABEL = 'Reference menu';
	const SHOW_TAKES_LABEL = 'Show takes';
	const DELETE_LABEL = 'Delete';
	const IN_USE_HINT = 'In use';

	let {
		filename,
		inUse,
		usesCount,
		onshowuses,
		ondelete
	}: {
		filename: string;
		inUse: boolean;
		usesCount: number;
		onshowuses: () => void;
		ondelete: () => void;
	} = $props();

	let popover: MenuPopover | undefined = $state();
</script>

<MenuPopover
	bind:this={popover}
	layer="reference-menu"
	label={MENU_LABEL}
	closeLabel={COLLECTION_MENU_CLOSE_LABEL}
>
	{#snippet trigger()}<Icon name="more-horizontal" size={18} />{/snippet}
	<p class="menu-heading">{filename}</p>
	{#if inUse}
		<button
			class="menu-item"
			onclick={() => {
				popover?.close();
				onshowuses();
			}}
		>
			{SHOW_TAKES_LABEL}
			<span class="menu-item-hint">{usesCount}</span>
		</button>
	{/if}
	<button
		class="menu-item destructive"
		disabled={inUse}
		onclick={() => {
			popover?.close();
			ondelete();
		}}
	>
		<Icon name="trash" size={14} />
		{DELETE_LABEL}
		{#if inUse}<span class="menu-item-hint">{IN_USE_HINT}</span>{/if}
	</button>
</MenuPopover>

<style>
	.menu-heading {
		margin: 0 0 0.25rem;
		padding: 0.3rem 0.6rem 0.5rem;
		font-family: var(--font-display);
		font-size: 11px;
		letter-spacing: 0.5px;
		color: var(--text-subtle);
		border-bottom: 1px solid var(--border);
		overflow-wrap: anywhere;
	}

	.menu-item {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		width: 100%;
		min-height: var(--hitbox-frequent);
		padding: 0.5rem 0.6rem;
		border-radius: var(--btn-radius-sm);
		font-size: 13px;
		background: none;
		border: none;
		text-align: left;
		cursor: pointer;
	}

	.menu-item-hint {
		margin-left: auto;
		font-size: 11px;
		color: var(--text-subtle);
	}

	.menu-item:hover:not(:disabled) {
		background: var(--surface-hover);
	}

	.menu-item:disabled {
		color: var(--text-disabled);
		cursor: default;
	}

	.menu-item.destructive:not(:disabled) {
		color: var(--fail);
	}
</style>
