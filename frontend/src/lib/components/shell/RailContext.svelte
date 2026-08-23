<script lang="ts">
	import { openCollection } from '$lib/stores/collection';
	import {
		albumList,
		playPlaylistEntries,
		selectedSongId,
		setShuffle,
		songList
	} from '$lib/stores/player';
	import { compareAlbumTracks, openCollectionEntry, selectSong } from '$lib/stores/navigation';
	import { librarySurface } from '$lib/stores/libraryContext';
	import { selectedPlaylistDetail } from '$lib/stores/playlists';
	import { audioPlayer } from '$lib/services/audioPlayer.svelte';
	import { titleInitials } from '$lib/utils/format';
	import {
		ALBUM_ART_EMPTY_INITIALS,
		RAIL_CONTEXT_EMPTY,
		RAIL_CONTEXT_NO_TAKES
	} from '$lib/constants';
	import type { PlaylistEntryItem, SongItem } from '$lib/api/types';

	const collection = $derived($openCollection);
	const albums = $derived($albumList);
	const songs = $derived($songList);
	const playlistDetail = $derived($selectedPlaylistDetail);
	const currentSongId = $derived($selectedSongId);
	const current = $derived(audioPlayer.current);
	const playing = $derived(audioPlayer.status === 'playing');

	const album = $derived(
		collection?.kind === 'album' ? (albums.find((a) => a.id === collection.id) ?? null) : null
	);
	const albumTracks = $derived(
		collection?.kind === 'album'
			? songs.filter((song) => song.album_id === collection.id).sort(compareAlbumTracks)
			: []
	);

	const title = $derived(
		collection?.kind === 'album' ? (album?.title ?? '') : (playlistDetail?.title ?? '')
	);
	const initials = $derived(title ? titleInitials(title) : ALBUM_ART_EMPTY_INITIALS);
	// The interior (AlbumDetailView/PlaylistDetailView) is the visible surface
	// only once a song stops covering it — see routes/+page.svelte's
	// song-first precedence.
	const isInteriorVisible = $derived($librarySurface === 'detail' && currentSongId === null);

	function isSongPlaying(song: SongItem): boolean {
		return current?.songId === song.id && playing;
	}

	function trackMeta(song: SongItem): string {
		if (song.generation_count === 0) return RAIL_CONTEXT_NO_TAKES;
		const takes = `${song.generation_count} take${song.generation_count !== 1 ? 's' : ''}`;
		const hasPick = song.generations.some((generation) => generation.is_picked);
		return hasPick ? `${takes} · pick` : takes;
	}

	function isEntryCurrent(entry: PlaylistEntryItem): boolean {
		return (
			current?.generation.id === entry.generation_id &&
			current?.generation.mp3_path === entry.mp3_path
		);
	}

	function isEntryPlaying(entry: PlaylistEntryItem): boolean {
		return isEntryCurrent(entry) && playing;
	}

	function onAlbumTrackClick(song: SongItem): void {
		selectSong(song.id, song);
	}

	function onPlaylistEntryClick(index: number): void {
		if (!playlistDetail) return;
		const entry = playlistDetail.entries[index];
		if (entry && isEntryCurrent(entry)) {
			audioPlayer.toggle();
			return;
		}
		setShuffle(false);
		playPlaylistEntries(playlistDetail.entries, index, { restart: true });
	}

	// A song (or take) open inside the collection covers the interior even
	// while librarySurface stays 'detail' (see +page.svelte's song-first
	// precedence) — clicking the header then means "back to the collection",
	// which replaces history instead of pushing a fresh detail entry.
	function onHeaderClick(): void {
		if (!collection) return;
		openCollectionEntry(collection);
	}
</script>

{#snippet contextHead()}
	<button
		type="button"
		class="context-head"
		onclick={onHeaderClick}
		aria-current={isInteriorVisible ? 'page' : undefined}
	>
		<span class="context-cover" aria-hidden="true">{initials}</span>
		<span class="context-title">{title}</span>
		<svg
			class="context-chevron"
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
			<polyline points="9 6 15 12 9 18" />
		</svg>
	</button>
{/snippet}

{#if collection?.kind === 'album' && album}
	<div class="rail-context">
		{@render contextHead()}
		<div class="context-tracks">
			{#each albumTracks as song (song.id)}
				<button
					type="button"
					class="context-row"
					class:selected={song.id === currentSongId}
					onclick={() => onAlbumTrackClick(song)}
				>
					{#if isSongPlaying(song)}
						<span class="equalizer" aria-hidden="true">
							<span></span><span></span><span></span>
						</span>
					{/if}
					<span class="context-row-title">{song.title}</span>
					<span class="context-row-meta">{trackMeta(song)}</span>
				</button>
			{/each}
		</div>
	</div>
{:else if collection?.kind === 'playlist' && playlistDetail}
	<div class="rail-context">
		{@render contextHead()}
		<div class="context-tracks">
			{#each playlistDetail.entries as entry, index (entry.id)}
				<button
					type="button"
					class="context-row"
					class:selected={isEntryCurrent(entry)}
					onclick={() => onPlaylistEntryClick(index)}
				>
					{#if isEntryPlaying(entry)}
						<span class="equalizer" aria-hidden="true">
							<span></span><span></span><span></span>
						</span>
					{/if}
					<span class="context-row-title">{entry.song_title}</span>
				</button>
			{/each}
		</div>
	</div>
{:else}
	<p class="context-empty">{RAIL_CONTEXT_EMPTY}</p>
{/if}

<style>
	.rail-context {
		display: flex;
		flex-direction: column;
		min-height: 0;
		overflow-y: auto;
		padding: 8px 0;
	}

	.context-head {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 4px 16px 8px;
		background: none;
		border: none;
		cursor: pointer;
		text-align: left;
	}

	.context-head:hover .context-title {
		color: var(--primary);
	}

	.context-head[aria-current='page'] .context-title {
		color: var(--primary);
	}

	.context-cover {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		flex-shrink: 0;
		background: var(--surface-hover);
		color: var(--text);
		font-family: var(--font-display);
		font-size: 0.65rem;
		letter-spacing: 0.06em;
	}

	.context-title {
		flex: 1;
		min-width: 0;
		font-family: var(--font-display);
		font-size: 0.8rem;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 0.5px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.context-chevron {
		flex-shrink: 0;
		color: var(--text-subtle);
	}

	.context-tracks {
		display: flex;
		flex-direction: column;
	}

	.context-row {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 6px 16px 6px 20px;
		background: none;
		border: none;
		border-left: 3px solid transparent;
		color: var(--text-muted);
		font-size: 0.8rem;
		text-align: left;
		cursor: pointer;
	}

	.context-row:hover {
		background: var(--surface-hover);
		color: var(--text);
	}

	.context-row.selected {
		border-left-color: var(--accent);
		color: var(--text);
		background: color-mix(in srgb, var(--accent) 8%, transparent);
	}

	.context-row-title {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.context-row-meta {
		flex-shrink: 0;
		font-size: 0.68rem;
		color: var(--text-subtle);
	}

	.context-empty {
		margin: 0;
		padding: 12px 16px;
		font-size: 0.75rem;
		color: var(--text-subtle);
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
