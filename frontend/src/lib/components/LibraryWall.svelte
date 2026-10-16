<script lang="ts">
	import { onMount } from 'svelte';
	import type { AlbumItem, PlaylistItem } from '$lib/api/types';
	import {
		albumList,
		allAlbumsLoad,
		ensureAllAlbumsLoaded,
		songList,
		albumSongsLoad
	} from '$lib/stores/libraryData';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import { playbackSource, playAlbum } from '$lib/stores/player';
	import { albumHasPlayableTake } from '$lib/utils/playable';
	import { openAlbum, openPlaylist } from '$lib/stores/navigation';
	import { historyLayerState } from '$lib/stores/layers';
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
		inLibraryOrder,
		lastPlayedByPlace,
		lastPlayedOf,
		libraryPlaceOrder,
		readLastPlayed
	} from '$lib/stores/libraryOrder';
	import { usableAlbumPrimary } from '$lib/utils/contrast';
	import { activityTimeLabel, songCountLabel } from '$lib/utils/format';
	import {
		ALBUM_COVER_ALT_TYPE,
		LIBRARY_NARROW_MEDIA,
		LIBRARY_ALBUM_CARD_TRACK_MAX_PX,
		LIBRARY_NEW_ALBUM_LABEL,
		LIBRARY_NEW_FACE,
		LIBRARY_NEW_MENU_CLOSE_LABEL,
		LIBRARY_NEW_MENU_LABEL,
		LIBRARY_NEW_PLAYLIST_LABEL,
		LIBRARY_PLAYLISTS_ERROR,
		LIBRARY_PLAYLISTS_LOADING,
		LIBRARY_PAGE_LABEL,
		LIBRARY_WALL_EMPTY,
		LIBRARY_WALL_ORDER_GROUP_LABEL,
		LIBRARY_WALL_ORDER_LABELS,
		LIBRARY_WALL_ORDERS,
		PLAYLISTS_PAGE_LABEL,
		PLAYLISTS_WALL_EMPTY,
		PLAYLISTS_WALL_ORDER_GROUP_LABEL,
		wallHeadingLabel,
		type LibraryWallOrder
	} from '$lib/constants';
	import Icon from './Icon.svelte';
	import LibraryContinue from './LibraryContinue.svelte';
	import LibraryRow from './LibraryRow.svelte';
	import LibraryTileContent from './LibraryTileContent.svelte';
	import MenuPopover from './MenuPopover.svelte';
	import NewAlbumCard from './NewAlbumCard.svelte';
	import NewPlaylistCard from './NewPlaylistCard.svelte';

	type NewPlaceKind = 'album' | 'playlist';
	// The Library wall of albums alone, or the Playlists page's wall of
	// playlists alone (#1354 rule 7; frames D1 and D3).
	type WallKind = 'library' | 'playlists';
	type WallCopy = {
		pageLabel: string;
		orderGroup: string;
		loading: string;
		failed: string;
		empty: string;
	};

	const WALL_COPY: Record<WallKind, WallCopy> = {
		library: {
			pageLabel: LIBRARY_PAGE_LABEL,
			orderGroup: LIBRARY_WALL_ORDER_GROUP_LABEL,
			loading: 'Loading library…',
			failed: 'Could not load library.',
			empty: LIBRARY_WALL_EMPTY
		},
		playlists: {
			pageLabel: PLAYLISTS_PAGE_LABEL,
			orderGroup: PLAYLISTS_WALL_ORDER_GROUP_LABEL,
			loading: LIBRARY_PLAYLISTS_LOADING,
			failed: LIBRARY_PLAYLISTS_ERROR,
			empty: PLAYLISTS_WALL_EMPTY
		}
	};

	let { kind }: { kind: WallKind } = $props();

	const copy = $derived(WALL_COPY[kind]);
	const albums = $derived($albumList);
	const playlists = $derived($playlistList);
	const currentCollection = $derived($openCollection);
	const order = $derived($libraryWallOrder);
	const browseState = $derived($libraryBrowse);
	const playlistStatus = $derived($playlistLoad);
	const restoredScroll = $derived($libraryScrollAnchor);

	let labelledAt = $state(new Date());

	let narrow = $state(false);
	$effect(() => {
		if (typeof window.matchMedia !== 'function') return;
		const media = window.matchMedia(LIBRARY_NARROW_MEDIA);
		const sync = () => {
			narrow = media.matches;
		};
		sync();
		media.addEventListener('change', sync);
		return () => media.removeEventListener('change', sync);
	});
	const songsByAlbum = $derived(Map.groupBy($songList, (song) => song.album_id));
	const wallItems = $derived(
		kind === 'library'
			? inLibraryOrder('album', albums, $libraryPlaceOrder)
			: inLibraryOrder('playlist', playlists, $libraryPlaceOrder)
	);
	const placeType = $derived(kind === 'library' ? 'album' : 'playlist');
	const loadStatuses = $derived(
		kind === 'library' ? [browseState.status] : [playlistStatus.status]
	);
	// The head states how many there are, which only the loaded list knows:
	// until it has loaded, the library holds none yet after a reload, or only
	// the album or playlist an address opened.
	const kindLoaded = $derived(
		kind === 'library' ? $allAlbumsLoad.status === 'ready' : playlistStatus.status === 'ready'
	);
	const headCount = $derived(kindLoaded ? wallItems.length : undefined);

	let browseEl = $state<HTMLElement | null>(null);
	let newMenu: MenuPopover | undefined = $state();
	const newCard = historyLayerState<NewPlaceKind | null>('library-new-card', null);
	let shownCard: NewPlaceKind | null = null;
	let focusNewOnFold = true;

	onMount(() => {
		initLibraryWallOrder();
		catchUpWall();
		return whenBackOnline(catchUpWall);
	});

	$effect(() => {
		const card = $newCard;
		if (shownCard && !card && focusNewOnFold) newMenu?.focusTrigger();
		focusNewOnFold = true;
		shownCard = card;
	});

	$effect(() => {
		void $lastPlayedByPlace;
		labelledAt = new Date();
	});

	$effect(() => {
		void wallItems.length;
		if (browseEl) browseEl.scrollTop = restoredScroll;
	});

	function sizeLabel(item: AlbumItem | PlaylistItem): string {
		return songCountLabel('song_count' in item ? item.song_count : item.entry_count);
	}

	function tileDetail(item: AlbumItem | PlaylistItem): string {
		const lastPlayed =
			order === 'played' ? lastPlayedOf($lastPlayedByPlace, { type: placeType, item }) : undefined;
		return lastPlayed ? activityTimeLabel(lastPlayed.at, labelledAt) : sizeLabel(item);
	}

	function isCurrent(id: string): boolean {
		return (
			audioPlayer.current !== null && $playbackSource?.kind === 'album' && $playbackSource.id === id
		);
	}

	function rowPlay(item: AlbumItem | PlaylistItem): (() => void) | undefined {
		if (
			!('song_count' in item) ||
			!albumHasPlayableTake(item, songsByAlbum.get(item.id) ?? [], {
				songsComplete: $albumSongsLoad[item.id] === 'idle'
			})
		)
			return undefined;
		return () => {
			if (isCurrent(item.id)) audioPlayer.toggle();
			else void playAlbum(item.id);
		};
	}

	// A failed read keeps what is on screen, and only an empty wall names it
	// (#1039 O4): the offline strip owns a lost network, and the wall reads
	// again when the page returns to the foreground or the network comes back.
	function catchUpWall(): void {
		if (kind === 'library') void ensureAllAlbumsLoaded();
		else void ensurePlaylistsLoaded();
		if ($libraryWallOrder === 'played') void readLastPlayed();
	}

	function chooseOrder(next: LibraryWallOrder): void {
		chooseLibraryWallOrder(next);
		labelledAt = new Date();
		if (next === 'played') void readLastPlayed();
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
	}

	function foldCreated(): void {
		focusNewOnFold = false;
		$newCard = null;
	}

	function retryLoad(): void {
		if (kind === 'library') void loadLibraryBrowse({ reset: true });
		else void loadPlaylists();
	}
</script>

<svelte:document onvisibilitychange={catchUpOnReturnToForeground} />

{#snippet newMenuButton()}
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
{/snippet}

{#snippet orderSwitch()}
	<div class="wall-order" role="group" aria-label={copy.orderGroup}>
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
{/snippet}

<div class="library-wall">
	<div class="wall-titlebar">
		<h1
			class="wall-title"
			aria-label={headCount === undefined
				? copy.pageLabel
				: wallHeadingLabel(copy.pageLabel, headCount)}
		>
			{copy.pageLabel}
			{#if headCount !== undefined}<span class="wall-count">{headCount}</span>{/if}
		</h1>
		{@render orderSwitch()}
		{@render newMenuButton()}
	</div>
	{#if kind === 'library'}
		<LibraryContinue />
	{/if}

	<div class="wall-body" bind:this={browseEl} onscroll={onBrowseScroll}>
		{#if $newCard === 'album'}
			<NewAlbumCard oncancel={cancelNew} oncreated={foldCreated} />
		{:else if $newCard === 'playlist'}
			<NewPlaylistCard oncancel={cancelNew} oncreated={foldCreated} />
		{/if}
		{#if wallItems.length > 0}
			<div class="tile-grid" style:--album-card-track={`${LIBRARY_ALBUM_CARD_TRACK_MAX_PX}px`}>
				{#each wallItems as item (placeType + item.id)}
					{@const content = {
						title: item.title,
						coverAlt: `${placeType === 'album' ? ALBUM_COVER_ALT_TYPE : 'Playlist cover for'} ${item.title}`,
						coverUrl: item.cover?.card ?? null,
						fill: 'colors' in item ? usableAlbumPrimary(item.colors) : null,
						playlistCovers: 'album_covers' in item ? item.album_covers : null
					}}
					{@const onopen = () => (kind === 'library' ? openAlbum(item.id) : openPlaylist(item.id))}
					<div
						class="wall-tile"
						class:phone={narrow}
						class:selected={currentCollection?.kind === placeType &&
							currentCollection.id === item.id}
					>
						{#if narrow}
							<LibraryRow
								{...content}
								subtitle={sizeLabel(item)}
								openLabel={`Open ${placeType} ${item.title}`}
								{onopen}
								onplay={rowPlay(item)}
								current={placeType === 'album' && isCurrent(item.id)}
								playing={isCurrent(item.id) && audioPlayer.status === 'playing'}
							/>
						{:else}
							<button
								type="button"
								class="wall-tile-body"
								onclick={onopen}
								aria-label={`Open ${placeType} ${item.title}`}
							>
								<LibraryTileContent {...content} subtitle={tileDetail(item)} />
							</button>
						{/if}
					</div>
				{/each}
			</div>
		{:else if loadStatuses.includes('loading')}
			<p class="empty" role="status">{copy.loading}</p>
		{:else if loadStatuses.includes('error')}
			<p class="empty" role="alert">{copy.failed}</p>
			<button class="retry-btn" onclick={retryLoad}>Retry</button>
		{:else}
			<p class="empty">{copy.empty}</p>
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
		flex-wrap: wrap;
		justify-content: space-between;
		gap: 8px;
		padding: 16px 20px 12px;
		border-bottom: 1px solid var(--border);
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

	.wall-titlebar .wall-order {
		margin-left: auto;
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

	.wall-tile.phone {
		border: 0;
		border-radius: 0;
		background: transparent;
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

		.wall-body {
			padding-inline: 12px;
		}

		.tile-grid {
			grid-template-columns: minmax(0, 1fr);
			gap: 0;
		}
	}
</style>
