<script lang="ts">
	import { untrack } from 'svelte';
	import { openCollection } from '$lib/stores/collection';
	import { librarySurface } from '$lib/stores/libraryContext';
	import {
		albumList,
		allAlbumsLoad,
		ensureAllAlbumsLoaded,
		loadSongsForAlbum,
		songList
	} from '$lib/stores/libraryData';
	import { selectedSongId } from '$lib/stores/player';
	import {
		compareAlbumTracks,
		openAlbum,
		openLibraryWall,
		selectSong
	} from '$lib/stores/navigation';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import {
		ALBUM_COVER_ALT_TYPE,
		LIBRARY_RETRY_LABEL,
		RAIL_CONTEXT_NO_TAKES,
		RAIL_LIBRARY_LABEL,
		RAIL_LIBRARY_LOAD_ERROR,
		RAIL_LIBRARY_NAV_LABEL,
		RAIL_PLAYING_MARKER_LABEL
	} from '$lib/constants';
	import type { SongItem } from '$lib/api/types';
	import { titleInitials } from '$lib/utils/format';
	import RailGroup from './RailGroup.svelte';
	import { RAIL_ALBUM_ITEM_CLASS } from './rail-item-selector';

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
	const current = $derived(audioPlayer.current);
	const playing = $derived(audioPlayer.status === 'playing');
	const openAlbumId = $derived(collection?.kind === 'album' ? collection.id : null);
	const isAlbumDetail = $derived(surface === 'detail' && openAlbumId !== null);
	const loadStatus = $derived($allAlbumsLoad.status);
	const loadError = $derived($allAlbumsLoad.error);

	// ensureAllAlbumsLoaded is route-independent (#304) -- the rail needs the
	// complete album list regardless of which library page, or which non-library
	// route (e.g. Settings), is currently open.
	$effect(() => {
		void ensureAllAlbumsLoaded();
	});

	function retryLibraryLoad(): void {
		void ensureAllAlbumsLoaded();
	}

	// A single slot, not a set (issue #323, operator ruling): with 42 albums,
	// letting every once-opened row accumulate would stop showing where the
	// viewer IS. Opening an album -- by its label or its own chevron -- closes
	// whichever other album was open; this is local to the LIBRARY group, so
	// an open playlist in the sibling PLAYLISTS group is never affected (the
	// two groups do not share a slot).
	let expandedAlbumId: string | null = $state(null);
	let libraryGroupMount = $state(0);

	function persistLibraryOpen(value: boolean): void {
		try {
			localStorage.setItem(LIBRARY_OPEN_STORAGE_KEY, String(value));
		} catch {
			// The disclosure remains usable when browser storage is unavailable.
		}
	}

	function closeLibraryGroupForWall(): void {
		persistLibraryOpen(false);
		libraryGroupMount = untrack(() => libraryGroupMount) + 1;
	}

	// The wall already is the library's album view. Recreate just this
	// persisted disclosure after entering it so RailGroup reads the closed
	// value; an album detail still uses its rising expandTrigger below.
	$effect(() => {
		if (surface === 'browse') closeLibraryGroupForWall();
	});

	// Edge-triggered like RailGroup's own expandTrigger idiom (see its comment):
	// previousOpenAlbumId is a plain variable, not $state, so this effect only
	// force-expands an album the moment it *becomes* the open one, never on
	// every rerun while it stays open -- otherwise a viewer could never
	// manually collapse the open album's row.
	let previousOpenAlbumId: string | null = null;
	$effect(() => {
		const enteredAlbum = openAlbumId !== null && openAlbumId !== previousOpenAlbumId;
		previousOpenAlbumId = openAlbumId;
		if (enteredAlbum) expandAlbum(openAlbumId as string);
	});

	function isAlbumExpanded(albumId: string): boolean {
		return expandedAlbumId === albumId;
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

	function openAllAlbums(): void {
		closeLibraryGroupForWall();
		void openLibraryWall();
	}

	function isSongPlaying(song: SongItem): boolean {
		return current?.songId === song.id && playing;
	}

	function trackMeta(song: SongItem): string {
		if (song.generation_count === 0) return RAIL_CONTEXT_NO_TAKES;
		const takes = `${song.generation_count} take${song.generation_count !== 1 ? 's' : ''}`;
		const hasPick = song.generations.some((generation) => generation.is_picked);
		return hasPick ? `${takes} · pick` : takes;
	}

	function onTrackClick(song: SongItem): void {
		void selectSong(song.id, song);
	}
</script>

{#snippet icon()}
	<svg
		width="14"
		height="14"
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		aria-hidden="true"
	>
		<rect x="3" y="3" width="7" height="7" rx="1" />
		<rect x="14" y="3" width="7" height="7" rx="1" />
		<rect x="3" y="14" width="7" height="7" rx="1" />
		<rect x="14" y="14" width="7" height="7" rx="1" />
	</svg>
{/snippet}

{#key libraryGroupMount}
	<RailGroup
		label={RAIL_LIBRARY_LABEL}
		groupId="rail-library-group"
		storageKey={LIBRARY_OPEN_STORAGE_KEY}
		count={albums.length}
		expandTrigger={isAlbumDetail || loadStatus === 'error'}
		{icon}
	>
		<nav class="rail-library-nav" aria-label={RAIL_LIBRARY_NAV_LABEL}>
			{#if loadStatus === 'error'}
				<div class="rail-load-error">
					<p class="rail-status" role="alert">{loadError ?? RAIL_LIBRARY_LOAD_ERROR}</p>
					<button type="button" class="rail-retry" onclick={retryLibraryLoad}>
						{LIBRARY_RETRY_LABEL}
					</button>
				</div>
			{/if}
			<ul class="album-list">
				<li>
					<button type="button" class="all-albums" onclick={openAllAlbums}>
						<svg
							class="caret"
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
						<span class="row-title">All albums</span>
						<span class="row-meta">{albums.length}</span>
					</button>
				</li>
				{#each albums as album (album.id)}
					{@const expanded = isAlbumExpanded(album.id)}
					<li>
						<button
							type="button"
							class={RAIL_ALBUM_ITEM_CLASS}
							class:row-active={album.id === openAlbumId}
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
										{#each [...(songsByAlbum.get(album.id) ?? [])].sort(compareAlbumTracks) as song (song.id)}
											<li>
												<button
													type="button"
													class="row row-sub2"
													class:row-active={song.id === currentSongId}
													onclick={() => onTrackClick(song)}
												>
													{#if isSongPlaying(song)}
														<span
															class="equalizer"
															role="img"
															aria-label={RAIL_PLAYING_MARKER_LABEL}
														>
															<span></span><span></span><span></span>
														</span>
													{/if}
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
	</RailGroup>
{/key}

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

	.all-albums {
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

	.all-albums:hover {
		background: var(--surface-hover);
		color: var(--text);
	}

	.album-label {
		display: flex;
		align-items: center;
		gap: 8px;
		flex: 1;
		min-width: 0;
		padding: 8px 16px 8px 32px;
		background: none;
		border: none;
		color: inherit;
		font: inherit;
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

	.equalizer {
		display: inline-flex;
		align-items: flex-end;
		gap: 2px;
		width: 12px;
		height: 12px;
		flex-shrink: 0;
	}

	.equalizer span {
		width: 2px;
		background: var(--accent);
		animation: equalize 0.9s ease-in-out infinite;
	}

	.equalizer span:nth-child(1) {
		height: 40%;
		animation-delay: -0.6s;
	}

	.equalizer span:nth-child(2) {
		height: 100%;
		animation-delay: -0.3s;
	}

	.equalizer span:nth-child(3) {
		height: 65%;
	}

	@media (prefers-reduced-motion: reduce) {
		.equalizer span {
			animation: none;
		}
	}

	@keyframes equalize {
		0%,
		100% {
			height: 30%;
		}
		50% {
			height: 100%;
		}
	}
</style>
