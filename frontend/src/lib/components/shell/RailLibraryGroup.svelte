<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { openCollection } from '#lib/stores/collection.ts';
	import {
		albumWhoseSongsShow,
		libraryWallShows,
		placeShown,
		librarySurface
	} from '#lib/stores/libraryContext.ts';
	import {
		albumList,
		allAlbumsLoad,
		allAlbumsLoadFailure,
		ensureAllAlbumsLoaded,
		loadSongsForAlbum,
		songList
	} from '#lib/stores/libraryData.ts';
	import { isSongCurrent, selectedSongId } from '#lib/stores/player.ts';
	import { matchesRailQuery, normalizedRailTreeQuery } from '#lib/stores/librarySearch.ts';
	import {
		ensureLastPlayedRead,
		inLibraryOrder,
		libraryPlaceOrder
	} from '#lib/stores/libraryOrder.ts';
	import { libraryWallOrder } from '#lib/stores/ui.ts';
	import { pickedTake, songPlayability } from '#lib/utils/playable.ts';
	import {
		compareAlbumTracks,
		openAlbum,
		openRailSearchTarget,
		selectSong
	} from '#lib/stores/navigation.ts';
	import {
		ALBUM_COVER_ALT_TYPE,
		LIBRARY_RETRY_LABEL,
		RAIL_CONTEXT_NO_TAKES,
		LIBRARY_PAGE_LABEL,
		RAIL_LIBRARY_NAV_LABEL
	} from '#lib/constants.ts';
	import type { SongItem } from '#lib/api/types.ts';
	import { LIBRARY_ROUTE_ID, LIBRARY_ROUTE_PATH } from '#lib/routes/addresses.ts';
	import { standingPathname } from '#lib/routes/standingAddress.ts';
	import { titleInitials } from '#lib/utils/format.ts';
	import PlayingMark from '../PlayingMark.svelte';
	import Icon from '../Icon.svelte';
	import RailGroup from './RailGroup.svelte';
	import { RAIL_ALBUM_ITEM_CLASS, revealOpenRailItem } from './rail-item-selector';

	// Local to this component rather than promoted to constants.ts: nothing
	// else reads this key, matching how RailGroup's own groupId is already
	// inlined per caller (see RailSettings.svelte) rather than centralized.
	const LIBRARY_OPEN_STORAGE_KEY = 'songmaker.rail-library-open';

	const albums = $derived($albumList);
	const songs = $derived($songList);
	const songsByAlbum = $derived.by(() => {
		// eslint-disable-next-line svelte/prefer-svelte-reactivity -- rebuilt per derivation, never mutated reactively
		const index = new Map<string, SongItem[]>();
		for (const song of songs) {
			const albumSongs = index.get(song.album_id);
			if (albumSongs) albumSongs.push(song);
			else index.set(song.album_id, [song]);
		}
		return index;
	});
	const collection = $derived($openCollection);
	const surface = $derived($librarySurface);
	const currentSongId = $derived($selectedSongId);
	const openAlbumId = $derived(collection?.kind === 'album' ? collection.id : null);
	const query = $derived($normalizedRailTreeQuery);
	const filtering = $derived(query.length > 0);
	const shownAlbumId = $derived(albumWhoseSongsShow(surface, collection));
	// The Library wall is the surface in view: it unfolds the group (#1354 D1).
	// The surface alone also reads `browse` on /settings and while /?song= looks
	// its song up, so it does not make the word current (#1523).
	const libraryWallIsSurface = $derived(libraryWallShows(surface, currentSongId));
	const onLibraryPage = $derived(
		placeShown('library', surface, currentSongId, standingPathname(page.state))
	);
	const isAlbumDetail = $derived(shownAlbumId !== null);
	const loadStatus = $derived($allAlbumsLoad.status);
	const loadFailure = $derived($allAlbumsLoadFailure);
	// Only a complete list can name the total, including an empty one.
	const albumCount = $derived(loadStatus === 'ready' ? albums.length : undefined);
	const visibleAlbums = $derived.by(() =>
		inLibraryOrder(
			'album',
			albums.filter((album) => {
				if (!filtering || album.id === openAlbumId) return true;
				if (matchesRailQuery(album.title, query)) return true;
				return (songsByAlbum.get(album.id) ?? []).some((song) =>
					matchesRailQuery(song.title, query)
				);
			}),
			$libraryPlaceOrder
		)
	);

	// ensureAllAlbumsLoaded is route-independent (#304) -- the rail needs the
	// complete album list regardless of which library page, or which non-library
	// route (e.g. Settings), is currently open.
	$effect(() => {
		void ensureAllAlbumsLoaded();
	});

	$effect(() => {
		if ($libraryWallOrder === 'played') void ensureLastPlayedRead();
	});

	function retryLibraryLoad(): void {
		void ensureAllAlbumsLoaded();
	}

	// A single slot, not a set (issue #323, operator ruling): with 42 albums,
	// letting every once-opened row accumulate would stop showing where the
	// viewer IS. Opening an album row closes
	// whichever other album was open; this is local to the LIBRARY group, so
	// an open playlist in the sibling PLAYLISTS group is never affected (the
	// two groups do not share a slot).
	let expandedAlbumId: string | null = $state(null);

	// Edge-triggered like RailGroup's own expandTrigger idiom (see its comment):
	// previousShownAlbumId is a plain variable, not $state, so this effect only
	// force-expands an album the moment its detail *starts* showing, never on
	// every rerun while it stays shown -- otherwise a viewer could never
	// manually collapse the open album's row. The wall keeps an album open
	// without showing it, so landing there loads none of its songs.
	let previousShownAlbumId: string | null = null;
	$effect(() => {
		const enteredAlbum = shownAlbumId !== null && shownAlbumId !== previousShownAlbumId;
		previousShownAlbumId = shownAlbumId;
		if (enteredAlbum) expandAlbum(shownAlbumId as string);
	});

	function isAlbumExpanded(albumId: string): boolean {
		return expandedAlbumId === albumId;
	}

	function visibleSongsForAlbum(albumId: string): SongItem[] {
		const albumSongs = songsByAlbum.get(albumId) ?? [];
		if (!filtering) return albumSongs;
		return albumSongs.filter(
			(song) => song.id === currentSongId || matchesRailQuery(song.title, query)
		);
	}

	function hasMatchingSong(albumId: string): boolean {
		return filtering && visibleSongsForAlbum(albumId).length > 0;
	}

	// True once this album's songs are already in songList -- re-expanding an
	// already-loaded album on every click must not refetch it. Deliberately NOT
	// short-circuited by album.song_count === 0: that count is never invalidated
	// in this store and songs can appear from outside this tab (Co-Writer,
	// another device), so a once-empty album would otherwise stay blind for the
	// rest of the session. A genuinely empty album paying for a cheap empty
	// fetch on every expand is the accepted cost -- librarySearch.ts already
	// treats song_count itself as unreliable, correcting it against the loaded
	// song list rather than trusting it.
	function albumSongsKnown(albumId: string): boolean {
		return songs.some((song) => song.album_id === albumId);
	}

	function expandAlbum(albumId: string): void {
		expandedAlbumId = albumId;
		if (!albumSongsKnown(albumId)) void loadSongsForAlbum(albumId);
	}

	// An album row is its one destination: it opens the album and its songs
	// together. The caret below only reports this button's expanded state.
	function openAlbumFromRail(albumId: string): void {
		expandAlbum(albumId);
		void openAlbum(albumId);
	}

	function trackMeta(song: SongItem): string {
		if (songPlayability(song) === 'none') return RAIL_CONTEXT_NO_TAKES;
		const takes = `${song.generation_count} take${song.generation_count !== 1 ? 's' : ''}`;
		const hasPick = pickedTake(song) !== undefined;
		return hasPick ? `${takes} · pick` : takes;
	}

	function onTrackClick(song: SongItem): void {
		void selectSong(song.id, song);
	}
</script>

{#snippet icon()}
	<Icon name="library" size={14} />
{/snippet}

<RailGroup
	label={LIBRARY_PAGE_LABEL}
	groupId="rail-library-group"
	storageKey={LIBRARY_OPEN_STORAGE_KEY}
	count={albumCount}
	expandTrigger={libraryWallIsSurface || isAlbumDetail || loadFailure !== null || filtering}
	page={{
		href: resolve(LIBRARY_ROUTE_ID),
		current: onLibraryPage,
		open: () => void openRailSearchTarget({ kind: 'page', href: LIBRARY_ROUTE_PATH })
	}}
	{icon}
>
	{#snippet children(groupOpen: boolean)}
		<nav class="rail-library-nav" aria-label={RAIL_LIBRARY_NAV_LABEL}>
			{#if loadFailure !== null}
				<div class="rail-load-error">
					<p class="rail-status" role="alert">{loadFailure}</p>
					<button type="button" class="rail-retry" onclick={retryLibraryLoad}>
						{LIBRARY_RETRY_LABEL}
					</button>
				</div>
			{/if}
			<ul class="album-list">
				{#each visibleAlbums as album (album.id)}
					{@const expanded = isAlbumExpanded(album.id) || hasMatchingSong(album.id)}
					{@const current = album.id === shownAlbumId}
					<li>
						<button
							type="button"
							class={RAIL_ALBUM_ITEM_CLASS}
							aria-current={current ? 'page' : undefined}
							use:revealOpenRailItem={current && groupOpen && !filtering}
							aria-expanded={expanded}
							aria-controls={`rail-library-album-${album.id}`}
							onclick={() => openAlbumFromRail(album.id)}
						>
							<svg
								class="caret"
								class:open={expanded}
								width="10"
								height="10"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="3"
								stroke-linecap="round"
								stroke-linejoin="round"
								aria-hidden="true"
							>
								<polyline points="9 6 15 12 9 18" />
							</svg>
							<span class="album-art">
								{#if album.cover?.card}
									<img src={album.cover.card} alt={`${ALBUM_COVER_ALT_TYPE} ${album.title}`} />
								{:else}
									<span aria-hidden="true">{titleInitials(album.title)}</span>
								{/if}
							</span>
							<span class="row-title">{album.title}</span>
							<span class="row-meta">{album.song_count}</span>
						</button>
						<div
							class="album-songs"
							data-open={expanded}
							inert={!expanded}
							id={`rail-library-album-${album.id}`}
						>
							<div class="album-songs-content">
								{#if expanded}
									<ul>
										{#each [...visibleSongsForAlbum(album.id)].sort(compareAlbumTracks) as song (song.id)}
											<li>
												<button
													type="button"
													class="row row-sub2"
													class:row-active={song.id === currentSongId}
													onclick={() => onTrackClick(song)}
												>
													<PlayingMark current={isSongCurrent(song.id)} />
													<span class="row-title">{song.title}</span>
													<span class="row-meta">{trackMeta(song)}</span>
												</button>
											</li>
										{/each}
									</ul>
								{/if}
							</div>
						</div>
					</li>
				{/each}
			</ul>
		</nav>
	{/snippet}
</RailGroup>

<style>
	.album-list {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.rail-status {
		margin: 0;
		font-size: 0.8rem;
		color: var(--score-bad);
		overflow-wrap: anywhere;
	}

	.rail-load-error {
		display: grid;
		gap: 8px;
		min-width: 0;
		margin: 4px 8px 8px;
		padding: 8px;
		border-left: 3px solid var(--score-bad);
		background: var(--score-bad-bg);
	}

	.rail-retry {
		justify-self: start;
		max-width: 100%;
		padding: 4px 8px;
		background: none;
		border: 1px solid var(--score-bad);
		color: var(--score-bad);
		font-size: 0.75rem;
		font-family: inherit;
		cursor: pointer;
	}

	.rail-retry:hover {
		background: var(--score-bad-bg);
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

	.album-label {
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

	.album-label:hover {
		background: var(--surface-hover);
		color: var(--text);
	}

	.album-art {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 20px;
		height: 20px;
		flex: 0 0 20px;
		overflow: hidden;
		border-radius: 3px;
		background: var(--surface-hover);
		font-family: var(--font-display);
		font-size: 0.55rem;
		letter-spacing: 0.04em;
		color: var(--text);
	}

	.album-art img {
		width: 100%;
		height: 100%;
		object-fit: cover;
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

	.caret {
		flex-shrink: 0;
		transition: transform 0.16s ease;
	}

	.caret.open {
		transform: rotate(90deg);
	}

	.album-songs {
		display: grid;
		grid-template-rows: 0fr;
		transition: grid-template-rows 0.2s ease;
	}

	.album-songs[data-open='true'] {
		grid-template-rows: 1fr;
	}

	.album-songs-content {
		overflow: hidden;
	}

	.album-songs-content ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	@media (prefers-reduced-motion: reduce) {
		.caret,
		.album-songs {
			transition: none;
		}
	}
</style>
