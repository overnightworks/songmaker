<script lang="ts">
	import { openPlaylist } from '$lib/stores/navigation';
	import {
		ensurePlaylistsLoaded,
		playlistList,
		selectedPlaylistDetail,
		selectedPlaylistId
	} from '$lib/stores/playlists';
	import { isPlaylistEntryCurrent, playPlaylistEntryAndShowNowPlaying } from '$lib/stores/player';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import { railTreeQuery } from '$lib/stores/filter';
	import {
		RAIL_PLAYING_MARKER_LABEL,
		RAIL_PLAYLISTS_LABEL,
		RAIL_PLAYLISTS_NAV_LABEL
	} from '$lib/constants';
	import type { PlaylistEntryItem } from '$lib/api/types';
	import PlaylistCover from '../PlaylistCover.svelte';
	import RailGroup from './RailGroup.svelte';
	import { RAIL_PLAYLIST_ITEM_CLASS } from './rail-item-selector';

	// Local to this component, matching RailLibraryGroup's own
	// LIBRARY_OPEN_STORAGE_KEY -- nothing else reads this key.
	const PLAYLISTS_OPEN_STORAGE_KEY = 'songmaker.rail-playlists-open';

	const playlists = $derived($playlistList);
	// Tracks exist only for the currently open playlist: loadPlaylistDetail
	// navigates as a side effect (openPlaylist in stores/navigation.ts), and
	// the frozen picture (docs/design/navigation.html) draws playlist rows
	// with no chevron in any state.
	const openPlaylistId = $derived($selectedPlaylistId);
	const openPlaylistDetail = $derived($selectedPlaylistDetail);
	const playing = $derived(audioPlayer.status === 'playing');
	const query = $derived($railTreeQuery.trim().toLowerCase());
	const filtering = $derived(query.length > 0);
	const visiblePlaylists = $derived(
		playlists.filter(
			(playlist) =>
				!filtering || playlist.id === openPlaylistId || playlist.title.toLowerCase().includes(query)
		)
	);

	// ensurePlaylistsLoaded is route-independent, mirroring
	// ensureAllAlbumsLoaded in RailLibraryGroup -- the rail needs the complete
	// playlist list regardless of which route is open.
	$effect(() => {
		void ensurePlaylistsLoaded();
	});

	function isEntryPlaying(entry: PlaylistEntryItem): boolean {
		return isPlaylistEntryCurrent(entry) && playing;
	}

	function onPlaylistLabelClick(playlistId: string): void {
		void openPlaylist(playlistId);
	}

	function onEntryClick(index: number): void {
		if (!openPlaylistDetail) return;
		void playPlaylistEntryAndShowNowPlaying(openPlaylistDetail, index);
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
		<path d="M9 18V5l12-2v13" />
		<circle cx="6" cy="18" r="3" />
		<circle cx="18" cy="16" r="3" />
	</svg>
{/snippet}

<RailGroup
	label={RAIL_PLAYLISTS_LABEL}
	groupId="rail-playlists-group"
	storageKey={PLAYLISTS_OPEN_STORAGE_KEY}
	count={playlists.length}
	expandTrigger={openPlaylistId !== null || filtering}
	{icon}
>
	{#snippet children(open: boolean)}
		<nav class="rail-playlists-nav" aria-label={RAIL_PLAYLISTS_NAV_LABEL}>
			<ul class="playlist-list">
				{#each visiblePlaylists as playlist (playlist.id)}
					{@const expanded = playlist.id === openPlaylistId}
					{@const entries =
						expanded && openPlaylistDetail?.id === playlist.id ? openPlaylistDetail.entries : []}
					<li>
						<button
							type="button"
							class={RAIL_PLAYLIST_ITEM_CLASS}
							class:row-active={expanded}
							onclick={() => onPlaylistLabelClick(playlist.id)}
						>
							<PlaylistCover
								title={playlist.title}
								covers={playlist.album_covers}
								cover={playlist.cover}
								visible={open}
							/>
							<span class="row-title">{playlist.title}</span>
							<span class="row-meta">{playlist.entry_count}</span>
						</button>
						<div class="playlist-songs" data-open={expanded} inert={!expanded}>
							<div class="playlist-songs-content">
								<ul>
									{#each entries as entry, index (entry.id)}
										<li>
											<button
												type="button"
												class="row row-sub2"
												class:row-active={isPlaylistEntryCurrent(entry)}
												onclick={() => onEntryClick(index)}
											>
												{#if isEntryPlaying(entry)}
													<span class="equalizer" role="img" aria-label={RAIL_PLAYING_MARKER_LABEL}>
														<span></span><span></span><span></span>
													</span>
												{/if}
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
