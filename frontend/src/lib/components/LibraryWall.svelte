<script lang="ts">
	interface Props {
		oncreate?: () => void;
	}

	let { oncreate }: Props = $props();

	import {
		addAlbumToList,
		albumList,
		songList,
		updateAlbumInList,
		updateGenerationInList,
		updateSongInList
	} from '$lib/stores/libraryData';
	import { playAlbum, playPlaylistFrom } from '$lib/stores/player';
	import {
		openAlbum,
		openPlaylist,
		persistLibraryHistory,
		revealSharedTake,
		selectLibraryFilter,
		selectSong
	} from '$lib/stores/navigation';
	import {
		loadMoreShares,
		loadShareInventory,
		refreshSharesAfterMutation,
		setShareTypeFilter,
		shareCount,
		shareInventory,
		sharesViewOpen,
		watchShareStatus,
		watchShareView
	} from '$lib/stores/shares';
	import { fetchAlbum, fetchAlbums } from '$lib/api/albums';
	import {
		fetchPlaylist,
		unarchiveAlbum,
		unshareAlbum,
		unshareGeneration,
		unsharePlaylist,
		unshareSong
	} from '$lib/api/client';
	import type {
		AlbumItem,
		PlaylistItem,
		ShareInventoryItem,
		SongItem,
		SongSummaryResponse
	} from '$lib/api/types';
	import {
		createNewPlaylist,
		playlistList,
		playlistLoad,
		loadPlaylists,
		updatePlaylistInList
	} from '$lib/stores/playlists';
	import { openCollection } from '$lib/stores/collection';
	import {
		captureLibraryScroll,
		libraryFilter,
		libraryScrollAnchor
	} from '$lib/stores/libraryContext';
	import {
		changeLibrarySort,
		libraryBrowse,
		librarySort,
		loadLibraryBrowse
	} from '$lib/stores/librarySearch';
	import { addToast } from '$lib/stores/toast';
	import Icon from './Icon.svelte';
	import LibraryTileContent from './LibraryTileContent.svelte';

	import { CREATED_SORT_LABELS, CREATED_SORTS, compareByCreatedAt } from '$lib/utils/recency';
	import { usableAlbumPrimary } from '$lib/utils/contrast';
	import { albumSummaryLabel, playlistSummaryLabel } from '$lib/utils/format';
	import {
		ALBUM_COVER_ALT_TYPE,
		LIBRARY_ALBUM_CARD_TRACK_MAX_PX,
		LIBRARY_ALBUM_PAGE_SIZE,
		LIBRARY_ALBUMS_EMPTY,
		LIBRARY_ALBUMS_LOADING,
		LIBRARY_ARCHIVED_EMPTY,
		LIBRARY_ARCHIVED_ERROR,
		LIBRARY_ARCHIVED_LOADING,
		LIBRARY_ARCHIVED_TOGGLE_LABEL,
		LIBRARY_ARCHIVED_UNARCHIVE_LABEL,
		LIBRARY_FILTERS,
		LIBRARY_FILTER_LABELS,
		LIBRARY_FILTER_NAV_LABEL,
		LIBRARY_LOAD_MORE,
		LIBRARY_NEW_ALBUM_LABEL,
		LIBRARY_NEW_PLAYLIST_LABEL,
		LIBRARY_PLAYLISTS_EMPTY,
		LIBRARY_PLAYLISTS_ERROR,
		LIBRARY_PLAYLISTS_LOADING,
		LIBRARY_RETRY_LABEL,
		LIBRARY_SEARCH_ERROR,
		LIBRARY_SHARES_ALL_LABEL,
		LIBRARY_SHARES_FILTER_LABEL,
		LIBRARY_SHARES_COPY_LABEL,
		LIBRARY_SHARES_ERROR,
		LIBRARY_SHARES_OPEN_LABEL,
		LIBRARY_SHARES_TYPE_EMPTY,
		LIBRARY_SHARES_TYPE_LABELS,
		LIBRARY_SHARES_TYPES,
		LIBRARY_SHARES_UNSHARE_LABEL,
		LIBRARY_SHARES_UNSHARE_TITLE,
		LIBRARY_SHARES_UNSHARE_WARNING,
		LIBRARY_SHARED_EMPTY,
		LIBRARY_SHARED_LOADING,
		NOW_PLAYING_TAKE_PREFIX,
		collectionRowPlayLabel,
		librarySharesStatusLabel,
		type LibraryFilter
	} from '$lib/constants';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';

	const albums = $derived($albumList);
	const songs = $derived($songList);
	const playlists = $derived($playlistList);
	const currentCollection = $derived($openCollection);
	const createdSort = $derived($librarySort);
	const browseState = $derived($libraryBrowse);
	const filter = $derived($libraryFilter);
	const playlistStatus = $derived($playlistLoad);
	const restoredScroll = $derived($libraryScrollAnchor);
	const sharesState = $derived($shareInventory);
	const sharesCount = $derived($shareCount);
	let pendingUnshare = $state<ShareInventoryItem | null>(null);

	type ArchivedLoadStatus = 'idle' | 'loading' | 'error' | 'ready';
	let archivedOpen = $state(false);
	let archivedAlbums = $state<AlbumItem[]>([]);
	let archivedStatus = $state<ArchivedLoadStatus>('idle');
	let archivedError = $state<string | null>(null);
	let archivedOffset = $state(0);
	let archivedHasMore = $state(false);

	$effect(() => {
		return watchShareStatus();
	});

	$effect(() => {
		if (!$sharesViewOpen) return;
		return watchShareView();
	});

	interface AlbumGroup {
		album: AlbumItem;
		songs: Array<SongItem | SongSummaryResponse>;
	}

	const albumGroups = $derived.by(() => {
		const orderedAlbums = [...albums].sort((a, b) => compareByCreatedAt(a, b, createdSort));
		const groups: AlbumGroup[] = [];
		for (const album of orderedAlbums) {
			const albumSongs = songs
				.filter((s) => s.album_id === album.id)
				.sort((a, b) => compareByCreatedAt(a, b, createdSort));
			groups.push({ album, songs: albumSongs });
		}
		return groups;
	});

	const orderedPlaylists = $derived(
		[...playlists].sort((a, b) => compareByCreatedAt(a, b, createdSort))
	);

	let browseEl = $state<HTMLElement | null>(null);

	$effect(() => {
		void albumGroups.length;
		void orderedPlaylists.length;
		void sharesState.items.length;
		if (browseEl) {
			browseEl.scrollTop = restoredScroll;
		}
	});

	function onBrowseScroll(event: Event): void {
		const target = event.currentTarget;
		if (!(target instanceof HTMLElement)) return;
		captureLibraryScroll(target.scrollTop);
	}

	async function hydrateAndOpenAlbum(album: AlbumItem): Promise<void> {
		albumList.update((list) =>
			list.some((item) => item.id === album.id) ? list : [...list, album]
		);
		await openAlbum(album.id);
	}

	function onPlayAlbum(albumId: string): void {
		void playAlbum(albumId);
	}

	async function onPlayPlaylist(playlist: PlaylistItem): Promise<void> {
		try {
			const detail = await fetchPlaylist(playlist.id);
			playPlaylistFrom(detail, 0);
		} catch {
			addToast('Play failed', 'error');
		}
	}

	function onSelectFilter(next: LibraryFilter): void {
		selectLibraryFilter(next);
	}

	async function loadArchivedAlbums(options?: { reset?: boolean }): Promise<void> {
		const reset = options?.reset ?? true;
		const offset = reset ? 0 : archivedOffset;
		archivedStatus = 'loading';
		archivedError = null;
		try {
			const page = await fetchAlbums(offset, LIBRARY_ALBUM_PAGE_SIZE, { archived: true });
			archivedAlbums = reset ? page.items : [...archivedAlbums, ...page.items];
			archivedOffset = offset + page.items.length;
			archivedHasMore = page.has_more;
			archivedStatus = 'ready';
		} catch (e) {
			archivedStatus = 'error';
			archivedError = e instanceof Error ? e.message : LIBRARY_ARCHIVED_ERROR;
		}
	}

	function toggleArchived(): void {
		archivedOpen = !archivedOpen;
		if (archivedOpen && archivedStatus === 'idle') {
			void loadArchivedAlbums({ reset: true });
		}
	}

	async function onUnarchiveAlbum(album: AlbumItem): Promise<void> {
		try {
			const restored = await unarchiveAlbum(album.id);
			archivedAlbums = archivedAlbums.filter((a) => a.id !== album.id);
			addAlbumToList(restored);
			addToast('Album unarchived', 'success');
		} catch {
			addToast('Unarchive failed', 'error');
		}
	}

	function onFilterKeydown(event: KeyboardEvent, current: LibraryFilter): void {
		const index = LIBRARY_FILTERS.indexOf(current);
		let next: LibraryFilter | null = null;
		if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
			event.preventDefault();
			next = LIBRARY_FILTERS[(index + 1) % LIBRARY_FILTERS.length];
		} else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
			event.preventDefault();
			next = LIBRARY_FILTERS[(index - 1 + LIBRARY_FILTERS.length) % LIBRARY_FILTERS.length];
		}
		if (!next) return;
		onSelectFilter(next);
		const chip = document.getElementById(`library-filter-${next}`);
		if (chip instanceof HTMLButtonElement) chip.focus();
	}

	function onSortChange(event: Event): void {
		const option = (event.target as HTMLSelectElement).value as (typeof CREATED_SORTS)[number];
		changeLibrarySort(option, '');
		persistLibraryHistory();
	}

	async function onCreatePlaylist(): Promise<void> {
		try {
			const playlist = await createNewPlaylist('Playlist');
			selectLibraryFilter('playlists');
			await openPlaylist(playlist.id);
		} catch {
			addToast('Create failed', 'error');
		}
	}

	function shareRowLabel(item: ShareInventoryItem): string {
		if (item.type === 'generation') {
			const number = item.generation_number ?? 0;
			return `${NOW_PLAYING_TAKE_PREFIX} #${number} — ${item.title}`;
		}
		return item.title;
	}

	async function onOpenShare(item: ShareInventoryItem): Promise<void> {
		if (item.type === 'album') {
			try {
				await hydrateAndOpenAlbum(await fetchAlbum(item.id));
			} catch {
				addToast('Open failed', 'error');
			}
		} else if (item.type === 'song') selectSong(item.id);
		else if (item.type === 'playlist') openPlaylist(item.id);
		else if (item.song_id) {
			// A dirty draft must park the song switch and the take pin together
			// (issue #265 review of #264) -- selectSong's own promise resolves the
			// instant a dirty draft parks it, so setting selectedGenerationId
			// right after this await used to run against whichever song was still
			// open while the confirm was pending.
			await revealSharedTake(item.song_id, item.id);
		}
	}

	async function onCopyShareLink(item: ShareInventoryItem): Promise<void> {
		try {
			await navigator.clipboard.writeText(`${window.location.origin}${item.public_path}`);
			addToast('Link copied', 'success');
		} catch {
			addToast('Copy failed', 'error');
		}
	}

	async function confirmUnshare(): Promise<void> {
		const item = pendingUnshare;
		if (!item) return;
		pendingUnshare = null;
		try {
			if (item.type === 'album') {
				await unshareAlbum(item.id);
				updateAlbumInList(item.id, (a) => ({ ...a, is_shared: false, share_slug: null }));
			} else if (item.type === 'song') {
				await unshareSong(item.id);
				updateSongInList(item.id, (s) => ({ ...s, is_shared: false, share_slug: null }));
			} else if (item.type === 'playlist') {
				await unsharePlaylist(item.id);
				updatePlaylistInList(item.id, (p) => ({ ...p, is_shared: false, share_slug: null }));
			} else {
				await unshareGeneration(item.id);
				updateGenerationInList(item.id, (g) => ({ ...g, is_shared: false, share_slug: null }));
			}
			await refreshSharesAfterMutation();
			addToast('Sharing disabled', 'success');
		} catch {
			addToast('Unshare failed', 'error');
		}
	}

	const sharesLabel = $derived(
		sharesCount.status === 'ready' && sharesCount.total !== null
			? librarySharesStatusLabel(sharesCount.total)
			: LIBRARY_FILTER_LABELS.shared
	);
	const panelSection = $derived(filter);
	const sharesPageComplete = $derived(sharesState.status === 'ready' && !sharesState.hasMore);
</script>

<div class="library-wall">
	<div class="wall-toolbar">
		<h1 class="wall-title">{LIBRARY_FILTER_LABELS[filter]}</h1>
		<div class="wall-controls">
			<div class="filter-chips" role="radiogroup" aria-label={LIBRARY_FILTER_NAV_LABEL}>
				{#each LIBRARY_FILTERS as item (item)}
					<button
						class="filter-chip"
						data-hitbox="frequent"
						class:active={filter === item}
						role="radio"
						id="library-filter-{item}"
						aria-checked={filter === item}
						tabindex={filter === item ? 0 : -1}
						onclick={() => onSelectFilter(item)}
						onkeydown={(event) => onFilterKeydown(event, item)}
					>
						{item === 'shared' ? sharesLabel : LIBRARY_FILTER_LABELS[item]}
					</button>
				{/each}
			</div>
			<select
				class="sort-select"
				data-hitbox="frequent"
				value={createdSort}
				onchange={onSortChange}
				aria-label="Sort"
			>
				{#each CREATED_SORTS as option (option)}
					<option value={option}>{CREATED_SORT_LABELS[option]}</option>
				{/each}
			</select>
			{#if filter === 'albums'}
				<button
					class="filter-chip"
					data-hitbox="frequent"
					class:active={archivedOpen}
					aria-pressed={archivedOpen}
					onclick={toggleArchived}
				>
					{LIBRARY_ARCHIVED_TOGGLE_LABEL}
				</button>
				<button
					class="new-btn"
					data-hitbox="frequent"
					onclick={oncreate}
					aria-label={LIBRARY_NEW_ALBUM_LABEL}
				>
					+ Album
				</button>
			{:else if filter === 'playlists'}
				<button
					class="new-btn"
					data-hitbox="frequent"
					onclick={onCreatePlaylist}
					aria-label={LIBRARY_NEW_PLAYLIST_LABEL}
				>
					+ Playlist
				</button>
			{/if}
		</div>
	</div>

	<div
		class="wall-body"
		data-library-filter={panelSection}
		bind:this={browseEl}
		onscroll={onBrowseScroll}
	>
		{#if filter === 'shared'}
			<div class="share-filters" role="radiogroup" aria-label={LIBRARY_SHARES_FILTER_LABEL}>
				<button
					class="filter-chip"
					data-hitbox="frequent"
					class:active={sharesState.typeFilter === null}
					role="radio"
					aria-checked={sharesState.typeFilter === null}
					onclick={() => setShareTypeFilter(null)}
				>
					{LIBRARY_SHARES_ALL_LABEL}
				</button>
				{#each LIBRARY_SHARES_TYPES as type (type)}
					<button
						class="filter-chip"
						data-hitbox="frequent"
						class:active={sharesState.typeFilter === type}
						role="radio"
						aria-checked={sharesState.typeFilter === type}
						onclick={() => setShareTypeFilter(type)}
					>
						{LIBRARY_SHARES_TYPE_LABELS[type]}
					</button>
				{/each}
			</div>
			{#if sharesState.status === 'loading' && sharesState.items.length === 0}
				<p class="empty" role="status">{LIBRARY_SHARED_LOADING}</p>
			{:else if sharesState.status === 'error' && sharesState.items.length === 0}
				<p class="empty" role="alert">{sharesState.error || LIBRARY_SHARES_ERROR}</p>
				<button class="retry-btn" onclick={() => loadShareInventory({ reset: true })}
					>{LIBRARY_RETRY_LABEL}</button
				>
			{:else if sharesPageComplete && sharesState.items.length === 0}
				<p class="empty">
					{sharesState.typeFilter
						? LIBRARY_SHARES_TYPE_EMPTY[sharesState.typeFilter]
						: LIBRARY_SHARED_EMPTY}
				</p>
			{:else}
				{#each sharesState.items as item (item.type + item.id)}
					<div class="share-row">
						<button
							class="share-open"
							onclick={() => onOpenShare(item)}
							aria-label={`${LIBRARY_SHARES_OPEN_LABEL} ${shareRowLabel(item)}`}
						>
							<span class="share-type">{LIBRARY_SHARES_TYPE_LABELS[item.type]}</span>
							<span class="share-title">{shareRowLabel(item)}</span>
						</button>
						<button
							class="share-action"
							onclick={() => onCopyShareLink(item)}
							aria-label={LIBRARY_SHARES_COPY_LABEL}
						>
							{LIBRARY_SHARES_COPY_LABEL}
						</button>
						<button
							class="share-action"
							onclick={() => (pendingUnshare = item)}
							aria-label={LIBRARY_SHARES_UNSHARE_LABEL}
						>
							{LIBRARY_SHARES_UNSHARE_LABEL}
						</button>
					</div>
				{/each}
			{/if}
			{#if sharesState.hasMore}
				<button
					class="load-more"
					onclick={() => loadMoreShares()}
					disabled={sharesState.status === 'loading'}
				>
					{LIBRARY_LOAD_MORE}
				</button>
			{/if}
			{#if sharesState.status === 'error' && sharesState.items.length > 0}
				<p class="empty" role="alert">{sharesState.error || LIBRARY_SHARES_ERROR}</p>
				<button class="retry-btn" onclick={() => loadShareInventory({ reset: true })}
					>{LIBRARY_RETRY_LABEL}</button
				>
			{/if}
		{:else if filter === 'albums' && archivedOpen}
			<div class="tile-grid" style:--album-card-track={`${LIBRARY_ALBUM_CARD_TRACK_MAX_PX}px`}>
				{#each archivedAlbums as archived (archived.id)}
					<div class="wall-tile">
						<div class="wall-tile-body">
							<LibraryTileContent
								title={archived.title}
								subtitle={albumSummaryLabel(archived.song_count, archived.picked_count)}
								coverAlt={`${ALBUM_COVER_ALT_TYPE} ${archived.title}`}
								coverUrl={archived.cover?.card ?? null}
							/>
						</div>
						<button
							type="button"
							class="wall-tile-unarchive"
							data-hitbox="frequent"
							onclick={() => onUnarchiveAlbum(archived)}
						>
							{LIBRARY_ARCHIVED_UNARCHIVE_LABEL}
						</button>
					</div>
				{/each}
			</div>

			{#if archivedStatus === 'loading' && archivedAlbums.length === 0}
				<p class="empty" role="status">{LIBRARY_ARCHIVED_LOADING}</p>
			{:else if archivedStatus === 'error' && archivedAlbums.length === 0}
				<p class="empty" role="alert">{archivedError || LIBRARY_ARCHIVED_ERROR}</p>
				<button class="retry-btn" onclick={() => loadArchivedAlbums({ reset: true })}
					>{LIBRARY_RETRY_LABEL}</button
				>
			{:else if archivedAlbums.length === 0}
				<p class="empty">{LIBRARY_ARCHIVED_EMPTY}</p>
			{/if}

			{#if archivedHasMore}
				<button
					class="load-more"
					onclick={() => loadArchivedAlbums({ reset: false })}
					disabled={archivedStatus === 'loading'}
				>
					{LIBRARY_LOAD_MORE}
				</button>
			{/if}
		{:else if filter === 'albums'}
			<div class="tile-grid" style:--album-card-track={`${LIBRARY_ALBUM_CARD_TRACK_MAX_PX}px`}>
				{#each albumGroups as group (group.album.id)}
					{@const fill = usableAlbumPrimary(group.album.colors)}
					{@const coverUrl = group.album.cover?.card ?? null}
					<div
						class="wall-tile"
						class:selected={currentCollection?.kind === 'album' &&
							currentCollection.id === group.album.id}
					>
						<button
							type="button"
							class="wall-tile-body"
							onclick={() => hydrateAndOpenAlbum(group.album)}
						>
							<LibraryTileContent
								title={group.album.title}
								subtitle={albumSummaryLabel(group.album.song_count, group.album.picked_count)}
								coverAlt={`${ALBUM_COVER_ALT_TYPE} ${group.album.title}`}
								{coverUrl}
								{fill}
							/>
						</button>
						<button
							type="button"
							class="wall-tile-play"
							data-hitbox="frequent"
							data-hitbox-face
							aria-label={collectionRowPlayLabel(group.album.title)}
							onclick={() => onPlayAlbum(group.album.id)}
						>
							<Icon name="play" size={16} />
						</button>
					</div>
				{/each}
			</div>

			{#if browseState.status === 'loading' && albums.length === 0}
				<p class="empty" role="status">{LIBRARY_ALBUMS_LOADING}</p>
			{:else if browseState.status === 'error' && albums.length === 0}
				<p class="empty" role="alert">{browseState.error || LIBRARY_SEARCH_ERROR}</p>
				<button class="retry-btn" onclick={() => loadLibraryBrowse({ reset: true })}
					>{LIBRARY_RETRY_LABEL}</button
				>
			{:else if albumGroups.length === 0}
				<p class="empty">{LIBRARY_ALBUMS_EMPTY}</p>
			{/if}

			{#if browseState.albumHasMore}
				<button
					class="load-more"
					onclick={async () => {
						await loadLibraryBrowse({ reset: false });
						persistLibraryHistory();
					}}
					disabled={browseState.status === 'loading'}
				>
					{LIBRARY_LOAD_MORE}
				</button>
			{/if}

			{#if browseState.status === 'error' && albums.length > 0}
				<p class="empty" role="alert">{browseState.error || LIBRARY_SEARCH_ERROR}</p>
				<button class="retry-btn" onclick={() => loadLibraryBrowse({ reset: true })}
					>{LIBRARY_RETRY_LABEL}</button
				>
			{/if}
		{:else if filter === 'playlists'}
			{#if orderedPlaylists.length > 0}
				<div class="tile-grid" style:--album-card-track={`${LIBRARY_ALBUM_CARD_TRACK_MAX_PX}px`}>
					{#each orderedPlaylists as playlist (playlist.id)}
						<div
							class="wall-tile"
							class:selected={currentCollection?.kind === 'playlist' &&
								currentCollection.id === playlist.id}
						>
							<button
								type="button"
								class="wall-tile-body"
								onclick={() => openPlaylist(playlist.id)}
							>
								<LibraryTileContent
									title={playlist.title}
									subtitle={playlistSummaryLabel(playlist.entry_count)}
									coverAlt={playlist.title}
								/>
							</button>
							<button
								type="button"
								class="wall-tile-play"
								data-hitbox="frequent"
								data-hitbox-face
								aria-label={collectionRowPlayLabel(playlist.title)}
								onclick={() => onPlayPlaylist(playlist)}
							>
								<Icon name="play" size={16} />
							</button>
						</div>
					{/each}
				</div>
			{:else if playlistStatus.status === 'loading'}
				<p class="empty" role="status">{LIBRARY_PLAYLISTS_LOADING}</p>
			{:else if playlistStatus.status === 'error'}
				<p class="empty" role="alert">{playlistStatus.error || LIBRARY_PLAYLISTS_ERROR}</p>
				<button class="retry-btn" onclick={() => loadPlaylists()}>{LIBRARY_RETRY_LABEL}</button>
			{:else}
				<p class="empty">{LIBRARY_PLAYLISTS_EMPTY}</p>
			{/if}
		{/if}
	</div>
</div>

{#if pendingUnshare}
	<ConfirmDeleteDialog
		title={LIBRARY_SHARES_UNSHARE_TITLE}
		items={[shareRowLabel(pendingUnshare)]}
		warning={LIBRARY_SHARES_UNSHARE_WARNING}
		confirmLabel={LIBRARY_SHARES_UNSHARE_LABEL}
		onconfirm={() => confirmUnshare()}
		oncancel={() => (pendingUnshare = null)}
	/>
{/if}

<style>
	.library-wall {
		display: flex;
		flex-direction: column;
		min-width: 0;
		min-height: 0;
		flex: 1;
	}

	.wall-toolbar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 16px 20px 8px;
		flex-shrink: 0;
	}

	.wall-title {
		font-family: var(--font-display);
		font-size: 1.4rem;
		color: var(--text);
		text-transform: uppercase;
		letter-spacing: 1px;
	}

	.wall-controls {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		min-width: 0;
	}

	.filter-chips {
		display: flex;
		gap: 4px;
		flex-wrap: wrap;
	}

	.filter-chip {
		border: 1px solid var(--border);
		background: var(--surface);
		color: var(--text-muted);
		border-radius: 999px;
		padding: 0.3rem 0.75rem;
		font-size: 0.75rem;
		font-family: var(--font-body);
		cursor: pointer;
	}

	.filter-chip.active {
		color: var(--text);
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 14%, var(--surface));
	}

	.sort-select {
		padding: 0.3rem 0.5rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: 0.8rem;
	}

	.new-btn {
		border: 1px solid var(--border);
		background: var(--surface);
		color: var(--text-muted);
		border-radius: 4px;
		padding: 0.3rem 0.6rem;
		font-size: 0.78rem;
		font-family: var(--font-body);
		white-space: nowrap;
	}

	.new-btn:hover {
		border-color: var(--primary);
		color: var(--primary);
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
		position: relative;
		min-width: 0;
		border: 1px solid var(--border);
		border-radius: var(--card-radius);
		background: var(--surface);
		overflow: hidden;
	}

	.wall-tile.selected {
		box-shadow: inset 0 0 0 2px var(--accent);
	}

	.wall-tile-body {
		display: flex;
		flex-direction: column;
		width: 100%;
		min-width: 0;
		background: transparent;
		border: none;
		color: var(--text);
		font-family: var(--font-body);
		cursor: pointer;
		text-align: left;
	}

	.wall-tile-body:hover {
		background: var(--surface-hover);
	}

	.wall-tile-play {
		position: absolute;
		right: 6px;
		bottom: 6px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border: none;
		background: none;
		color: var(--text-muted);
	}

	.wall-tile-play:hover {
		color: var(--primary);
	}

	.wall-tile-unarchive {
		width: 100%;
		padding: 6px 8px;
		background: none;
		border: none;
		border-top: 1px solid var(--border);
		color: var(--text-muted);
		font-size: 0.72rem;
		font-family: var(--font-body);
		text-transform: uppercase;
		letter-spacing: 0.4px;
		cursor: pointer;
	}

	.wall-tile-unarchive:hover {
		color: var(--primary);
		border-color: var(--primary);
	}

	.share-filters {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		padding-bottom: 8px;
	}

	.share-row {
		display: flex;
		align-items: center;
		width: 100%;
		min-width: 0;
		gap: 4px;
		padding: 4px 8px 4px 4px;
	}

	.share-open {
		display: flex;
		align-items: center;
		flex: 1;
		min-width: 0;
		padding: 8px;
		background: none;
		border: none;
		color: var(--text-light);
		font-size: var(--label-font-size);
		cursor: pointer;
		text-align: left;
		gap: 8px;
	}

	.share-open:hover {
		color: var(--text);
	}

	.share-action {
		flex-shrink: 0;
		background: none;
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text-muted);
		font-size: 0.68rem;
		font-family: var(--font-body);
		padding: 4px 8px;
		cursor: pointer;
	}

	.share-action:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.share-title {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.share-type {
		font-size: 0.7rem;
		color: var(--text-subtle);
		flex-shrink: 0;
		margin-left: 8px;
	}

	.empty {
		padding: 20px;
		color: var(--text-subtle);
		text-align: center;
		font-size: var(--label-font-size);
	}

	.retry-btn,
	.load-more {
		display: block;
		margin: 0 auto 16px;
		padding: 6px 12px;
		background: none;
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text-muted);
		font-size: var(--label-font-size);
		font-family: var(--font-body);
		cursor: pointer;
	}

	.retry-btn:hover,
	.load-more:hover {
		border-color: var(--primary);
		color: var(--primary);
	}

	.load-more:disabled {
		opacity: 0.5;
		cursor: default;
	}

	@media (max-width: 768px) {
		.wall-toolbar {
			padding: 12px 12px 6px;
		}

		.tile-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}
</style>
