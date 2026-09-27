<script lang="ts">
	import { onMount } from 'svelte';
	import { get } from 'svelte/store';
	import { fetchLibraryContinue, type LibraryContinueItem } from '$lib/api/library';
	import type { AlbumItem, PlaylistItem } from '$lib/api/types';
	import { albumList, ensureAllAlbumsLoaded } from '$lib/stores/libraryData';
	import { openAlbum, openPlaylist } from '$lib/stores/navigation';
	import {
		ensurePlaylistsLoaded,
		playlistList,
		playlistLoad,
		loadPlaylists
	} from '$lib/stores/playlists';
	import { openCollection } from '$lib/stores/collection';
	import { captureLibraryScroll, libraryScrollAnchor } from '$lib/stores/libraryContext';
	import { offline } from '$lib/stores/connectivity';
	import { libraryBrowse, loadLibraryBrowse } from '$lib/stores/librarySearch';
	import { chooseLibraryWallOrder, initLibraryWallOrder, libraryWallOrder } from '$lib/stores/ui';
	import { compareByCreatedAt } from '$lib/utils/recency';
	import { usableAlbumPrimary } from '$lib/utils/contrast';
	import { activityTimeLabel, addedDayLabel, placeLine, songCountLabel } from '$lib/utils/format';
	import {
		ALBUM_COVER_ALT_TYPE,
		LIBRARY_ALBUM_CARD_TRACK_MAX_PX,
		LIBRARY_WALL_HEADING,
		LIBRARY_WALL_ORDER_GROUP_LABEL,
		LIBRARY_WALL_ORDER_LABELS,
		LIBRARY_WALL_ORDERS,
		LIBRARY_WALL_RECENT_PAGE_SIZE,
		type LibraryWallOrder
	} from '$lib/constants';
	import LibraryContinue from './LibraryContinue.svelte';
	import LibraryTileContent from './LibraryTileContent.svelte';

	type WallItem = { type: 'album'; item: AlbumItem } | { type: 'playlist'; item: PlaylistItem };
	type LastWork = { rank: number; at: string };

	const albums = $derived($albumList);
	const playlists = $derived($playlistList);
	const currentCollection = $derived($openCollection);
	const order = $derived($libraryWallOrder);
	const browseState = $derived($libraryBrowse);
	const playlistStatus = $derived($playlistLoad);
	const restoredScroll = $derived($libraryScrollAnchor);

	let recentWork = $state<LibraryContinueItem[]>([]);
	let labelledAt = $state(new Date());
	let recentWorkRequest = 0;

	const lastWorkByPlace = $derived(
		new Map<string, LastWork>(
			recentWork.map((place, rank) => [
				placeKey(place.type, place.id),
				{ rank, at: place.activity_at }
			])
		)
	);

	const ORDER_COMPARATORS: Record<LibraryWallOrder, (a: WallItem, b: WallItem) => number> = {
		title: compareTitles,
		recent: compareByLastWork,
		added: (a, b) => compareByCreatedAt(a.item, b.item, 'newest')
	};

	const wallItems = $derived.by(() => {
		const items: WallItem[] = [
			...albums.map((item) => ({ type: 'album' as const, item })),
			...playlists.map((item) => ({ type: 'playlist' as const, item }))
		];
		return items.sort(ORDER_COMPARATORS[order]);
	});

	let browseEl = $state<HTMLElement | null>(null);

	onMount(() => {
		initLibraryWallOrder();
		catchUpWall();
		return whenBackOnline(catchUpWall);
	});

	$effect(() => {
		void wallItems.length;
		if (browseEl) browseEl.scrollTop = restoredScroll;
	});

	function placeKey(type: WallItem['type'], id: string): string {
		return `${type}:${id}`;
	}

	function lastWorkOf(wallItem: WallItem): LastWork | undefined {
		return lastWorkByPlace.get(placeKey(wallItem.type, wallItem.item.id));
	}

	function compareTitles(a: WallItem, b: WallItem): number {
		return compareByCreatedAt(a.item, b.item, 'title');
	}

	// A place newer than the last read of Recent has no rank yet; it waits at
	// the end in title order until the next read ranks it.
	function compareByLastWork(a: WallItem, b: WallItem): number {
		const aRank = lastWorkOf(a)?.rank ?? Number.POSITIVE_INFINITY;
		const bRank = lastWorkOf(b)?.rank ?? Number.POSITIVE_INFINITY;
		if (aRank === bRank) return compareTitles(a, b);
		return aRank < bRank ? -1 : 1;
	}

	function sizeLabel(wallItem: WallItem): string {
		return songCountLabel(
			wallItem.type === 'album' ? wallItem.item.song_count : wallItem.item.entry_count
		);
	}

	function tileDetail(wallItem: WallItem): string {
		if (order === 'added') return addedDayLabel(wallItem.item.created_at, labelledAt);
		const lastWork = order === 'recent' ? lastWorkOf(wallItem) : undefined;
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
		if ($libraryWallOrder === 'recent') void loadRecentWork();
	}

	function whenBackOnline(callback: () => void): () => void {
		let wasOffline = get(offline);
		return offline.subscribe((isOffline) => {
			if (wasOffline && !isOffline) callback();
			wasOffline = isOffline;
		});
	}

	async function loadRecentWork(): Promise<void> {
		const request = ++recentWorkRequest;
		const ranking = await readRecentWork();
		if (ranking === null || request !== recentWorkRequest) return;
		recentWork = ranking;
		labelledAt = new Date();
	}

	async function readRecentWork(): Promise<LibraryContinueItem[] | null> {
		const places: LibraryContinueItem[] = [];
		try {
			for (;;) {
				const page = await fetchLibraryContinue({
					offset: places.length,
					limit: LIBRARY_WALL_RECENT_PAGE_SIZE
				});
				places.push(...page.items);
				if (page.items.length < LIBRARY_WALL_RECENT_PAGE_SIZE) return places;
			}
		} catch {
			return null;
		}
	}

	function chooseOrder(next: LibraryWallOrder): void {
		chooseLibraryWallOrder(next);
		labelledAt = new Date();
		if (next === 'recent') void loadRecentWork();
	}

	function catchUpOnReturnToForeground(): void {
		if (document.visibilityState === 'visible') catchUpWall();
	}

	function onBrowseScroll(event: Event): void {
		const target = event.currentTarget;
		if (!(target instanceof HTMLElement)) return;
		captureLibraryScroll(target.scrollTop);
	}

	function retryLoad(): void {
		void loadLibraryBrowse({ reset: true });
		void loadPlaylists();
	}
</script>

<svelte:document onvisibilitychange={catchUpOnReturnToForeground} />

<div class="library-wall">
	<h1 class="wall-title">Library</h1>
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
			<p class="empty">No albums or playlists yet.</p>
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

	.wall-title {
		padding: 16px 20px 8px;
		color: var(--text);
		font-family: var(--font-display);
		font-size: 1.4rem;
		letter-spacing: 1px;
		text-transform: uppercase;
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
		.wall-title {
			padding: 12px 12px 6px;
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
