<script lang="ts">
	import type { GenerationItem, ShareResult } from '#lib/api/types.ts';
	import { createShareToggle } from '#lib/stores/shareToggle.svelte.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import Icon from '../Icon.svelte';
	import MenuPopover from '../MenuPopover.svelte';

	interface Props {
		gen: GenerationItem;
		onrepaint: () => void;
		oncover: () => void;
		onuseseed: () => void;
		onshare: () => Promise<ShareResult>;
		onunshare: () => Promise<void>;
		onaddtoplaylist: () => void;
		onrestore: () => void;
		ondelete: () => void;
	}

	let {
		gen,
		onrepaint,
		oncover,
		onuseseed,
		onshare,
		onunshare,
		onaddtoplaylist,
		onrestore,
		ondelete
	}: Props = $props();

	const takeLabel = $derived(
		gen.version_number !== null
			? pageText('takeMenu.headingWithVersion', {
					version: String(gen.version_number),
					take: String(gen.generation_number)
				})
			: pageText('takeMenu.heading', { take: String(gen.generation_number) })
	);

	const shareToggle = createShareToggle(() => ({
		kind: 'gen',
		isShared: gen.is_shared,
		shareSlug: gen.share_slug,
		onshare,
		onunshare
	}));

	let popover: MenuPopover | undefined = $state();

	function runAndClose(action: () => void): void {
		popover?.close();
		action();
	}
</script>

<MenuPopover
	bind:this={popover}
	layer="take-menu"
	label={pageText('takeMenu.label')}
	closeLabel={pageText('takeMenu.close')}
	hitboxFace
>
	{#snippet trigger()}<Icon name="more-horizontal" size={16} />{/snippet}
	<p class="menu-heading">{takeLabel}</p>
	<button class="menu-item" onclick={() => runAndClose(onrepaint)}>
		<Icon name="paintbrush" size={14} />
		{pageText('takeMenu.repaint')}
	</button>
	<button class="menu-item" onclick={() => runAndClose(oncover)}>
		<Icon name="layers" size={14} />
		{pageText('takeMenu.cover')}
	</button>
	{#if gen.seed != null}
		<button class="menu-item" onclick={() => runAndClose(onuseseed)}>
			<Icon name="pin" size={14} />
			{pageText('takeMenu.useSeed')}
			<span class="menu-item-hint">{gen.seed}</span>
		</button>
	{/if}
	{#if gen.is_archived}
		<button class="menu-item" onclick={() => runAndClose(onrestore)}>
			<Icon name="refresh-cw" size={14} />
			{pageText('takeMenu.restore')}
		</button>
	{:else}
		<button class="menu-item" onclick={() => runAndClose(onaddtoplaylist)}>
			<Icon name="list-plus" size={14} />
			{pageText('takeMenu.addToPlaylist')}
		</button>
	{/if}
	{#if !gen.is_archived || gen.is_shared}
		<button
			class="menu-item"
			aria-pressed={gen.is_shared}
			title={shareToggle.sharedTooltip}
			onclick={shareToggle.toggle}
		>
			<Icon name={shareToggle.iconName} size={14} />
			{pageText('takeMenu.share')}
			<span class="menu-item-hint" aria-hidden="true">
				{pageText(gen.is_shared ? 'takeMenu.shareOn' : 'takeMenu.shareOff')}
			</span>
		</button>
	{/if}
	<button class="menu-item destructive" onclick={() => runAndClose(ondelete)}>
		<Icon name="trash" size={14} />
		{pageText('takeMenu.delete')}
	</button>
</MenuPopover>
