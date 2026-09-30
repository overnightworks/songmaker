<script lang="ts">
	import { onMount } from 'svelte';
	import type { AlbumItem, PlaylistItem } from '$lib/api/types';
	import { albumList, ensureAllAlbumsLoaded } from '$lib/stores/libraryData';
	import { historyLayerState, openAlbum, openPlaylist } from '$lib/stores/navigation';
	import {
		ensurePlaylistsLoaded,
		playlistList,
		playlistLoad,
		loadPlaylists
	} from '$lib/stores/playlists';
	import { openCollection } from '$lib/stores/collection';
	import { captureLibraryScroll, libraryScrollAnchor } from '$lib/stores/libraryContext';
	import { whenBackOnline } from '$lib/stores/connectivity';
	import { libraryBrowse, loadLibraryBrowse } from '$lib/stores/librarySearch';
	import { chooseLibraryWallOrder, initLibraryWallOrder, libraryWallOrder } from '$lib/stores/ui';
	import {
		lastWorkByPlace,
		lastWorkOf,
		libraryPlaceOrder,
		readRecentWork
	} from '$lib/stores/libraryOrder';
	import { usableAlbumPrimary } from '$lib/utils/contrast';
	import { activityTimeLabel, addedDayLabel, placeLine, songCountLabel } from '$lib/utils/format';
	import {
		ALBUM_COVER_ALT_TYPE,
		LIBRARY_ALBUM_CARD_TRACK_MAX_PX,
		LIBRARY_NEW_ALBUM_LABEL,
		LIBRARY_NEW_FACE,
		LIBRARY_NEW_MENU_CLOSE_LABEL,
		LIBRARY_NEW_MENU_LABEL,
		LIBRARY_NEW_PLAYLIST_LABEL,
		LIBRARY_WALL_EMPTY,
		LIBRARY_WALL_HEADING,
		LIBRARY_WALL_ORDER_GROUP_LABEL,
		LIBRARY_WALL_ORDER_LABELS,
		LIBRARY_WALL_ORDERS,
		type LibraryWallOrder
	} from '$lib/constants';
	import Icon from './Icon.svelte';
	import LibraryContinue from './LibraryContinue.svelte';
	import LibraryTileContent from './LibraryTileContent.svelte';
	import MenuPopover from './MenuPopover.svelte';
	import NewAlbumCard from './NewAlbumCard.svelte';
	import NewPlaylistCard from './NewPlaylistCard.svelte';

	type NewPlaceKind = 'album' | 'playlist';
	type WallItem = { type: 'album'; item: AlbumItem } | { type: 'playlist'; item: PlaylistItem };

	const albums = $derived($albumList);
	const playlists = $derived($playlistList);
	const currentCollection = $derived($openCollection);
	const order = $derived($libraryWallOrder);
	const browseState = $derived($libraryBrowse);
	const playlistStatus = $derived($playlistLoad);
	const restoredScroll = $derived($libraryScrollAnchor);

	let labelledAt = $state(new Date());

	const wallItems = $derived.by(() => {
		const items: WallItem[] = [
			...albums.map((item) => ({ type: 'album' as const, item })),
			...playlists.map((item) => ({ type: 'playlist' as const, item }))
		];
		return items.sort($libraryPlaceOrder);
	});

	let browseEl = $state<HTMLElement | null>(null);
	let newMenu: MenuPopover | undefined = $state();
	const newCard = historyLayerState<NewPlaceKind | null>('library-new-card', null);

	onMount(() => {
		initLibraryWallOrder();
		catchUpWall();
		return whenBackOnline(catchUpWall);
	});

	$effect(() => {
		void $lastWorkByPlace;
		labelledAt = new Date();
	});

	$effect(() => {
		void wallItems.length;
		if (browseEl) browseEl.scrollTop = restoredScroll;
	});

	function sizeLabel(wallItem: WallItem): string {
		return songCountLabel(
			wallItem.type === 'album' ? wallItem.item.song_count : wallItem.item.entry_count
		);
	}

	function tileDetail(wallItem: WallItem): string {
		if (order === 'added') return addedDayLabel(wallItem.item.created_at, labelledAt);
		const lastWork = order === 'recent' ? lastWorkOf($lastWorkByPlace, wallItem) : undefined;
		return lastWork ? activityTimeLabel(lastWork.at, labelledAt) : sizeLabel(wallItem);
	}

	function tileLine(wallItem: WallItem): string {
		return placeLine(wallItem.type, tileDetail(wallItem));
	}

	// A failed read keeps what is on screen, and only an empty wall names it
	// (#1039 O4): the offline strip owns a lost network, and the wall reads
	// again when the page returns to the foreground or the network comes back.
	function catchUpWall(): void {
		void ensureAllAlbumsLoaded();
		void ensurePlaylistsLoaded();
		if ($libraryWallOrder === 'recent') void readRecentWork();
	}

	function chooseOrder(next: LibraryWallOrder): void {
		chooseLibraryWallOrder(next);
		labelledAt = new Date();
		if (next === 'recent') void readRecentWork();
	}

	function catchUpOnReturnToForeground(): void {
		if (document.visibilityState === 'visible') catchUpWall();
	}

	function onBrowseScroll(event: Event): void {
		const target = event.currentTarget;
		if (!(target instanceof HTMLElement)) return;
		captureLibraryScroll(target.scrollTop);
	}

	function startNew(kind: NewPlaceKind): void {
		newMenu?.close(false);
		$newCard = kind;
	}

	function cancelNew(): void {
		$newCard = null;
		newMenu?.focusTrigger();
	}

	function foldCreated(): void {
		$newCard = null;
	}

	function retryLoad(): void {
		void loadLibraryBrowse({ reset: true });
		void loadPlaylists();
	}
</script>

<svelte:document onvisibilitychange={catchUpOnReturnToForeground} />

<div class="library-wall">
	<div class="wall-titlebar">
		<h1 class="wall-title">Library</h1>
		<MenuPopover
			bind:this={newMenu}
			layer="library-new"
			label={LIBRARY_NEW_MENU_LABEL}
			closeLabel={LIBRARY_NEW_MENU_CLOSE_LABEL}
			pressed={$newCard !== null}
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
	</div>
	<LibraryContinue />

	<div class="wall-head">
		<h2 class="wall-heading">
			{LIBRARY_WALL_HEADING} <span class="wall-count">{wallItems.length}</span>
		</h2>
		<div class="wall-order" role="group" aria-label={LIBRARY_WALL_ORDER_GROUP_LABEL}>
			{#each LIBRARY_WALL_ORDERS as choice (choice)}
				<button
					type="button"
					class="wall-order-choice"
					aria-pressed={order === choice}
					onclick={() => chooseOrder(choice)}
				>
					<span class="wall-order-face">{LIBRARY_WALL_ORDER_LABELS[choice]}</span>
				</button>
			{/each}
		</div>
	</div>

	<div class="wall-body" bind:this={browseEl} onscroll={onBrowseScroll}>
		{#if $newCard === 'album'}
			<NewAlbumCard oncancel={cancelNew} oncreated={foldCreated} />
		{:else if $newCard === 'playlist'}
			<NewPlaylistCard oncancel={cancelNew} oncreated={foldCreated} />
		{/if}
		{#if wallItems.length > 0}
			<div class="tile-grid" style:--album-card-track={`${LIBRARY_ALBUM_CARD_TRACK_MAX_PX}px`}>
				{#each wallItems as wallItem (wallItem.type + wallItem.item.id)}
					<div
						class="wall-tile"
						class:selected={currentCollection?.kind === wallItem.type &&
							currentCollection.id === wallItem.item.id}
					>
						<button
							type="button"
							class="wall-tile-body"
							onclick={() =>
								wallItem.type === 'album'
									? openAlbum(wallItem.item.id)
									: openPlaylist(wallItem.item.id)}
							aria-label={`Open ${wallItem.type} ${wallItem.item.title}`}
						>
							{#if wallItem.type === 'album'}
								<LibraryTileContent
									title={wallItem.item.title}
									subtitle={tileLine(wallItem)}
									coverAlt={`${ALBUM_COVER_ALT_TYPE} ${wallItem.item.title}`}
									coverUrl={wallItem.item.cover?.card ?? null}
									fill={usableAlbumPrimary(wallItem.item.colors)}
								/>
							{:else}
								<LibraryTileContent
									title={wallItem.item.title}
									subtitle={tileLine(wallItem)}
									coverAlt={`Playlist cover for ${wallItem.item.title}`}
									coverUrl={wallItem.item.cover?.card ?? null}
									playlistCovers={wallItem.item.album_covers}
								/>
							{/if}
						</button>
					</div>
				{/each}
			</div>
		{:else if browseState.status === 'loading' || playlistStatus.status === 'loading'}
			<p class="empty" role="status">Loading library…</p>
		{:else if browseState.status === 'error' || playlistStatus.status === 'error'}
			<p class="empty" role="alert">Could not load library.</p>
			<button class="retry-btn" onclick={retryLoad}>Retry</button>
		{:else}
			<p class="empty">{LIBRARY_WALL_EMPTY}</p>
		{/if}
	</div>
</div>

<style>
	.library-wall {
		display: flex;
		flex: 1;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
	}

	.wall-titlebar {
		display: flex;
		flex-shrink: 0;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		padding: 16px 20px 8px;
	}

	.wall-title {
		color: var(--text);
		font-family: var(--font-display);
		font-size: 1.4rem;
		letter-spacing: 1px;
		text-transform: uppercase;
	}

	.wall-titlebar :global(.menu-trigger) {
		padding: 0;
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

	.wall-head {
		display: flex;
		flex-shrink: 0;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		padding: 0 20px;
		border-bottom: 1px solid var(--border);
		background: var(--bg);
	}

	.wall-heading {
		color: var(--text);
		font-family: var(--font-display);
		font-size: 0.9rem;
		font-weight: 500;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		white-space: nowrap;
	}

	.wall-count {
		margin-left: 0.3rem;
		color: var(--text-subtle);
		font-weight: 400;
		letter-spacing: 0.04em;
	}

	.wall-order {
		display: inline-flex;
	}

	.wall-order-choice {
		display: inline-flex;
		align-items: center;
		height: var(--hitbox-frequent);
		padding: 0;
		border: 0;
		background: none;
		cursor: pointer;
	}

	.wall-order-face {
		display: inline-flex;
		align-items: center;
		height: 30px;
		padding: 0 0.6rem;
		border: 1px solid var(--border);
		background: none;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 0.74rem;
		letter-spacing: 0.5px;
		text-transform: uppercase;
		white-space: nowrap;
	}

	.wall-order-choice + .wall-order-choice .wall-order-face {
		border-left: 0;
	}

	.wall-order-choice:first-child .wall-order-face {
		border-radius: var(--btn-radius-sm) 0 0 var(--btn-radius-sm);
	}

	.wall-order-choice:last-child .wall-order-face {
		border-radius: 0 var(--btn-radius-sm) var(--btn-radius-sm) 0;
	}

	.wall-order-choice[aria-pressed='true'] .wall-order-face {
		background: color-mix(in srgb, var(--accent) 16%, var(--surface));
		color: var(--accent);
	}

	.wall-order-choice:focus-visible {
		outline: none;
	}

	.wall-order-choice:focus-visible .wall-order-face {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}

	.wall-body {
		flex: 1;
		min-width: 0;
		min-height: 0;
		overflow-x: hidden;
		overflow-y: auto;
		padding: 8px 20px 20px;
	}

	.tile-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(0, var(--album-card-track)));
		gap: 12px;
		min-width: 0;
	}

	.wall-tile {
		min-width: 0;
		overflow: hidden;
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface);
	}

	.wall-tile.selected {
		box-shadow: inset 0 0 0 2px var(--accent);
	}

	.wall-tile-body {
		display: flex;
		flex-direction: column;
		width: 100%;
		min-width: 0;
		border: 0;
		background: transparent;
		color: var(--text);
		font-family: var(--font-body);
		cursor: pointer;
		text-align: left;
	}

	.wall-tile-body:hover,
	.wall-tile-body:focus-visible {
		background: var(--surface-hover);
		outline: none;
	}

	.empty {
		padding: 20px;
		color: var(--text-subtle);
		font-size: var(--label-font-size);
		text-align: center;
	}

	.retry-btn {
		display: block;
		margin: 0 auto 16px;
		padding: 6px 12px;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: none;
		color: var(--text-muted);
		font-family: var(--font-body);
		font-size: var(--label-font-size);
		cursor: pointer;
	}

	.retry-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	@media (max-width: 768px) {
		.wall-titlebar {
			padding: 10px 12px 6px;
		}

		.new-menu-item {
			min-height: 44px;
		}

		.wall-head {
			padding: 0 12px;
		}

		.wall-body {
			padding-inline: 12px;
		}

		.tile-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}
</style>
