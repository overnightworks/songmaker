<script lang="ts">
	import type { ShareResult, UnplayableSongSummary } from '#lib/api/types.ts';
	import { createShareToggle } from '#lib/stores/shareToggle.svelte.ts';
	import { pageText, type TextKey } from '#lib/utils/page-words.ts';
	import AddToPicker from './AddToPicker.svelte';
	import Icon from './Icon.svelte';
	import MenuPickerHead from './MenuPickerHead.svelte';
	import MenuPopover from './MenuPopover.svelte';
	import ShareRowContent from './ShareRowContent.svelte';
	import ShareDialog from './ShareDialog.svelte';

	interface Props {
		kind: 'album' | 'playlist';
		/** The playlist's own id, which its Add to… leaves out of the choices. */
		collectionId: string;
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
		/** Playlist-only: picks a cover file to upload, from the Cover rows. */
		oncover?: () => void;
		/** Album-only: opens the cover editor, which uploads, suggests and removes. */
		oncoveredit?: () => void;
		hasCover?: boolean;
		/** Playlist-only: removes the cover once one is set. */
		onremovecover?: () => void;
		/** Adds the album's songs, or the playlist's entries, to the playlist chosen in the menu. */
		onaddto?: (playlistId: string) => void;
	}

	const kindKeys = {
		album: {
			heading: 'collectionMenu.albumHeading',
			share: 'collectionMenu.albumShare',
			delete: 'collectionMenu.albumDelete'
		},
		playlist: {
			heading: 'collectionMenu.playlistHeading',
			share: 'collectionMenu.playlistShare',
			delete: 'collectionMenu.playlistDelete'
		}
	} as const satisfies Record<'album' | 'playlist', Record<string, TextKey>>;

	let {
		kind,
		collectionId,
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
		onaddto
	}: Props = $props();

	const shareToggle = createShareToggle(() => ({
		kind,
		isShared,
		shareSlug,
		onshare: shareAndWarnIfIncomplete,
		onunshare
	}));

	let popover: MenuPopover | undefined = $state();
	let missingTakeSongs: UnplayableSongSummary[] = $state([]);
	/** The rows themselves, or the list that one of them swaps into the same popover. */
	let view: 'rows' | 'addTo' | 'cover' = $state('rows');

	function addToAndClose(playlistId: string): void {
		popover?.close();
		onaddto?.(playlistId);
	}

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

	function runAndClose(action: () => void, restoreFocus = true): void {
		popover?.close(restoreFocus);
		action();
	}

	function closeLeavingFocusToForm(action: () => void): void {
		runAndClose(action, false);
	}
</script>

{#snippet actionRow(
	label: string,
	action: () => void,
	icon?: string,
	hint?: string,
	close: (action: () => void) => void = runAndClose
)}
	<button class="menu-item" onclick={() => close(action)}>
		{#if icon}<Icon name={icon} size={14} />{/if}
		{label}
		{#if hint}<span class="menu-item-hint" aria-hidden="true">{hint}</span>{/if}
	</button>
{/snippet}

{#snippet opensListRow(label: string, target: 'addTo' | 'cover', icon: string)}
	<button class="menu-item opens-list" onclick={() => (view = target)}>
		<Icon name={icon} size={14} />
		{label}
	</button>
{/snippet}

{#snippet shareRow()}
	<button
		class="menu-item"
		aria-pressed={isShared}
		aria-busy={shareToggle.busy}
		title={shareToggle.sharedTooltip}
		onclick={shareToggle.toggle}
	>
		<ShareRowContent
			label={pageText(kindKeys[kind].share)}
			hint={pageText(isShared ? 'collectionMenu.shareOn' : 'collectionMenu.shareOff')}
			iconName={shareToggle.iconName}
			{isShared}
			busy={shareToggle.busy}
		/>
	</button>
{/snippet}

<div class="collection-menu">
	<MenuPopover
		bind:this={popover}
		layer="collection-menu"
		label={pageText('collectionMenu.label')}
		closeLabel={pageText('collectionMenu.close')}
		onclose={() => (view = 'rows')}
	>
		{#snippet trigger()}<Icon name="more-horizontal" size={18} />{/snippet}
		{#if view === 'addTo'}
			<AddToPicker
				onselect={addToAndClose}
				onback={() => (view = 'rows')}
				excludePlaylistId={kind === 'playlist' ? collectionId : undefined}
			/>
		{:else if view === 'cover'}
			<MenuPickerHead
				label={pageText('collectionMenu.coverBack')}
				heading={pageText('collectionMenu.cover')}
				onback={() => (view = 'rows')}
			/>
			{#if oncover}
				{@render actionRow(pageText('collectionMenu.upload'), oncover)}
			{/if}
			{#if hasCover && onremovecover}
				{@render actionRow(pageText('collectionMenu.removeCover'), onremovecover)}
			{/if}
		{:else}
			<p class="menu-heading">{pageText(kindKeys[kind].heading, { title })}</p>
			{#if kind === 'album'}
				{#if oneditdetails}
					{@render actionRow(
						pageText('collectionMenu.editDetails'),
						oneditdetails,
						'pencil',
						undefined,
						closeLeavingFocusToForm
					)}
				{/if}
				{#if oncoveredit}
					{@render actionRow(
						pageText('collectionMenu.cover'),
						oncoveredit,
						'image',
						pageText('collectionMenu.coverHint')
					)}
				{/if}
				{#if onaddto}
					{@render opensListRow(pageText('collectionMenu.addTo'), 'addTo', 'list-plus')}
				{/if}
				{@render shareRow()}
				{#if onarchive}
					{@render actionRow(pageText('collectionMenu.archive'), onarchive, 'archive')}
				{/if}
			{:else}
				{#if onrename}
					{@render actionRow(pageText('collectionMenu.rename'), onrename, 'pencil')}
				{/if}
				{#if oncover}
					{@render opensListRow(pageText('collectionMenu.cover'), 'cover', 'image')}
				{/if}
				{#if onaddto}
					{@render opensListRow(pageText('collectionMenu.addTo'), 'addTo', 'list-plus')}
				{/if}
				{@render shareRow()}
			{/if}
			<button class="menu-item destructive" onclick={() => runAndClose(ondelete)}>
				<Icon name="trash" size={14} />
				{pageText(kindKeys[kind].delete)}
			</button>
		{/if}
	</MenuPopover>
	<ShareDialog songs={missingTakeSongs} onclose={closeShareWarning} />
</div>
