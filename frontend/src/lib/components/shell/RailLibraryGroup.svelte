<script lang="ts">
	import { openCollection } from '$lib/stores/collection';
	import {
		albumList,
		ensureAllAlbumsLoaded,
		loadSongsForAlbum,
		songList
	} from '$lib/stores/libraryData';
	import { selectedSongId } from '$lib/stores/player';
	import {
		compareAlbumTracks,
		openAlbum,
		openLibraryFilter,
		selectSong
	} from '$lib/stores/navigation';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import {
		RAIL_ALBUM_DISCLOSE_LABEL,
		RAIL_CONTEXT_NO_TAKES,
		RAIL_LIBRARY_LABEL,
		RAIL_LIBRARY_NAV_LABEL
	} from '$lib/constants';
	import type { SongItem } from '$lib/api/types';
	import RailGroup from './RailGroup.svelte';

	// Local to this component rather than promoted to constants.ts: nothing
	// else reads this key, matching how RailGroup's own groupId is already
	// inlined per caller (see RailSettings.svelte) rather than centralized.
	const LIBRARY_OPEN_STORAGE_KEY = 'songmaker.rail-library-open';

	const albums = $derived($albumList);
	const songs = $derived($songList);
	const collection = $derived($openCollection);
	const currentSongId = $derived($selectedSongId);
	const current = $derived(audioPlayer.current);
	const playing = $derived(audioPlayer.status === 'playing');
	const openAlbumId = $derived(collection?.kind === 'album' ? collection.id : null);

	// ensureAllAlbumsLoaded is route-independent (#304) -- the rail needs the
	// complete album list regardless of which library page, or which non-library
	// route (e.g. Settings), is currently open.
	$effect(() => {
		void ensureAllAlbumsLoaded();
	});

	// A single slot, not a set (issue #323, operator ruling): with 42 albums,
	// letting every once-opened row accumulate would stop showing where the
	// viewer IS. Opening an album -- by its label or its own chevron -- closes
	// whichever other album was open; this is local to the LIBRARY group, so
	// an open playlist in the sibling PLAYLISTS group is never affected (the
	// two groups do not share a slot).
	let expandedAlbumId: string | null = $state(null);

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

	function albumTracks(albumId: string): SongItem[] {
		return songs.filter((song) => song.album_id === albumId).sort(compareAlbumTracks);
	}

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

	function toggleAlbum(albumId: string): void {
		if (isAlbumExpanded(albumId)) {
			expandedAlbumId = null;
			return;
		}
		expandAlbum(albumId);
	}

	function onLibraryTitleClick(): void {
		void openLibraryFilter('albums');
	}

	// The row's label is the navigation target (ruled sentence 5 of #302: a
	// list entry click goes directly into that album), the same openAlbum
	// LibraryWall's own album cards already use -- not goto/pushState, and not
	// openCollectionEntry, whose "song open -> back to collection" branch reads
	// the *currently* open collection regardless of which row was clicked and
	// would misfire for any row that isn't it. expandAlbum runs unconditionally
	// first (idempotent) so a label click always shows the album's songs even
	// when the album was already open but its row had been manually collapsed,
	// a case openAlbum's own collection change alone would not re-trigger (see
	// the edge-triggered effect above).
	function onAlbumLabelClick(albumId: string): void {
		expandAlbum(albumId);
		void openAlbum(albumId);
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

<RailGroup
	label={RAIL_LIBRARY_LABEL}
	groupId="rail-library-group"
	storageKey={LIBRARY_OPEN_STORAGE_KEY}
	count={albums.length}
	expandTrigger={openAlbumId !== null}
	onTitleClick={onLibraryTitleClick}
	{icon}
>
	<nav class="rail-library-nav" aria-label={RAIL_LIBRARY_NAV_LABEL}>
		<ul class="album-list">
			{#each albums as album (album.id)}
				{@const expanded = isAlbumExpanded(album.id)}
				<li>
					<div class="album-row">
						<button
							type="button"
							class="album-disclose"
							aria-expanded={expanded}
							aria-controls={`rail-library-album-${album.id}`}
							aria-label={RAIL_ALBUM_DISCLOSE_LABEL}
							onclick={() => toggleAlbum(album.id)}
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
						</button>
						<button
							type="button"
							class="album-label"
							class:row-active={album.id === openAlbumId}
							onclick={() => onAlbumLabelClick(album.id)}
						>
							<span class="row-title">{album.title}</span>
							<span class="row-meta">{album.song_count}</span>
						</button>
					</div>
					<div
						class="album-songs"
						data-open={expanded}
						id={`rail-library-album-${album.id}`}
						inert={!expanded}
					>
						<div class="album-songs-content">
							<ul>
								{#each albumTracks(album.id) as song (song.id)}
									<li>
										<button
											type="button"
											class="row row-sub2"
											class:row-active={song.id === currentSongId}
											onclick={() => onTrackClick(song)}
										>
											{#if isSongPlaying(song)}
												<span class="equalizer" aria-hidden="true">
													<span></span><span></span><span></span>
												</span>
											{/if}
											<span class="row-title">{song.title}</span>
											<span class="row-meta">{trackMeta(song)}</span>
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
</RailGroup>

<style>
	.album-list {
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

	/* Mirrors RailGroup's own .disclose-row/.disclose/.group-title-action split:
	   the chevron toggles only, the label navigates only -- see
	   onAlbumLabelClick's own comment for why they must be two elements. */
	.album-row {
		display: flex;
		align-items: center;
		color: var(--text-muted);
		font-size: 0.8rem;
	}

	.album-disclose {
		display: flex;
		align-items: center;
		padding: 8px 4px 8px 32px;
		background: none;
		border: none;
		color: inherit;
		cursor: pointer;
	}

	.album-disclose:hover {
		color: var(--text);
	}

	.album-label {
		display: flex;
		align-items: center;
		gap: 8px;
		flex: 1;
		min-width: 0;
		padding: 8px 16px 8px 4px;
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
