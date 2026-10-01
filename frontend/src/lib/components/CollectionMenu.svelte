<script lang="ts">
	import type { ShareResult, UnplayableSongSummary } from '$lib/api/types';
	import {
		ALBUM_COVER_UPLOAD_LABEL,
		COLLECTION_MENU_ADD_TO_PLAYLIST_LABEL,
		COLLECTION_MENU_ARCHIVE_LABEL,
		COLLECTION_MENU_CLOSE_LABEL,
		COLLECTION_MENU_COVER_HINT,
		COLLECTION_MENU_COVER_LABEL,
		COLLECTION_MENU_COVER_REMOVE_LABEL,
		COLLECTION_MENU_CURATE_LABEL,
		COLLECTION_MENU_DELETE_LABEL,
		COLLECTION_MENU_EDIT_DETAILS_LABEL,
		COLLECTION_MENU_LABEL,
		COLLECTION_MENU_RENAME_LABEL,
		COLLECTION_MENU_SAVE_OFFLINE_LABEL,
		COLLECTION_MENU_SAVE_OFFLINE_REMOVE_LABEL,
		COLLECTION_MENU_SAVE_OFFLINE_SAVING_LABEL,
		COLLECTION_MENU_SHARE_LABEL
	} from '$lib/constants';
	import Icon from './Icon.svelte';
	import MenuPopover from './MenuPopover.svelte';
	import ShareButton from './ShareButton.svelte';
	import ShareDialog from './ShareDialog.svelte';

	interface Props {
		kind: 'album' | 'playlist';
		title: string;
		isShared: boolean;
		shareSlug: string | null | undefined;
		onshare: () => Promise<ShareResult>;
		onunshare: () => Promise<void>;
		/** Album-only: title, subtitle and year are edited together here. */
		oneditdetails?: () => void;
		/** Playlist-only: renames through the title. */
		onrename?: () => void;
		ondelete: () => void;
		onarchive?: () => void;
		/** Playlist-only: picks a cover file to upload. */
		oncover?: () => void;
		/** Album-only: opens the cover editor, which uploads, suggests and removes. */
		oncoveredit?: () => void;
		hasCover?: boolean;
		/** Playlist-only: removes the cover once one is set. */
		onremovecover?: () => void;
		onaddtoplaylist?: () => void;
		oncurate?: () => void;
		onsaveoffline?: () => void;
		offlineSaved?: boolean;
		offlineSaving?: boolean;
		offlineProgressLabel?: string | null;
	}

	let {
		kind,
		title,
		isShared,
		shareSlug,
		onshare,
		onunshare,
		oneditdetails,
		onrename,
		ondelete,
		onarchive,
		oncover,
		oncoveredit,
		hasCover = false,
		onremovecover,
		onaddtoplaylist,
		oncurate,
		onsaveoffline,
		offlineSaved = false,
		offlineSaving = false,
		offlineProgressLabel = null
	}: Props = $props();

	const kindLabel = $derived(kind === 'album' ? 'Album' : 'Playlist');
	const shareLabel = $derived(
		kind === 'album' ? COLLECTION_MENU_SHARE_LABEL : `${COLLECTION_MENU_SHARE_LABEL} ${kind}`
	);
	const deleteLabel = $derived(
		kind === 'album' ? COLLECTION_MENU_DELETE_LABEL : `${COLLECTION_MENU_DELETE_LABEL} ${kind}`
	);

	let popover: MenuPopover | undefined = $state();
	let missingTakeSongs: UnplayableSongSummary[] = $state([]);

	async function shareAndWarnIfIncomplete(): Promise<ShareResult> {
		const result = await onshare();
		if (kind === 'album' && result.songs_without_playable_take.length > 0) {
			missingTakeSongs = result.songs_without_playable_take;
			// Close the menu so its own focus-trapped dialog doesn't stack with
			// ShareDialog's -- two independent window keydown handlers would
			// otherwise both react to a single Escape press.
			popover?.close(false);
		}
		return result;
	}

	function closeShareWarning(): void {
		missingTakeSongs = [];
	}

	function runAndClose(action: () => void): void {
		popover?.close();
		action();
	}
</script>

{#snippet actionRow(label: string, action: () => void, icon?: string, hint?: string)}
	<button class="menu-item" onclick={() => runAndClose(action)}>
		{#if icon}<Icon name={icon} size={14} />{/if}
		{label}
		{#if hint}<span class="menu-item-hint" aria-hidden="true">{hint}</span>{/if}
	</button>
{/snippet}

{#snippet shareRow(icon?: string)}
	<div class="menu-row">
		<span class="menu-row-label"
			>{#if icon}<Icon name={icon} size={14} />{/if}{shareLabel}</span
		>
		<ShareButton {isShared} {shareSlug} onshare={shareAndWarnIfIncomplete} {onunshare} />
	</div>
{/snippet}

<div class="collection-menu">
	<MenuPopover
		bind:this={popover}
		layer="collection-menu"
		label={COLLECTION_MENU_LABEL}
		closeLabel={COLLECTION_MENU_CLOSE_LABEL}
	>
		{#snippet trigger()}<Icon name="more-horizontal" size={18} />{/snippet}
		<p class="menu-heading">{kindLabel} · {title}</p>
		{#if kind === 'album'}
			{#if oneditdetails}
				{@render actionRow(COLLECTION_MENU_EDIT_DETAILS_LABEL, oneditdetails, 'pencil')}
			{/if}
			{#if oncoveredit}
				{@render actionRow(
					COLLECTION_MENU_COVER_LABEL,
					oncoveredit,
					'image',
					COLLECTION_MENU_COVER_HINT
				)}
			{/if}
			{#if oncurate}
				{@render actionRow(COLLECTION_MENU_CURATE_LABEL, oncurate, 'spark')}
			{/if}
			{#if onaddtoplaylist}
				{@render actionRow(COLLECTION_MENU_ADD_TO_PLAYLIST_LABEL, onaddtoplaylist, 'list-plus')}
			{/if}
			{@render shareRow('share')}
			{#if onarchive}
				{@render actionRow(COLLECTION_MENU_ARCHIVE_LABEL, onarchive, 'archive')}
			{/if}
		{:else}
			{@render shareRow()}
			{#if oncover}
				{@render actionRow(ALBUM_COVER_UPLOAD_LABEL, oncover)}
			{/if}
			{#if hasCover && onremovecover}
				{@render actionRow(COLLECTION_MENU_COVER_REMOVE_LABEL, onremovecover)}
			{/if}
			{#if onsaveoffline}
				<button
					class="menu-item"
					onclick={() => runAndClose(onsaveoffline)}
					disabled={offlineSaving}
				>
					{#if offlineSaved}
						{COLLECTION_MENU_SAVE_OFFLINE_REMOVE_LABEL}
					{:else if offlineSaving}
						{offlineProgressLabel ?? COLLECTION_MENU_SAVE_OFFLINE_SAVING_LABEL}
					{:else}
						{COLLECTION_MENU_SAVE_OFFLINE_LABEL}
					{/if}
				</button>
			{/if}
			{#if onrename}
				{@render actionRow(COLLECTION_MENU_RENAME_LABEL, onrename)}
			{/if}
		{/if}
		<button class="menu-item destructive" onclick={() => runAndClose(ondelete)}>
			<Icon name="trash" size={14} />
			{deleteLabel}
		</button>
	</MenuPopover>
	<ShareDialog songs={missingTakeSongs} onclose={closeShareWarning} />
</div>

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

	.menu-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem;
		padding: 0.25rem 0.6rem;
	}

	.menu-row-label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-size: 0.87rem;
		color: var(--text);
	}

	.menu-item {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		min-height: var(--hitbox-frequent);
		padding: 0.5rem 0.6rem;
		border-radius: 4px;
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

	.menu-item:hover:not(:disabled) {
		background: var(--surface-hover);
	}

	.menu-item:disabled {
		opacity: 0.5;
		cursor: default;
	}

	.menu-item.destructive {
		color: var(--score-bad);
	}
</style>
