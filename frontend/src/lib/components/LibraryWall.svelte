<script lang="ts">
	import { onMount } from 'svelte';
	import { get } from 'svelte/store';
	import type { AlbumItem, PlaylistItem, SongItem } from '#lib/api/types.ts';
	import {
		albumList,
		allAlbumsLoad,
		ensureAllAlbumsLoaded,
		songList,
		albumSongsLoad
	} from '#lib/stores/libraryData.ts';
	import { collectionTransport, toggleOrStartCollection, playAlbum } from '#lib/stores/player.ts';
	import { albumRowOffersPlay } from '#lib/utils/playable.ts';
	import { openAlbum, openPlaylist } from '#lib/stores/navigation.ts';
	import {
		ensurePlaylistsLoaded,
		playlistList,
		playlistLoad,
		loadPlaylists
	} from '#lib/stores/playlists.ts';
	import { openCollection, type OpenCollection } from '#lib/stores/collection.ts';
	import {
		captureLibraryScroll,
		libraryScrollAnchor,
		libraryScrollRestore,
		takePlaceReturnedFrom
	} from '#lib/stores/libraryContext.ts';
	import { whenBackOnline } from '#lib/stores/connectivity.ts';
	import { libraryBrowse, loadLibraryBrowse } from '#lib/stores/librarySearch.ts';
	import {
		chooseLibraryWallOrder,
		initLibraryWallOrder,
		libraryWallOrder
	} from '#lib/stores/ui.ts';
	import {
		ensureLastPlayedRead,
		inLibraryOrder,
		lastPlayedByPlace,
		lastPlayedOf,
		libraryPlaceOrder,
		readLastPlayed
	} from '#lib/stores/libraryOrder.ts';
	import { usableAlbumPrimary } from '#lib/utils/contrast.ts';
	import { activityTimeLabel, songCountLabel } from '#lib/utils/format.ts';
	import {
		ALBUM_COVER_ALT_TYPE,
		LIBRARY_NARROW_MEDIA,
		LIBRARY_ALBUM_CARD_TRACK_MAX_PX,
		LIBRARY_PLAYLISTS_ERROR,
		LIBRARY_PLAYLISTS_LOADING,
		LIBRARY_PAGE_LABEL,
		LIBRARY_WALL_EMPTY,
		LIBRARY_WALL_ORDER_GROUP_LABEL,
		LIBRARY_WALL_ORDER_LABELS,
		LIBRARY_WALL_ORDERS,
		PLAYLISTS_PAGE_LABEL,
		PLAYLISTS_WALL_EMPTY,
		PLAYLISTS_WALL_ORDER_GROUP_LABEL,
		wallHeadingLabel,
		type LibraryWallOrder
	} from '#lib/constants.ts';
	import LibraryRow from './LibraryRow.svelte';
	import LibraryTileContent from './LibraryTileContent.svelte';
	import NewPlaceMenu from './NewPlaceMenu.svelte';

	const SCROLL_RESTORE_TOLERANCE_PX = 1;
	const SCROLL_KEYS: ReadonlySet<string> = new Set([
		'ArrowUp',
		'ArrowDown',
		'PageUp',
		'PageDown',
		'Home',
		'End',
		' '
	]);

	// The Library wall of albums alone, or the Playlists page's wall of
	// playlists alone (#1354 rule 7; frames D1 and D3).
	type WallKind = 'library' | 'playlists';
	type WallCopy = {
		pageLabel: string;
		orderGroup: string;
		loading: string;
		failed: string;
		empty: string;
	};

	const WALL_COPY: Record<WallKind, WallCopy> = {
		library: {
			pageLabel: LIBRARY_PAGE_LABEL,
			orderGroup: LIBRARY_WALL_ORDER_GROUP_LABEL,
			loading: 'Loading library…',
			failed: 'Could not load library.',
			empty: LIBRARY_WALL_EMPTY
		},
		playlists: {
			pageLabel: PLAYLISTS_PAGE_LABEL,
			orderGroup: PLAYLISTS_WALL_ORDER_GROUP_LABEL,
			loading: LIBRARY_PLAYLISTS_LOADING,
			failed: LIBRARY_PLAYLISTS_ERROR,
			empty: PLAYLISTS_WALL_EMPTY
		}
	};

	let { kind }: { kind: WallKind } = $props();

	const copy = $derived(WALL_COPY[kind]);
	const albums = $derived($albumList);
	const playlists = $derived($playlistList);
	const currentCollection = $derived($openCollection);
	const order = $derived($libraryWallOrder);
	const browseState = $derived($libraryBrowse);
	const playlistStatus = $derived($playlistLoad);
	const pendingRestore = $derived($libraryScrollRestore);

	let labelledAt = $state(new Date());

	// The light is one event of this showing of the wall: the row that lights
	// spends it, so a remount of that row (the width crossing the phone
	// boundary, the list refilling) does not light it again.
	let placeToLight = $state.raw<OpenCollection | null>(takePlaceReturnedFrom());
	function spendLight(): void {
		placeToLight = null;
	}

	let narrow = $state(false);
	$effect(() => {
		if (typeof window.matchMedia !== 'function') return;
		const media = window.matchMedia(LIBRARY_NARROW_MEDIA);
		const sync = () => {
			narrow = media.matches;
		};
		sync();
		media.addEventListener('change', sync);
		return () => media.removeEventListener('change', sync);
	});
	const songsByAlbum = $derived.by(() => {
		// eslint-disable-next-line svelte/prefer-svelte-reactivity -- This local map is rebuilt by $derived whenever songList changes.
		const grouped = new Map<string, SongItem[]>();
		for (const song of $songList) {
			const songs = grouped.get(song.album_id);
			if (songs) songs.push(song);
			else grouped.set(song.album_id, [song]);
		}
		return grouped;
	});
	const wallItems = $derived(
		kind === 'library'
			? inLibraryOrder('album', albums, $libraryPlaceOrder)
			: inLibraryOrder('playlist', playlists, $libraryPlaceOrder)
	);
	const placeType = $derived(kind === 'library' ? 'album' : 'playlist');
	const loadStatuses = $derived(
		kind === 'library' ? [browseState.status] : [playlistStatus.status]
	);
	// The head states how many there are, which only the loaded list knows:
	// until it has loaded, the library holds none yet after a reload, or only
	// the album or playlist an address opened.
	const kindLoaded = $derived(
		kind === 'library' ? $allAlbumsLoad.status === 'ready' : playlistStatus.status === 'ready'
	);
	// A list held back until its order is known is not an empty one.
	const orderKnown = $derived($libraryPlaceOrder.known);
	const headCount = $derived(kindLoaded && orderKnown ? wallItems.length : undefined);

	let browseEl = $state<HTMLElement | null>(null);

	onMount(() => {
		// A wall mounted without a landing starts where the anchor says, so the two agree.
		if (!get(libraryScrollRestore)) libraryScrollRestore.set({ top: get(libraryScrollAnchor) });
		initLibraryWallOrder();
		catchUpWall(ensureLastPlayedRead);
		const stopReconnectCatchUp = whenBackOnline(() => catchUpWall(readLastPlayed));
		// A request cleared while this wall stays mounted leaves the anchor at its
		// target; the wall then reports where it really is.
		let waiting = get(libraryScrollRestore) !== null;
		const stopWatchingRestore = libraryScrollRestore.subscribe((request) => {
			if (waiting && request === null && browseEl) captureLibraryScroll(browseEl.scrollTop);
			waiting = request !== null;
		});
		return () => {
			stopReconnectCatchUp();
			stopWatchingRestore();
		};
	});

	$effect(() => {
		void $lastPlayedByPlace;
		labelledAt = new Date();
	});

	// Only a pending restore writes scrollTop: once the content is tall enough to
	// hold it, or, for a target it can never hold, once the list has loaded, when
	// the clamped position goes back to the anchor.
	$effect(() => {
		void wallItems.length;
		if (!browseEl || !pendingRestore) return;
		const reachable = browseEl.scrollHeight - browseEl.clientHeight;
		const holdsTarget = reachable + SCROLL_RESTORE_TOLERANCE_PX >= pendingRestore.top;
		if (!holdsTarget && !(kindLoaded && orderKnown)) return;
		const landedAt = holdsTarget ? pendingRestore.top : Math.max(0, reachable);
		browseEl.scrollTop = landedAt;
		if (!holdsTarget) captureLibraryScroll(landedAt);
		libraryScrollRestore.set(null);
	});

	function sizeLabel(item: AlbumItem | PlaylistItem): string {
		return songCountLabel('song_count' in item ? item.song_count : item.entry_count);
	}

	function tileDetail(item: AlbumItem | PlaylistItem): string {
		const lastPlayed =
			order === 'played' ? lastPlayedOf($lastPlayedByPlace, { type: placeType, item }) : undefined;
		return lastPlayed ? activityTimeLabel(lastPlayed.at, labelledAt) : sizeLabel(item);
	}

	function rowPlay(item: AlbumItem | PlaylistItem): (() => void) | undefined {
		if (
			!('song_count' in item) ||
			!albumRowOffersPlay(item, songsByAlbum.get(item.id) ?? [], $albumSongsLoad)
		)
			return undefined;
		return () => toggleOrStartCollection('album', item.id, () => void playAlbum(item.id));
	}

	// A failed read keeps what is on screen, and only an empty wall names it
	// (#1039 O4): the offline strip owns a lost network, and the wall reads
	// again when the page returns to the foreground or the network comes back.
	// Showing the wall again asks only for a ranking that a recorded listen has not
	// outdated, so a page load stays at the one read the rail may have made.
	function catchUpWall(readRanking: () => Promise<boolean>): void {
		if (kind === 'library') void ensureAllAlbumsLoaded();
		else void ensurePlaylistsLoaded();
		if ($libraryWallOrder === 'played') void readRanking();
	}

	function chooseOrder(next: LibraryWallOrder): void {
		chooseLibraryWallOrder(next);
		labelledAt = new Date();
		if (next === 'played') void readLastPlayed();
	}

	function catchUpOnReturnToForeground(): void {
		if (document.visibilityState === 'visible') catchUpWall(readLastPlayed);
	}

	// Only the person's own input drops a pending restore; a clamp, momentum or
	// the wall's own write are scroll events without it.
	function dropRestoreForInput(): void {
		if (!pendingRestore || !browseEl) return;
		libraryScrollRestore.set(null);
		captureLibraryScroll(browseEl.scrollTop);
	}

	$effect(() => {
		const body = browseEl;
		if (!body) return;
		const onKeydown = (event: KeyboardEvent) => {
			if (SCROLL_KEYS.has(event.key)) dropRestoreForInput();
		};
		const options = { passive: true };
		body.addEventListener('pointerdown', dropRestoreForInput, options);
		body.addEventListener('touchstart', dropRestoreForInput, options);
		body.addEventListener('wheel', dropRestoreForInput, options);
		body.addEventListener('keydown', onKeydown);
		return () => {
			body.removeEventListener('pointerdown', dropRestoreForInput);
			body.removeEventListener('touchstart', dropRestoreForInput);
			body.removeEventListener('wheel', dropRestoreForInput);
			body.removeEventListener('keydown', onKeydown);
		};
	});

	function onBrowseScroll(event: Event): void {
		const target = event.currentTarget;
		if (!(target instanceof HTMLElement)) return;
		if (pendingRestore) return;
		captureLibraryScroll(target.scrollTop);
	}

	function retryLoad(): void {
		if (kind === 'library') void loadLibraryBrowse({ reset: true });
		else void loadPlaylists();
	}
</script>

<svelte:document onvisibilitychange={catchUpOnReturnToForeground} />

{#snippet orderSwitch()}
	<div class="wall-order" role="group" aria-label={copy.orderGroup}>
		{#each LIBRARY_WALL_ORDERS as choice (choice)}
			<button
				type="button"
				class="wall-order-choice"
				aria-pressed={order === choice}
				onclick={() => chooseOrder(choice)}
			>
				<span class="wall-order-face">{LIBRARY_WALL_ORDER_LABELS[choice]}</span>
			</button>
		{/each}
	</div>
{/snippet}

<div class="library-wall">
	<div class="wall-titlebar">
		<h1
			class="wall-title"
			aria-label={headCount === undefined
				? copy.pageLabel
				: wallHeadingLabel(copy.pageLabel, headCount)}
		>
			{copy.pageLabel}
			{#if headCount !== undefined}<span class="wall-count">{headCount}</span>{/if}
		</h1>
		{@render orderSwitch()}
		{#if !narrow}<NewPlaceMenu />{/if}
	</div>

	<div class="wall-body" bind:this={browseEl} onscroll={onBrowseScroll}>
		{#if wallItems.length > 0}
			<div class="tile-grid" style:--album-card-track={`${LIBRARY_ALBUM_CARD_TRACK_MAX_PX}px`}>
				{#each wallItems as item (placeType + item.id)}
					{@const transport = $collectionTransport(placeType, item.id)}
					{@const content = {
						title: item.title,
						coverAlt: `${placeType === 'album' ? ALBUM_COVER_ALT_TYPE : 'Playlist cover for'} ${item.title}`,
						coverUrl: item.cover?.card ?? null,
						fill: 'colors' in item ? usableAlbumPrimary(item.colors) : null,
						playlistCovers: 'album_covers' in item ? item.album_covers : null
					}}
					{@const onopen = () => (kind === 'library' ? openAlbum(item.id) : openPlaylist(item.id))}
					{@const selected =
						currentCollection?.kind === placeType && currentCollection.id === item.id}
					{#if narrow}
						<LibraryRow
							{...content}
							{selected}
							subtitle={sizeLabel(item)}
							lightUp={placeToLight?.kind === placeType && placeToLight.id === item.id}
							onlit={spendLight}
							openLabel={`Open ${placeType} ${item.title}`}
							{onopen}
							onplay={rowPlay(item)}
							current={placeType === 'album' && transport.current}
							transport={transport.transport}
						/>
					{:else}
						<div class="wall-tile" class:selected>
							<button
								type="button"
								class="wall-tile-body"
								onclick={onopen}
								aria-label={`Open ${placeType} ${item.title}`}
							>
								<LibraryTileContent {...content} subtitle={tileDetail(item)} />
							</button>
						</div>
					{/if}
				{/each}
			</div>
		{:else if !orderKnown || loadStatuses.includes('loading')}
			<p class="empty" role="status">{copy.loading}</p>
		{:else if loadStatuses.includes('error')}
			<p class="empty" role="alert">{copy.failed}</p>
			<button class="retry-btn" onclick={retryLoad}>Retry</button>
		{:else}
			<p class="empty">{copy.empty}</p>
		{/if}
	</div>
</div>

<style>
	.library-wall {
		display: flex;
		flex: 1;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
	}

	.wall-titlebar {
		display: flex;
		flex-shrink: 0;
		align-items: center;
		flex-wrap: wrap;
		justify-content: space-between;
		gap: 8px;
		padding: 16px 20px 12px;
		border-bottom: 1px solid var(--border);
	}

	.wall-title {
		color: var(--text);
		font-family: var(--font-display);
		font-size: 1.4rem;
		letter-spacing: 1px;
		text-transform: uppercase;
	}

	.wall-titlebar .wall-order {
		margin-left: auto;
	}

	.wall-count {
		margin-left: 0.3rem;
		color: var(--text-subtle);
		font-weight: 400;
		letter-spacing: 0.04em;
	}

	.wall-order {
		display: inline-flex;
	}

	.wall-order-choice {
		display: inline-flex;
		align-items: center;
		height: var(--hitbox-frequent);
		padding: 0;
		border: 0;
		background: none;
		cursor: pointer;
	}

	.wall-order-face {
		display: inline-flex;
		align-items: center;
		height: 30px;
		padding: 0 0.6rem;
		border: 1px solid var(--border);
		background: none;
		color: var(--text-muted);
		font-family: var(--font-display);
		font-size: 0.74rem;
		letter-spacing: 0.5px;
		text-transform: uppercase;
		white-space: nowrap;
	}

	.wall-order-choice + .wall-order-choice .wall-order-face {
		border-left: 0;
	}

	.wall-order-choice:first-child .wall-order-face {
		border-radius: var(--btn-radius-sm) 0 0 var(--btn-radius-sm);
	}

	.wall-order-choice:last-child .wall-order-face {
		border-radius: 0 var(--btn-radius-sm) var(--btn-radius-sm) 0;
	}

	.wall-order-choice[aria-pressed='true'] .wall-order-face {
		background: color-mix(in srgb, var(--accent) 16%, var(--surface));
		color: var(--accent);
	}

	.wall-order-choice:focus-visible {
		outline: none;
	}

	.wall-order-choice:focus-visible .wall-order-face {
		outline: 2px solid var(--accent);
		outline-offset: -2px;
	}

	.wall-body {
		flex: 1;
		min-width: 0;
		min-height: 0;
		overflow-x: hidden;
		overflow-y: auto;
		padding: 8px 20px 20px;
	}

	.tile-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(0, var(--album-card-track)));
		gap: 12px;
		min-width: 0;
	}

	.wall-tile {
		min-width: 0;
		overflow: hidden;
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface);
	}

	.wall-tile.selected {
		box-shadow: var(--selected-ring);
	}

	.wall-tile-body {
		display: flex;
		flex-direction: column;
		width: 100%;
		min-width: 0;
		border: 0;
		background: transparent;
		color: var(--text);
		font-family: var(--font-body);
		cursor: pointer;
		text-align: left;
	}

	.wall-tile-body:hover,
	.wall-tile-body:focus-visible {
		background: var(--surface-hover);
		outline: none;
	}

	.empty {
		padding: 20px;
		color: var(--text-subtle);
		font-size: var(--label-font-size);
		text-align: center;
	}

	.retry-btn {
		display: block;
		margin: 0 auto 16px;
		padding: 6px 12px;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: none;
		color: var(--text-muted);
		font-family: var(--font-body);
		font-size: var(--label-font-size);
		cursor: pointer;
	}

	.retry-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	@media (max-width: 768px) {
		.wall-titlebar {
			padding: 10px 12px 6px;
		}

		.wall-body {
			padding-inline: 12px;
		}

		.tile-grid {
			grid-template-columns: minmax(0, 1fr);
			gap: 0;
		}
	}
</style>
