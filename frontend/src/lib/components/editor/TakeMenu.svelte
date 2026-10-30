<script lang="ts">
	import type { GenerationItem, ShareResult } from '#lib/api/types.ts';
	import {
		COLLECTION_MENU_CLOSE_LABEL,
		COLLECTION_MENU_SHARE_OFF_HINT,
		COLLECTION_MENU_SHARE_ON_HINT,
		TAKE_COVER_LABEL,
		TAKE_DELETE_LABEL,
		TAKE_OVERFLOW_LABEL,
		TAKE_PLAYLIST_LABEL,
		TAKE_REPAINT_LABEL,
		TAKE_RESTORE_LABEL,
		TAKE_SHARE_LABEL
	} from '#lib/constants.ts';
	import { TAKE_USE_SEED_LABEL } from '#lib/constants/take-task.ts';
	import { createShareToggle } from '#lib/stores/shareToggle.svelte.ts';
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
			? `Take · v${gen.version_number} · ${gen.generation_number}`
			: `Take · ${gen.generation_number}`
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
	label={TAKE_OVERFLOW_LABEL}
	closeLabel={COLLECTION_MENU_CLOSE_LABEL}
	hitboxFace
>
	{#snippet trigger()}<Icon name="more-horizontal" size={16} />{/snippet}
	<p class="menu-heading">{takeLabel}</p>
	<button class="menu-item" onclick={() => runAndClose(onrepaint)}>
		<Icon name="paintbrush" size={14} />
		{TAKE_REPAINT_LABEL}
	</button>
	<button class="menu-item" onclick={() => runAndClose(oncover)}>
		<Icon name="layers" size={14} />
		{TAKE_COVER_LABEL}
	</button>
	{#if gen.seed != null}
		<button class="menu-item" onclick={() => runAndClose(onuseseed)}>
			<Icon name="pin" size={14} />
			{TAKE_USE_SEED_LABEL}
			<span class="menu-item-hint">{gen.seed}</span>
		</button>
	{/if}
	{#if gen.is_archived}
		<button class="menu-item" onclick={() => runAndClose(onrestore)}>
			<Icon name="refresh-cw" size={14} />
			{TAKE_RESTORE_LABEL}
		</button>
	{:else}
		<button class="menu-item" onclick={() => runAndClose(onaddtoplaylist)}>
			<Icon name="list-plus" size={14} />
			{TAKE_PLAYLIST_LABEL}
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
			{TAKE_SHARE_LABEL}
			<span class="menu-item-hint" aria-hidden="true">
				{gen.is_shared ? COLLECTION_MENU_SHARE_ON_HINT : COLLECTION_MENU_SHARE_OFF_HINT}
			</span>
		</button>
	{/if}
	<button class="menu-item destructive" onclick={() => runAndClose(ondelete)}>
		<Icon name="trash" size={14} />
		{TAKE_DELETE_LABEL}
	</button>
</MenuPopover>

<style>
	.menu-heading {
		margin: 0;
		padding: 0.3rem 0.6rem 0.5rem;
		font-family: var(--font-display);
		font-size: 0.7rem;
		letter-spacing: 0.5px;
		text-transform: uppercase;
		color: var(--text-subtle);
		border-bottom: 1px solid var(--border);
		margin-bottom: 0.25rem;
		overflow-wrap: anywhere;
	}

	.menu-item {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		min-height: var(--hitbox-frequent);
		padding: 0.5rem 0.6rem;
		border-radius: var(--btn-radius-sm);
		font-size: 0.87rem;
		color: var(--text);
		background: none;
		border: none;
		text-align: left;
		cursor: pointer;
	}

	.menu-item-hint {
		margin-left: auto;
		font-size: 0.75rem;
		color: var(--text-subtle);
	}

	.menu-item:hover {
		background: var(--surface-hover);
	}

	.menu-item.destructive {
		color: var(--score-bad);
	}
</style>
