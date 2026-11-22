<script lang="ts">
	import { onDestroy } from 'svelte';
	import Icon from '../Icon.svelte';
	import {
		cancelSongMove,
		confirmSongMove,
		openSongMovePicker,
		songMoveConfirm,
		songMovePicker,
		songMoveRun
	} from '#lib/stores/songMove.ts';
	import type { ShareResult } from '#lib/api/types.ts';
	import { selectedSongId } from '#lib/stores/player.ts';
	import { createShareToggle } from '#lib/stores/shareToggle.svelte.ts';
	import { pageText } from '#lib/utils/page-words.ts';
	import AddToPicker from '../AddToPicker.svelte';
	import ConfirmDialog from '../ConfirmDialog.svelte';
	import MenuPopover from '../MenuPopover.svelte';
	import ShareRowContent from '../ShareRowContent.svelte';
	import SongMovePicker from './SongMovePicker.svelte';

	interface Props {
		title: string;
		saveDisabled: boolean;
		onsave: () => void;
		onrename: () => void;
		onaddto: (playlistId: string) => void;
		ondelete: () => void;
		isShared: boolean;
		shareSlug: string | null | undefined;
		onshare: () => Promise<ShareResult>;
		onunshare: () => Promise<void>;
	}

	let {
		title,
		saveDisabled,
		onsave,
		onrename,
		onaddto,
		ondelete,
		isShared,
		shareSlug,
		onshare,
		onunshare
	}: Props = $props();

	const shareToggle = createShareToggle(() => ({
		kind: 'song',
		isShared,
		shareSlug,
		onshare,
		onunshare
	}));

	let popover: MenuPopover | undefined = $state();
	let adding = $state(false);

	// A refused move after the shared-album ask finds the menu closed; it comes back on the red row.
	$effect(() => {
		if (
			$songMoveRun.status === 'failed' &&
			$songMoveRun.songId === $selectedSongId &&
			$songMovePicker.status === 'closed'
		) {
			void openSongMovePicker();
			popover?.open();
		}
	});

	onDestroy(cancelSongMove);

	function addToAndClose(playlistId: string): void {
		popover?.close();
		onaddto(playlistId);
	}

	function runAndClose(action: () => void, restoreFocus = true): void {
		popover?.close(restoreFocus);
		action();
	}
</script>

<div class="song-menu">
	<MenuPopover
		bind:this={popover}
		layer="song-menu"
		label={pageText('songMenu.label')}
		closeLabel={pageText('songMenu.close')}
		onclose={() => (adding = false)}
	>
		{#snippet trigger()}<Icon name="more-horizontal" size={18} />{/snippet}
		{#if adding}
			<AddToPicker onselect={addToAndClose} onback={() => (adding = false)} />
		{:else if $songMovePicker.status === 'closed'}
			<p class="menu-heading">{pageText('songMenu.heading', { title })}</p>
			<button class="menu-item" disabled={saveDisabled} onclick={() => runAndClose(onsave)}>
				<Icon name="check" size={14} />
				{pageText('songMenu.save')}
			</button>
			<!-- The title field takes the focus the closing menu would give back to its trigger. -->
			<button class="menu-item" onclick={() => runAndClose(onrename, false)}>
				<Icon name="pencil" size={14} />
				{pageText('songMenu.rename')}
			</button>
			<button class="menu-item opens-list" onclick={() => void openSongMovePicker()}>
				<Icon name="library" size={14} />
				{pageText('songMenu.move')}
			</button>
			<button class="menu-item opens-list" onclick={() => (adding = true)}>
				<Icon name="list-plus" size={14} />
				{pageText('songMenu.addTo')}
			</button>
			<button
				class="menu-item"
				aria-pressed={isShared}
				aria-busy={shareToggle.busy}
				title={shareToggle.sharedTooltip}
				onclick={shareToggle.toggle}
			>
				<ShareRowContent
					label={pageText('songMenu.share')}
					hint={pageText(isShared ? 'collectionMenu.shareOn' : 'collectionMenu.shareOff')}
					iconName={shareToggle.iconName}
					{isShared}
					busy={shareToggle.busy}
				/>
			</button>
			<button class="menu-item destructive" onclick={() => runAndClose(ondelete)}>
				<Icon name="trash" size={14} />
				{pageText('songMenu.delete')}
			</button>
		{:else}
			<SongMovePicker onclose={() => popover?.close()} />
		{/if}
	</MenuPopover>
</div>

{#if $songMoveConfirm}
	<ConfirmDialog
		title={pageText('songMove.sharedTitle')}
		message={pageText('songMove.sharedMessage', { song: title, album: $songMoveConfirm.title })}
		confirmLabel={pageText('songMove.confirm')}
		destructive={false}
		onconfirm={() => void confirmSongMove()}
		oncancel={cancelSongMove}
	/>
{/if}
