<script lang="ts">
	import AgeStamp from './AgeStamp.svelte';
	import SongNode from './SongNode.svelte';
	import type { AlbumItem, SongItem } from '$lib/api/types';
	import {
		ALBUM_COVER_ALT_TYPE,
		LIBRARY_ALBUMS_LOADING,
		LIBRARY_RETRY_LABEL
	} from '$lib/constants';
	import { titleInitials } from '$lib/utils/format';
	import type { AlbumSongsLoadState } from '$lib/stores/libraryData';
	import { usableAlbumPrimary } from '$lib/utils/contrast';

	interface Props {
		album: AlbumItem;
		songs?: SongItem[];
		expanded?: boolean;
		selected: boolean;
		showCreatedAge?: boolean;
		loadState?: AlbumSongsLoadState;
		onselect: () => void;
		onretry?: () => void;
	}

	let {
		album,
		songs = [],
		expanded = false,
		selected,
		showCreatedAge = true,
		loadState,
		onselect,
		onretry
	}: Props = $props();

	const cardTitle = $derived(album.title);
	const cardArtist = $derived(album.artist);
	const cardCount = $derived(album.song_count);
	const cardCreatedAt = $derived(album.created_at);
	const cardColors = $derived(album.colors ?? {});
	const cardCover = $derived(album.cover ?? null);
	const artFill = $derived(usableAlbumPrimary(cardColors));
	const initials = $derived(titleInitials(cardTitle));
	const coverUrl = $derived(cardCover?.card ?? null);
	let coverFailed = $state(false);

	$effect(() => {
		void coverUrl;
		coverFailed = false;
	});

	const showCover = $derived(Boolean(coverUrl) && !coverFailed);
	const coverAlt = $derived(`${ALBUM_COVER_ALT_TYPE} ${cardTitle}`);
</script>

<div class="album-group">
	<button type="button" class="album-card album-hit" class:selected onclick={onselect}>
		{#if showCover && coverUrl}
			<span class="album-art">
				<img src={coverUrl} alt={coverAlt} onerror={() => (coverFailed = true)} />
			</span>
		{:else if artFill}
			<span class="album-art" style:background={artFill} aria-hidden="true"></span>
		{:else}
			<span class="album-art album-art-initials" aria-hidden="true">{initials}</span>
		{/if}
		<span class="album-text">
			<span class="album-title">{cardTitle}</span>
			{#if cardArtist}
				<span class="album-artist">{cardArtist}</span>
			{/if}
		</span>
		{#if showCreatedAge}
			<span class="album-age">
				<AgeStamp createdAt={cardCreatedAt} named />
			</span>
		{/if}
		<span class="album-count">{cardCount}</span>
	</button>

	{#if expanded}
		{#if loadState?.status === 'loading' && songs.length === 0}
			<p class="album-status" role="status">{LIBRARY_ALBUMS_LOADING}</p>
		{:else if loadState?.status === 'error'}
			<p class="album-status" role="alert">{loadState.error}</p>
			{#if onretry}
				<button type="button" class="album-retry" onclick={onretry}>{LIBRARY_RETRY_LABEL}</button>
			{/if}
		{/if}
		{#each songs as song (song.id)}
			<SongNode {song} />
		{/each}
	{/if}
</div>

<style>
	.album-group {
		min-width: 0;
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface);
		overflow: hidden;
	}

	.album-card {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		grid-template-rows: auto auto auto;
		align-items: center;
		gap: 4px 8px;
		width: 100%;
		min-width: 0;
		padding: 8px;
		background: transparent;
		border: none;
		color: var(--text);
		font-family: var(--font-body);
		cursor: pointer;
		text-align: left;
	}

	.album-card:hover {
		background: var(--surface-hover);
	}

	.album-card.selected {
		background: rgba(160, 32, 240, 0.06);
		box-shadow: inset 3px 0 0 var(--accent);
	}

	.album-card:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}

	.album-art {
		grid-column: 1 / -1;
		display: flex;
		align-items: center;
		justify-content: center;
		width: 100%;
		aspect-ratio: 1;
		background: var(--surface-hover);
		color: var(--text);
		font-family: var(--font-display);
		font-size: 1.6rem;
		letter-spacing: 0.06em;
		user-select: none;
		overflow: hidden;
	}

	.album-art img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}

	.album-text {
		grid-column: 1 / -1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.album-title {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-family: var(--font-display);
		font-size: 0.9rem;
		letter-spacing: 0.4px;
	}

	.album-artist {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 0.72rem;
		color: var(--text-muted);
	}

	.album-age {
		min-width: 0;
	}

	.album-count {
		font-size: 0.6rem;
		color: var(--text-subtle);
		flex-shrink: 0;
	}

	.album-hit {
		grid-template-columns: 3.5rem minmax(0, 1fr) auto auto;
		grid-template-rows: auto auto;
		align-items: center;
	}

	.album-hit .album-art {
		grid-column: 1;
		grid-row: 1 / span 2;
		width: 3.5rem;
		height: 3.5rem;
		aspect-ratio: auto;
		font-size: 0.85rem;
	}

	.album-hit .album-text {
		grid-column: 2;
		grid-row: 1 / span 2;
	}

	.album-hit .album-age {
		grid-column: 3;
		grid-row: 1 / span 2;
	}

	.album-hit .album-count {
		grid-column: 4;
		grid-row: 1 / span 2;
	}

	.album-status {
		margin: 0;
		padding: 8px 12px;
		font-size: 0.8rem;
		color: var(--text-muted);
	}

	.album-retry {
		margin: 0 12px 8px;
		padding: 4px 8px;
		background: none;
		border: 1px solid var(--border);
		color: var(--text);
		font-size: 0.75rem;
		cursor: pointer;
	}

	@media (max-width: 768px) {
		.album-card {
			grid-template-columns: 3.5rem minmax(0, 1fr) auto auto;
			grid-template-rows: auto auto;
			align-items: center;
		}

		.album-art {
			grid-column: 1;
			grid-row: 1 / span 2;
			width: 3.5rem;
			height: 3.5rem;
			aspect-ratio: auto;
			font-size: 0.85rem;
		}

		.album-text {
			grid-column: 2;
			grid-row: 1 / span 2;
		}

		.album-age {
			grid-column: 3;
			grid-row: 1 / span 2;
		}

		.album-count {
			grid-column: 4;
			grid-row: 1 / span 2;
		}
	}
</style>
