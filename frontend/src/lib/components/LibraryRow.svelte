<script lang="ts">
	import type { AlbumItem, PlaylistItem } from '$lib/api/types';
	import type { OpenCollection } from '$lib/stores/collection';
	import { albumList } from '$lib/stores/libraryData';
	import { playlistList } from '$lib/stores/playlists';
	import { librarySort } from '$lib/stores/librarySearch';
	import { openAlbum, openPlaylist } from '$lib/stores/navigation';
	import { kineticScroll } from '$lib/actions/kineticScroll';
	import { compareByCreatedAt } from '$lib/utils/recency';
	import { usableAlbumPrimary } from '$lib/utils/contrast';
	import { albumSummaryLabel, playlistSummaryLabel, titleInitials } from '$lib/utils/format';
	import { ALBUM_COVER_ALT_TYPE, LIBRARY_FILTER_LABELS } from '$lib/constants';

	interface Props {
		collection: OpenCollection;
	}

	let { collection }: Props = $props();

	interface RowTile {
		id: string;
		title: string;
		subtitle: string;
		coverUrl: string | null;
		fill: string | null;
	}

	function albumTile(album: AlbumItem): RowTile {
		return {
			id: album.id,
			title: album.title,
			subtitle: albumSummaryLabel(album.song_count, album.picked_count),
			coverUrl: album.cover?.card ?? null,
			fill: usableAlbumPrimary(album.colors)
		};
	}

	function playlistTile(playlist: PlaylistItem): RowTile {
		return {
			id: playlist.id,
			title: playlist.title,
			subtitle: playlistSummaryLabel(playlist.entry_count),
			coverUrl: null,
			fill: null
		};
	}

	const sort = $derived($librarySort);

	// Fed from the same album/playlist state and the same creation-order
	// comparator the full wall uses (LibraryWall.svelte's albumGroups /
	// orderedPlaylists) so the row and the wall never disagree on order --
	// the row just skips the wall's search/archive/share branches, which
	// don't apply once a collection is already open.
	const tiles = $derived.by((): RowTile[] =>
		collection.kind === 'album'
			? [...$albumList].sort((a, b) => compareByCreatedAt(a, b, sort)).map(albumTile)
			: [...$playlistList].sort((a, b) => compareByCreatedAt(a, b, sort)).map(playlistTile)
	);

	const rowLabel = $derived(
		collection.kind === 'album' ? LIBRARY_FILTER_LABELS.albums : LIBRARY_FILTER_LABELS.playlists
	);

	function openTile(item: HTMLElement): void {
		const id = item.dataset.tileId;
		if (!id) return;
		if (collection.kind === 'album') void openAlbum(id);
		else void openPlaylist(id);
	}
</script>

<div class="library-row-scrim">
	<div
		class="library-row"
		aria-label={rowLabel}
		use:kineticScroll={{ itemSelector: '.row-tile', onOpen: openTile }}
	>
		{#each tiles as tile (tile.id)}
			<button
				type="button"
				class="row-tile"
				class:active={tile.id === collection.id}
				data-tile-id={tile.id}
				aria-current={tile.id === collection.id}
				title={tile.title}
			>
				<span class="row-tile-cover">
					{#if tile.coverUrl}
						<img src={tile.coverUrl} alt={`${ALBUM_COVER_ALT_TYPE} ${tile.title}`} />
					{:else if tile.fill}
						<span class="row-tile-cover-fill" style:background={tile.fill} aria-hidden="true"
						></span>
					{:else}
						<span class="row-tile-cover-fill row-tile-cover-initials" aria-hidden="true"
							>{titleInitials(tile.title)}</span
						>
					{/if}
				</span>
				<span class="row-tile-meta">
					<span class="row-tile-title">{tile.title}</span>
					<span class="row-tile-subtitle">{tile.subtitle}</span>
				</span>
			</button>
		{/each}
	</div>
</div>

<style>
	.library-row-scrim {
		position: relative;
		flex-shrink: 0;
		border-bottom: 1px solid var(--border);
		background: var(--surface);
	}

	.library-row-scrim::after {
		content: '';
		position: absolute;
		top: 0;
		right: 0;
		bottom: 0;
		width: 40px;
		background: linear-gradient(to right, transparent, var(--surface));
		pointer-events: none;
	}

	.library-row {
		display: flex;
		gap: 0.5rem;
		padding: 0.6rem 0.9rem;
		overflow-x: auto;
		cursor: grab;
		user-select: none;
		-webkit-user-select: none;
		touch-action: pan-x;
	}

	.library-row:global(.is-dragging) {
		cursor: grabbing;
	}

	.row-tile {
		display: flex;
		flex-direction: column;
		flex-shrink: 0;
		width: 84px;
		padding: 0;
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: inherit;
		font-family: inherit;
		text-align: left;
		overflow: hidden;
		opacity: 0.55;
		transform: scale(0.94);
		cursor: pointer;
	}

	.row-tile.active {
		opacity: 1;
		transform: scale(1);
		box-shadow: 0 0 0 2px var(--accent);
	}

	.row-tile:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}

	.row-tile-cover {
		display: block;
		width: 100%;
		aspect-ratio: 1;
		background: var(--surface-hover);
	}

	.row-tile-cover img,
	.row-tile-cover-fill {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.row-tile-cover-initials {
		font-family: var(--font-display);
		font-size: 0.82rem;
		letter-spacing: 0.06em;
		color: var(--text);
		user-select: none;
	}

	.row-tile-meta {
		display: flex;
		flex-direction: column;
		min-width: 0;
		gap: 1px;
		padding: 0.25rem 0.3rem;
	}

	.row-tile-title {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-family: var(--font-display);
		font-size: 0.6rem;
		letter-spacing: 0.2px;
		color: var(--text);
	}

	.row-tile-subtitle {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 0.55rem;
		color: var(--text-subtle);
	}
</style>
