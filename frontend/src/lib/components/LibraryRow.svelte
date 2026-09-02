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
	import {
		ALBUM_COVER_ALT_TYPE,
		LIBRARY_FILTER_LABELS,
		LIBRARY_ROW_FILTER_EMPTY
	} from '$lib/constants';
	import LibraryTileContent from './LibraryTileContent.svelte';
	import LibraryRowFilter from './LibraryRowFilter.svelte';

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

	// The row's own instant filter (#402) -- local component state only, not
	// a store and not a URL param, so it never outlives this row and never
	// touches the wall's grid search (LibraryWall.svelte's searchQuery),
	// which is a different job: server-side, across the whole library.
	let filterQuery = $state('');
	const normalizedFilter = $derived(filterQuery.trim().toLowerCase());

	function tileMatchesFilter(tile: RowTile): boolean {
		return (
			tile.title.toLowerCase().includes(normalizedFilter) ||
			tile.subtitle.toLowerCase().includes(normalizedFilter)
		);
	}

	// null means "no filter active" -- every tile renders. Once a query is
	// typed, only its own matches render, except the open tile: it stays
	// visible and marked no matter what (#348 ruling 6 / #402), so it alone
	// is exempted from tileHidden below rather than folded into this set.
	const matchingTileIds = $derived.by((): Set<string> | null => {
		if (!normalizedFilter) return null;
		return new Set(tiles.filter(tileMatchesFilter).map((tile) => tile.id));
	});

	function tileHidden(tile: RowTile): boolean {
		if (matchingTileIds === null || matchingTileIds.has(tile.id)) return false;
		return tile.id !== collection.id;
	}

	function tileFilteredOutButOpen(tile: RowTile): boolean {
		return matchingTileIds !== null && !matchingTileIds.has(tile.id) && tile.id === collection.id;
	}

	const hasNoMatches = $derived(matchingTileIds !== null && matchingTileIds.size === 0);

	// The row's actual on-screen layout in one comparable value: the ordered
	// ids of the tiles that are not hidden. Centring and the overflow
	// measurement below only need to redo their work when this changes --
	// not on every keystroke (most keystrokes narrow the match set further
	// without changing which tiles are currently shown) and not when a
	// sibling's title or subtitle changes without moving in or out of view.
	const visibleTileKey = $derived(
		tiles
			.filter((tile) => !tileHidden(tile))
			.map((tile) => tile.id)
			.join('\u0000')
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
	// component's own job, on every mount and every change of what's open --
	// and whenever a filter keystroke actually hides or reveals a neighbour
	// (visibleTileKey), since that reflows the row and can shift the open
	// tile off-centre even though it never moved in the underlying list. A
	// keystroke that only narrows the match set further without changing
	// what's currently shown -- or a sibling's title/subtitle changing while
	// its visibility doesn't -- must not recentre.
	$effect(() => {
		const row = rowEl;
		const openId = collection.id;
		const index = activeIndex;
		const visibleKey = visibleTileKey;
		if (!row || index === -1) return;
		const active = row.querySelector<HTMLElement>('.row-tile.active');
		if (!active || typeof active.scrollIntoView !== 'function') return;
		active.scrollIntoView({
			inline: 'center',
			block: 'nearest',
			behavior: prefersReducedMotion() ? 'auto' : 'smooth'
		});
		void openId;
		void visibleKey;
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
		void visibleTileKey;
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
	<LibraryRowFilter bind:value={filterQuery} collectionLabel={rowLabel} />
	{#if hasNoMatches}
		<p class="library-row-filter-empty">{LIBRARY_ROW_FILTER_EMPTY}</p>
	{/if}
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
				class:filtered-out-but-open={tileFilteredOutButOpen(tile)}
				data-tile-id={tile.id}
				aria-current={tile.id === collection.id}
				title={tile.title}
				hidden={tileHidden(tile)}
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

	.row-tile.filtered-out-but-open {
		opacity: 0.4;
		outline: 1px dashed var(--border);
		outline-offset: -1px;
	}

	.row-tile:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}

	.library-row-filter-empty {
		margin: 0;
		padding: 0.3rem 0.9rem 0;
		font-size: 0.72rem;
		color: var(--text-subtle);
	}
</style>
