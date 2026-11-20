<script lang="ts">
	import { pageText } from '#lib/utils/page-words.ts';
	import Icon from './Icon.svelte';
	import MenuPopover from './MenuPopover.svelte';

	let {
		name,
		onedit,
		ondelete
	}: {
		name: string;
		onedit: () => void;
		ondelete: () => void;
	} = $props();

	let popover: MenuPopover | undefined = $state();

	function runAndClose(action: () => void): void {
		popover?.close();
		action();
	}
</script>

<MenuPopover
	bind:this={popover}
	layer="preset-menu"
	label={pageText('collectionMenu.label')}
	closeLabel={pageText('collectionMenu.close')}
>
	{#snippet trigger()}<Icon name="more-horizontal" size={18} />{/snippet}
	<p class="menu-heading">{name}</p>
	<button class="menu-item" onclick={() => runAndClose(onedit)}>
		<Icon name="pencil" size={14} />
		{pageText('generationPage.edit')}
	</button>
	<button class="menu-item destructive" onclick={() => runAndClose(ondelete)}>
		<Icon name="trash" size={14} />
		{pageText('generationPage.delete')}
	</button>
</MenuPopover>
