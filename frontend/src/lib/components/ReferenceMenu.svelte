<script lang="ts">
	import { pageText } from '#lib/utils/page-words.ts';
	import Icon from './Icon.svelte';
	import MenuPopover from './MenuPopover.svelte';

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
	label={pageText('referenceMenu.label')}
	closeLabel={pageText('referenceMenu.close')}
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
			{pageText('referenceMenu.showTakes')}
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
		{pageText('referenceMenu.delete')}
		{#if inUse}<span class="menu-item-hint">{pageText('referenceMenu.inUse')}</span>{/if}
	</button>
</MenuPopover>
