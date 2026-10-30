<script lang="ts">
	import { historyLayerState } from '#lib/stores/layers.ts';
	import {
		LIBRARY_NEW_ALBUM_LABEL,
		LIBRARY_NEW_FACE,
		LIBRARY_NEW_MENU_CLOSE_LABEL,
		LIBRARY_NEW_MENU_LABEL,
		LIBRARY_NEW_PLAYLIST_LABEL
	} from '#lib/constants.ts';
	import Icon from './Icon.svelte';
	import MenuPopover from './MenuPopover.svelte';
	import NewAlbumCard from './NewAlbumCard.svelte';
	import NewPlaylistCard from './NewPlaylistCard.svelte';

	type NewPlaceKind = 'album' | 'playlist';

	let menu: MenuPopover | undefined = $state();
	const card = historyLayerState<NewPlaceKind | null>('library-new-card', null);
	let shownCard: NewPlaceKind | null = null;
	let focusMenuOnFold = true;

	$effect(() => {
		const unfolded = $card;
		if (shownCard && !unfolded && focusMenuOnFold) menu?.focusTrigger();
		focusMenuOnFold = true;
		shownCard = unfolded;
	});

	function startNew(kind: NewPlaceKind): void {
		menu?.close(false);
		$card = kind;
	}

	function cancelNew(): void {
		$card = null;
	}

	function foldCreated(): void {
		focusMenuOnFold = false;
		$card = null;
	}
</script>

<span class="new-place-menu">
	<MenuPopover
		bind:this={menu}
		layer="library-new"
		label={LIBRARY_NEW_MENU_LABEL}
		closeLabel={LIBRARY_NEW_MENU_CLOSE_LABEL}
		pressed={$card !== null}
	>
		{#snippet trigger()}<span class="new-face"
				><Icon name="plus" size={16} />{LIBRARY_NEW_FACE}</span
			>{/snippet}
		<p class="new-menu-heading">New in <b>Library</b></p>
		<button type="button" class="new-menu-item" onclick={() => startNew('album')}
			><Icon name="album" size={16} />{LIBRARY_NEW_ALBUM_LABEL}</button
		>
		<button type="button" class="new-menu-item" onclick={() => startNew('playlist')}
			><Icon name="playlist" size={16} />{LIBRARY_NEW_PLAYLIST_LABEL}</button
		>
	</MenuPopover>
</span>
{#if $card}
	<div class="new-place-slot">
		{#if $card === 'album'}
			<NewAlbumCard oncancel={cancelNew} oncreated={foldCreated} />
		{:else}
			<NewPlaylistCard oncancel={cancelNew} oncreated={foldCreated} />
		{/if}
	</div>
{/if}

<style>
	.new-place-menu {
		display: contents;
	}

	.new-place-menu :global(.menu-trigger) {
		padding: 0;
	}

	.new-place-slot {
		flex: 1 0 100%;
		min-width: 0;
	}

	.new-place-slot :global(.new-place) {
		margin-bottom: 0;
	}

	.new-face {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		height: 42px;
		padding: 0 14px;
		font-family: var(--font-display);
		font-size: 0.78rem;
		font-weight: 500;
		letter-spacing: 0.5px;
		text-transform: uppercase;
	}

	.new-menu-heading {
		padding: 0.2rem 0.6rem 0.5rem;
		border-bottom: 1px solid var(--border);
		color: var(--text-subtle);
		font-size: 13px;
	}

	.new-menu-heading b {
		color: var(--text);
		font-weight: 600;
	}

	.new-menu-item {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		min-height: 34px;
		padding: 0 0.6rem;
		border: 0;
		border-radius: var(--btn-radius-sm);
		background: none;
		color: var(--text);
		font-family: var(--font-body);
		font-size: 0.87rem;
		text-align: left;
	}

	.new-menu-item :global(svg) {
		flex: none;
		color: var(--text-muted);
	}

	.new-menu-item:hover {
		background: var(--surface-hover);
	}

	@media (max-width: 768px) {
		.new-menu-item {
			min-height: 44px;
		}
	}
</style>
