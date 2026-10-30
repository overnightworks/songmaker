<script lang="ts">
	import {
		COLLECTION_MENU_CLOSE_LABEL,
		SONG_MENU_ADD_TO_PLAYLIST_LABEL,
		SONG_MENU_DELETE_LABEL,
		SONG_MENU_RENAME_LABEL,
		SONG_MENU_SAVE_LABEL,
		SONG_MENU_LABEL
	} from '#lib/constants.ts';
	import Icon from '../Icon.svelte';
	import MenuPopover from '../MenuPopover.svelte';

	interface Props {
		title: string;
		saveDisabled: boolean;
		onsave: () => void;
		onrename: () => void;
		onaddtoplaylist: () => void;
		ondelete: () => void;
	}

	let { title, saveDisabled, onsave, onrename, onaddtoplaylist, ondelete }: Props = $props();

	let popover: MenuPopover | undefined = $state();

	function runAndClose(action: () => void, restoreFocus = true): void {
		popover?.close(restoreFocus);
		action();
	}
</script>

<div class="song-menu">
	<MenuPopover
		bind:this={popover}
		layer="song-menu"
		label={SONG_MENU_LABEL}
		closeLabel={COLLECTION_MENU_CLOSE_LABEL}
	>
		{#snippet trigger()}<Icon name="more-horizontal" size={18} />{/snippet}
		<p class="menu-heading">Song · {title}</p>
		<button class="menu-item" disabled={saveDisabled} onclick={() => runAndClose(onsave)}>
			<Icon name="check" size={14} />
			{SONG_MENU_SAVE_LABEL}
		</button>
		<!-- The title field takes the focus the closing menu would give back to its trigger. -->
		<button class="menu-item" onclick={() => runAndClose(onrename, false)}>
			<Icon name="pencil" size={14} />
			{SONG_MENU_RENAME_LABEL}
		</button>
		<button class="menu-item" onclick={() => runAndClose(onaddtoplaylist)}>
			<Icon name="list-plus" size={14} />
			{SONG_MENU_ADD_TO_PLAYLIST_LABEL}
		</button>
		<button class="menu-item destructive" onclick={() => runAndClose(ondelete)}>
			<Icon name="trash" size={14} />
			{SONG_MENU_DELETE_LABEL}
		</button>
	</MenuPopover>
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
