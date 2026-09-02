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
	import { albumSummaryLabel, playlistSummaryLabel } from '$lib/utils/format';
	import { ALBUM_COVER_ALT_TYPE, LIBRARY_FILTER_LABELS } from '$lib/constants';
	import LibraryTileContent from './LibraryTileContent.svelte';

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

	// Position, not the list contents, is what centring cares about: a
	// metadata edit to some other tile (a title rename, a cover landing via
	// SSE) produces a new tiles array without moving the open one, and must
	// not drag the row back to it while the user has scrolled elsewhere.
	// Tracking this index (a plain number) rather than the tiles array
	// itself is what lets Svelte's own dependency tracking skip the
	// scrollIntoView effect below on every such unrelated change.
	const activeIndex = $derived(tiles.findIndex((tile) => tile.id === collection.id));

	function openTile(item: HTMLElement): void {
		const id = item.dataset.tileId;
		if (!id) return;
		if (collection.kind === 'album') void openAlbum(id);
		else void openPlaylist(id);
	}

	function prefersReducedMotion(): boolean {
		return (
			typeof window !== 'undefined' &&
			typeof window.matchMedia === 'function' &&
			window.matchMedia('(prefers-reduced-motion: reduce)').matches
		);
	}

	let rowEl = $state<HTMLElement | null>(null);

	// A click on a still-visible neighbour already leaves it in view, but a
	// mount on a deep link, a keyboard jump, or switching collection kind
	// (album <-> playlist, which swaps the whole tile set) can land on a tile
	// that isn't. kineticScroll's own snap only runs after a drag/wheel
	// gesture settles, so centring "whichever one is open" is this
	// component's own job, on every mount and every change of what's open.
	$effect(() => {
		const row = rowEl;
		const openId = collection.id;
		const index = activeIndex;
		if (!row || index === -1) return;
		const active = row.querySelector<HTMLElement>('.row-tile.active');
		if (!active || typeof active.scrollIntoView !== 'function') return;
		active.scrollIntoView({
			inline: 'center',
			block: 'nearest',
			behavior: prefersReducedMotion() ? 'auto' : 'smooth'
		});
		void openId;
	});

	const OVERFLOW_TOLERANCE_PX = 1;

	function hasOverflowToTheRight(row: HTMLElement): boolean {
		return row.scrollWidth - row.clientWidth - row.scrollLeft > OVERFLOW_TOLERANCE_PX;
	}

	// The right-edge fade is a claim that there is more to scroll to -- true
	// only while the row actually overflows. A short list (or one that has
	// been scrolled all the way to its end) must not keep showing it just
	// because the CSS is unconditional. Three things can change the answer:
	// scrolling, the box resizing, and the tile list itself changing length.
	let hasMoreToTheRight = $state(false);

	$effect(() => {
		const row = rowEl;
		if (!row) {
			hasMoreToTheRight = false;
			return;
		}
		void tiles.length;
		const measure = () => {
			hasMoreToTheRight = hasOverflowToTheRight(row);
		};
		measure();
		const observer = new ResizeObserver(measure);
		observer.observe(row);
		row.addEventListener('scroll', measure, { passive: true });
		return () => {
			observer.disconnect();
			row.removeEventListener('scroll', measure);
		};
	});
</script>

<div class="library-row-scrim" class:has-overflow={hasMoreToTheRight}>
	<div
		class="library-row"
		aria-label={rowLabel}
		bind:this={rowEl}
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
				<LibraryTileContent
					title={tile.title}
					subtitle={tile.subtitle}
					coverAlt={`${ALBUM_COVER_ALT_TYPE} ${tile.title}`}
					coverUrl={tile.coverUrl}
					fill={tile.fill}
				/>
			</button>
		{/each}
	</div>
</div>

<style>
	.library-row-scrim {
		--row-tile-width: 84px;

		position: relative;
		flex-shrink: 0;
		border-bottom: 1px solid var(--border);
		background: var(--surface-hover);
	}

	.library-row-scrim::after {
		content: '';
		position: absolute;
		top: 0;
		right: 0;
		bottom: 0;
		width: 40px;
		background: linear-gradient(to right, transparent, var(--surface-hover));
		pointer-events: none;
		opacity: 0;
	}

	.library-row-scrim.has-overflow::after {
		opacity: 1;
	}

	.library-row {
		display: flex;
		gap: 0.5rem;
		padding-block: 0.6rem;
		/* Symmetric end insets, roughly half the row's own width minus half a
		   tile, so the first and last tile can each reach the container's
		   centre too -- without them, scrollIntoView({inline:'center'}) clamps
		   an edge tile's scroll position and it can never actually centre. */
		padding-inline: max(0.9rem, calc(50% - (var(--row-tile-width) / 2)));
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
		--tile-initials-size: 0.82rem;
		--tile-meta-padding: 0.25rem 0.3rem;
		--tile-title-size: 0.6rem;
		--tile-subtitle-size: 0.55rem;

		display: flex;
		flex-direction: column;
		flex-shrink: 0;
		width: var(--row-tile-width);
		padding: 0;
		background: var(--surface);
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
		box-shadow: 0 0 0 2px var(--primary);
	}

	.row-tile:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
</style>
