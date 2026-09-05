<script lang="ts">
	import { onMount } from 'svelte';
	import type { AlbumItem, PlaylistItem } from '$lib/api/types';
	import { albumList } from '$lib/stores/libraryData';
	import { openAlbum, openPlaylist, persistLibraryHistory } from '$lib/stores/navigation';
	import {
		ensurePlaylistsLoaded,
		playlistList,
		playlistLoad,
		loadPlaylists
	} from '$lib/stores/playlists';
	import { openCollection } from '$lib/stores/collection';
	import { captureLibraryScroll, libraryScrollAnchor } from '$lib/stores/libraryContext';
	import { libraryBrowse, librarySort, loadLibraryBrowse } from '$lib/stores/librarySearch';
	import { compareByCreatedAt } from '$lib/utils/recency';
	import { usableAlbumPrimary } from '$lib/utils/contrast';
	import { albumSummaryLabel, playlistSummaryLabel } from '$lib/utils/format';
	import { ALBUM_COVER_ALT_TYPE, LIBRARY_ALBUM_CARD_TRACK_MAX_PX } from '$lib/constants';
	import LibraryContinue from './LibraryContinue.svelte';
	import LibraryTileContent from './LibraryTileContent.svelte';

	type WallItem = { type: 'album'; item: AlbumItem } | { type: 'playlist'; item: PlaylistItem };

	const albums = $derived($albumList);
	const playlists = $derived($playlistList);
	const currentCollection = $derived($openCollection);
	const createdSort = $derived($librarySort);
	const browseState = $derived($libraryBrowse);
	const playlistStatus = $derived($playlistLoad);
	const restoredScroll = $derived($libraryScrollAnchor);

	const wallItems = $derived.by(() => {
		const items: WallItem[] = [
			...albums.map((item) => ({ type: 'album' as const, item })),
			...playlists.map((item) => ({ type: 'playlist' as const, item }))
		];
		return items.sort((a, b) => compareByCreatedAt(a.item, b.item, createdSort));
	});

	let browseEl = $state<HTMLElement | null>(null);

	onMount(() => {
		void ensurePlaylistsLoaded();
	});

	$effect(() => {
		void wallItems.length;
		if (browseEl) browseEl.scrollTop = restoredScroll;
	});

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

<div class="library-wall">
	<h1 class="wall-title">Library</h1>
	<LibraryContinue />

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
									subtitle={albumSummaryLabel(wallItem.item.song_count, wallItem.item.picked_count)}
									coverAlt={`${ALBUM_COVER_ALT_TYPE} ${wallItem.item.title}`}
									coverUrl={wallItem.item.cover?.card ?? null}
									fill={usableAlbumPrimary(wallItem.item.colors)}
								/>
							{:else}
								<LibraryTileContent
									title={wallItem.item.title}
									subtitle={playlistSummaryLabel(wallItem.item.entry_count)}
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

		{#if browseState.albumHasMore}
			<button
				class="load-more"
				onclick={async () => {
					await loadLibraryBrowse({ reset: false });
					persistLibraryHistory();
				}}
				disabled={browseState.status === 'loading'}
			>
				Load more
			</button>
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

	.retry-btn,
	.load-more {
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

	.retry-btn:hover,
	.load-more:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.load-more:disabled {
		opacity: 0.5;
		cursor: default;
	}

	@media (max-width: 768px) {
		.wall-title {
			padding: 12px 12px 6px;
		}

		.wall-body {
			padding-inline: 12px;
		}

		.tile-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}
</style>
