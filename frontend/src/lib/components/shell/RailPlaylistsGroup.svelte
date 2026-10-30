<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { PLAYLISTS_ROUTE_PATH } from '#lib/routes/addresses.ts';
	import { standingPathname } from '#lib/routes/standingAddress.ts';
	import { openCollection } from '#lib/stores/collection.ts';
	import {
		placeShown,
		librarySurface,
		playlistsWallShows,
		playlistWhoseDetailShows
	} from '#lib/stores/libraryContext.ts';
	import { openPlaylist, openRailSearchTarget } from '#lib/stores/navigation.ts';
	import {
		ensurePlaylistsLoaded,
		playlistList,
		playlistLoad,
		selectedPlaylistDetail,
		selectedPlaylistId
	} from '#lib/stores/playlists.ts';
	import {
		isPlaylistEntryCurrent,
		playPlaylistEntryAndShowNowPlaying,
		queueContext,
		selectedSongId
	} from '#lib/stores/player.ts';
	import { whenBackOnline } from '#lib/stores/connectivity.ts';
	import { matchesRailQuery, normalizedRailTreeQuery } from '#lib/stores/librarySearch.ts';
	import {
		ensureLastPlayedRead,
		inLibraryOrder,
		libraryPlaceOrder
	} from '#lib/stores/libraryOrder.ts';
	import { libraryWallOrder } from '#lib/stores/ui.ts';
	import { PLAYLISTS_PAGE_LABEL, RAIL_PLAYLISTS_NAV_LABEL } from '#lib/constants.ts';
	import PlaylistCover from '../PlaylistCover.svelte';
	import PlayingMark from '../PlayingMark.svelte';
	import Icon from '../Icon.svelte';
	import RailGroup from './RailGroup.svelte';
	import { RAIL_PLAYLIST_ITEM_CLASS, revealOpenRailItem } from './rail-item-selector';

	// Local to this component, matching RailLibraryGroup's own
	// LIBRARY_OPEN_STORAGE_KEY -- nothing else reads this key.
	const PLAYLISTS_OPEN_STORAGE_KEY = 'songmaker.rail-playlists-open';

	const playlists = $derived($playlistList);
	// A list that never loaded counts nothing yet, rather than a false 0.
	const playlistCount = $derived(
		playlists.length > 0 || $playlistLoad.status === 'ready' ? playlists.length : undefined
	);
	// Tracks exist only for the currently open playlist: loadPlaylistDetail
	// navigates as a side effect (openPlaylist in stores/navigation.ts), and
	// the frozen picture (docs/design/navigation.html) draws playlist rows
	// with no chevron in any state.
	const openPlaylistId = $derived($selectedPlaylistId);
	const openPlaylistDetail = $derived($selectedPlaylistDetail);
	const shownPlaylistId = $derived(playlistWhoseDetailShows($librarySurface, $openCollection));
	// The Playlists wall is the surface in view: it unfolds the group (#1354 D3).
	// The surface stays `playlists` after leaving for Settings, so it does not make
	// the word current (#1523).
	const playlistsWallIsSurface = $derived(playlistsWallShows($librarySurface, $selectedSongId));
	const onPlaylistsPage = $derived(
		placeShown('playlists', $librarySurface, $selectedSongId, standingPathname(page.state))
	);
	const query = $derived($normalizedRailTreeQuery);
	const filtering = $derived(query.length > 0);
	const visiblePlaylists = $derived(
		inLibraryOrder(
			'playlist',
			playlists.filter(
				(playlist) =>
					!filtering || playlist.id === openPlaylistId || matchesRailQuery(playlist.title, query)
			),
			$libraryPlaceOrder
		)
	);

	// ensurePlaylistsLoaded is route-independent, mirroring
	// ensureAllAlbumsLoaded in RailLibraryGroup -- the rail needs the complete
	// playlist list regardless of which route is open.
	$effect(() => {
		void ensurePlaylistsLoaded();
	});

	$effect(() => whenBackOnline(() => void ensurePlaylistsLoaded()));

	$effect(() => {
		if ($libraryWallOrder === 'played') void ensureLastPlayedRead();
	});

	function onPlaylistLabelClick(playlistId: string): void {
		void openPlaylist(playlistId);
	}

	function onEntryClick(index: number): void {
		if (!openPlaylistDetail) return;
		void playPlaylistEntryAndShowNowPlaying(openPlaylistDetail, index);
	}
</script>

{#snippet icon()}
	<Icon name="playlists" size={14} />
{/snippet}

<RailGroup
	label={PLAYLISTS_PAGE_LABEL}
	groupId="rail-playlists-group"
	storageKey={PLAYLISTS_OPEN_STORAGE_KEY}
	count={playlistCount}
	expandTrigger={playlistsWallIsSurface || openPlaylistId !== null || filtering}
	page={{
		href: resolve(PLAYLISTS_ROUTE_PATH),
		current: onPlaylistsPage,
		open: () => void openRailSearchTarget({ kind: 'page', href: PLAYLISTS_ROUTE_PATH })
	}}
	{icon}
>
	{#snippet children(groupOpen: boolean)}
		<nav class="rail-playlists-nav" aria-label={RAIL_PLAYLISTS_NAV_LABEL}>
			<ul class="playlist-list">
				{#each visiblePlaylists as playlist (playlist.id)}
					{@const playlistOpen = playlist.id === openPlaylistId}
					{@const current = playlist.id === shownPlaylistId}
					{@const entries =
						playlistOpen && openPlaylistDetail?.id === playlist.id
							? openPlaylistDetail.entries
							: []}
					<li>
						<button
							type="button"
							class={RAIL_PLAYLIST_ITEM_CLASS}
							aria-current={current ? 'page' : undefined}
							use:revealOpenRailItem={current && groupOpen && !filtering}
							onclick={() => onPlaylistLabelClick(playlist.id)}
						>
							<PlaylistCover
								title={playlist.title}
								covers={playlist.album_covers}
								cover={playlist.cover}
								visible={groupOpen}
							/>
							<span class="row-title">{playlist.title}</span>
							<span class="row-meta">{playlist.entry_count}</span>
						</button>
						<div class="playlist-songs" data-open={playlistOpen} inert={!playlistOpen}>
							<div class="playlist-songs-content">
								<ul>
									{#each entries as entry, index (entry.id)}
										{@const current = isPlaylistEntryCurrent(entry, $queueContext)}
										<li>
											<button
												type="button"
												class="row row-sub2"
												class:row-active={current}
												onclick={() => onEntryClick(index)}
											>
												<PlayingMark {current} />
												<span class="row-title">{entry.song_title}</span>
											</button>
										</li>
									{/each}
								</ul>
							</div>
						</div>
					</li>
				{/each}
			</ul>
		</nav>
	{/snippet}
</RailGroup>

<style>
	.playlist-list {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.row {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 8px 16px;
		background: none;
		border: none;
		color: var(--text-muted);
		font-size: 0.85rem;
		text-align: left;
		text-decoration: none;
		cursor: pointer;
	}

	.row:hover {
		background: var(--surface-hover);
		color: var(--text);
	}

	.row-sub2 {
		padding-left: 48px;
		font-size: 0.8rem;
		font-family: inherit;
		text-transform: none;
		letter-spacing: normal;
		border-left: 3px solid transparent;
	}

	.playlist-label {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 8px 16px 8px 32px;
		background: none;
		border: none;
		color: var(--text-muted);
		font: inherit;
		font-size: 0.8rem;
		text-align: left;
		cursor: pointer;
	}

	.playlist-label:hover {
		background: var(--surface-hover);
		color: var(--text);
	}

	.row-title {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.row-meta {
		flex-shrink: 0;
		font-size: 0.7rem;
		color: var(--text-subtle);
	}

	.row-active {
		color: var(--text);
		border-left-color: var(--primary);
		background: color-mix(in srgb, var(--primary) 8%, transparent);
	}

	.playlist-songs {
		display: grid;
		grid-template-rows: 0fr;
		transition: grid-template-rows 0.2s ease;
	}

	.playlist-songs[data-open='true'] {
		grid-template-rows: 1fr;
	}

	.playlist-songs-content {
		overflow: hidden;
	}

	.playlist-songs-content ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	@media (prefers-reduced-motion: reduce) {
		.playlist-songs {
			transition: none;
		}
	}
</style>
