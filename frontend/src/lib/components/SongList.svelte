<script lang="ts">
	interface Props {
		onNewSong?: () => void;
	}

	let { onNewSong }: Props = $props();

	import {
		albumList,
		albumSongsLoad,
		loadSongsForAlbum,
		songList,
		selectedAlbumId,
		selectedGenerationId,
		updateAlbumInList,
		updateGenerationInList,
		updateSongInList
	} from '$lib/stores/player';
	import {
		persistLibraryHistory,
		selectAlbumOverview,
		selectLibrarySection,
		selectPlaylistView,
		selectSong
	} from '$lib/stores/navigation';
	import {
		loadMoreShares,
		loadShareInventory,
		refreshSharesAfterMutation,
		setShareTypeFilter,
		shareInventory,
		sharesViewOpen,
		watchShareView
	} from '$lib/stores/shares';
	import { fetchAlbum } from '$lib/api/albums';
	import { unshareAlbum, unshareGeneration, unsharePlaylist, unshareSong } from '$lib/api/client';
	import type { AlbumItem, ShareInventoryItem, SongItem } from '$lib/api/types';
	import { searchQuery } from '$lib/stores/filter';
	import {
		createNewPlaylist,
		playlistList,
		playlistLoad,
		loadPlaylists,
		selectedPlaylistId,
		updatePlaylistInList
	} from '$lib/stores/playlists';
	import {
		albumIsExpanded,
		captureLibraryScroll,
		expandedAlbumIds,
		libraryScrollAnchor,
		librarySection,
		setLibrarySurface,
		toggleAlbumExpanded
	} from '$lib/stores/libraryContext';
	import {
		changeLibrarySort,
		groupSearchHits,
		libraryBrowse,
		librarySearch,
		librarySort,
		loadLibraryBrowse,
		loadMoreLibrarySearch,
		retryLibrarySearch,
		syncLibrarySearch
	} from '$lib/stores/librarySearch';
	import { addToast } from '$lib/stores/toast';
	import AlbumNode from './AlbumNode.svelte';

	import { CREATED_SORT_LABELS, CREATED_SORTS, compareByCreatedAt } from '$lib/utils/recency';
	import {
		LIBRARY_ALBUMS_EMPTY,
		LIBRARY_ALBUMS_LOADING,
		LIBRARY_LOAD_MORE,
		LIBRARY_NEW_PLAYLIST_LABEL,
		LIBRARY_NEW_SONG_LABEL,
		LIBRARY_PLAYLISTS_EMPTY,
		LIBRARY_PLAYLISTS_ERROR,
		LIBRARY_PLAYLISTS_LOADING,
		LIBRARY_RETRY_LABEL,
		LIBRARY_SEARCH_EMPTY,
		LIBRARY_SEARCH_ERROR,
		LIBRARY_SEARCH_LOADING,
		LIBRARY_SEARCH_PLACEHOLDER,
		LIBRARY_SECTION_LABELS,
		LIBRARY_SECTION_NAV_LABEL,
		LIBRARY_SECTIONS,
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
		type LibrarySection
	} from '$lib/constants';
	import ConfirmDeleteDialog from './ConfirmDeleteDialog.svelte';

	const albums = $derived($albumList);
	const songs = $derived($songList);
	const search = $derived($searchQuery);
	const currentAlbumId = $derived($selectedAlbumId);
	const playlists = $derived($playlistList);
	const currentPlaylistId = $derived($selectedPlaylistId);
	const createdSort = $derived($librarySort);
	const searchState = $derived($librarySearch);
	const browseState = $derived($libraryBrowse);
	const searching = $derived(search.trim().length > 0);
	const section = $derived($librarySection);
	const expanded = $derived($expandedAlbumIds);
	const playlistStatus = $derived($playlistLoad);
	const restoredScroll = $derived($libraryScrollAnchor);
	const albumLoads = $derived($albumSongsLoad);
	const sharesOpen = $derived($sharesViewOpen);
	const sharesState = $derived($shareInventory);
	let pendingUnshare = $state<ShareInventoryItem | null>(null);

	$effect(() => {
		if (!sharesOpen) return;
		return watchShareView();
	});

	$effect(() => {
		syncLibrarySearch(search);
	});

	interface AlbumGroup {
		album: AlbumItem;
		songs: SongItem[];
	}

	const albumGroups = $derived.by(() => {
		if (searching) {
			return groupSearchHits(searchState.items);
		}

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

	function onToggleAlbum(albumId: string): void {
		toggleAlbumExpanded(albumId);
		persistLibraryHistory();
	}

	function hydrateAndOpenAlbum(album: AlbumItem): void {
		albumList.update((list) =>
			list.some((item) => item.id === album.id) ? list : [...list, album]
		);
		selectAlbumOverview(album.id);
	}

	function onSelectSection(next: LibrarySection): void {
		selectLibrarySection(next);
	}

	function onSectionKeydown(event: KeyboardEvent, current: LibrarySection): void {
		const index = LIBRARY_SECTIONS.indexOf(current);
		let next: LibrarySection | null = null;
		if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
			event.preventDefault();
			next = LIBRARY_SECTIONS[(index + 1) % LIBRARY_SECTIONS.length];
		} else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
			event.preventDefault();
			next = LIBRARY_SECTIONS[(index - 1 + LIBRARY_SECTIONS.length) % LIBRARY_SECTIONS.length];
		}
		if (!next) return;
		onSelectSection(next);
		const tab = document.getElementById(`library-tab-${next}`);
		if (tab instanceof HTMLButtonElement) tab.focus();
	}

	function onSortChange(option: (typeof CREATED_SORTS)[number]): void {
		changeLibrarySort(option, search);
		persistLibraryHistory();
	}

	function onSearchInput(event: Event): void {
		const value = (event.target as HTMLInputElement).value;
		searchQuery.set(value);
		if (value.trim()) setLibrarySurface('browse');
		syncLibrarySearch(value);
		persistLibraryHistory();
	}

	async function onCreatePlaylist(): Promise<void> {
		try {
			const playlist = await createNewPlaylist('Playlist');
			selectLibrarySection('playlists');
			selectPlaylistView(playlist.id);
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
				hydrateAndOpenAlbum(await fetchAlbum(item.id));
			} catch {
				addToast('Open failed', 'error');
			}
		} else if (item.type === 'song') selectSong(item.id);
		else if (item.type === 'playlist') selectPlaylistView(item.id);
		else if (item.song_id) {
			selectSong(item.song_id);
			selectedGenerationId.set(item.id);
			persistLibraryHistory();
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

	const panelSection = $derived(searching ? 'search' : sharesOpen ? 'shares' : section);
	const sharesPageComplete = $derived(sharesState.status === 'ready' && !sharesState.hasMore);
</script>

<div class="library-nav">
	<div class="search-bar">
		<input
			class="search"
			type="text"
			placeholder={LIBRARY_SEARCH_PLACEHOLDER}
			value={search}
			oninput={onSearchInput}
			aria-label={LIBRARY_SEARCH_PLACEHOLDER}
			aria-busy={searching && searchState.status === 'loading'}
		/>
		<div class="sort-strip" role="radiogroup" aria-label="List sort" tabindex="-1">
			{#each CREATED_SORTS as option (option)}
				<button
					class="sort-btn"
					class:active={createdSort === option}
					role="radio"
					aria-checked={createdSort === option}
					aria-label={CREATED_SORT_LABELS[option]}
					onclick={() => onSortChange(option)}
				>
					{CREATED_SORT_LABELS[option]}
				</button>
			{/each}
		</div>
		{#if onNewSong}
			<button
				class="new-btn"
				data-hitbox="frequent"
				data-hitbox-face
				onclick={onNewSong}
				title={LIBRARY_NEW_SONG_LABEL}
				aria-label={LIBRARY_NEW_SONG_LABEL}>+</button
			>
		{/if}
	</div>

	<div class="section-nav" role="tablist" aria-label={LIBRARY_SECTION_NAV_LABEL}>
		{#each LIBRARY_SECTIONS as item (item)}
			<button
				class="section-tab"
				class:active={section === item && !sharesOpen}
				role="tab"
				id="library-tab-{item}"
				aria-selected={section === item && !sharesOpen}
				aria-controls="library-panel"
				tabindex={section === item && !sharesOpen ? 0 : -1}
				onclick={() => onSelectSection(item)}
				onkeydown={(event) => onSectionKeydown(event, item)}
			>
				{LIBRARY_SECTION_LABELS[item]}
			</button>
		{/each}
	</div>
</div>

<div
	class="library-browse"
	id="library-panel"
	role="tabpanel"
	data-library-section={panelSection}
	aria-labelledby="library-tab-{section}"
	bind:this={browseEl}
	onscroll={onBrowseScroll}
>
	{#if searching}
		{#each albumGroups as group (group.album.id)}
			<AlbumNode
				album={group.album}
				songs={group.songs}
				expanded={albumIsExpanded(group.album.id, expanded, {
					selectedAlbumId: currentAlbumId,
					searching: true,
					songHits: group.songs.length
				})}
				selected={group.album.id === currentAlbumId}
				loadState={albumLoads[group.album.id]}
				ontoggle={() => onToggleAlbum(group.album.id)}
				onselect={() => hydrateAndOpenAlbum(group.album)}
				onretry={() => loadSongsForAlbum(group.album.id)}
			/>
		{/each}

		{#if searchState.status === 'loading' && searchState.items.length === 0}
			<p class="empty" role="status">{LIBRARY_SEARCH_LOADING}</p>
		{:else if searchState.status === 'error'}
			<p class="empty" role="alert">{searchState.error || LIBRARY_SEARCH_ERROR}</p>
			<button class="retry-btn" onclick={() => retryLibrarySearch()}>{LIBRARY_RETRY_LABEL}</button>
		{:else if albumGroups.length === 0}
			<p class="empty">{LIBRARY_SEARCH_EMPTY}</p>
		{/if}

		{#if searchState.hasMore}
			<button
				class="load-more"
				onclick={async () => {
					await loadMoreLibrarySearch();
					persistLibraryHistory();
				}}
				disabled={searchState.status === 'loading'}
			>
				{LIBRARY_LOAD_MORE}
			</button>
		{/if}
	{:else if sharesOpen}
		<div class="share-filters" role="radiogroup" aria-label={LIBRARY_SHARES_FILTER_LABEL}>
			<button
				class="sort-btn"
				class:active={sharesState.typeFilter === null}
				role="radio"
				aria-checked={sharesState.typeFilter === null}
				onclick={() => setShareTypeFilter(null)}
			>
				{LIBRARY_SHARES_ALL_LABEL}
			</button>
			{#each LIBRARY_SHARES_TYPES as type (type)}
				<button
					class="sort-btn"
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
						<span class="playlist-count">{LIBRARY_SHARES_TYPE_LABELS[item.type]}</span>
						<span class="playlist-title">{shareRowLabel(item)}</span>
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
	{:else if section === 'albums'}
		<div class="album-overview">
			{#each albumGroups as group (group.album.id)}
				<AlbumNode
					album={group.album}
					songs={group.songs}
					expanded={albumIsExpanded(group.album.id, expanded, {
						selectedAlbumId: currentAlbumId,
						searching: false,
						songHits: group.songs.length
					})}
					selected={group.album.id === currentAlbumId}
					loadState={albumLoads[group.album.id]}
					ontoggle={() => onToggleAlbum(group.album.id)}
					onselect={() => hydrateAndOpenAlbum(group.album)}
					onretry={() => loadSongsForAlbum(group.album.id)}
				/>
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

		{#if browseState.albumHasMore || browseState.songHasMore}
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
	{:else if section === 'playlists'}
		<div class="section-toolbar">
			<button
				class="new-btn"
				data-hitbox="frequent"
				data-hitbox-face
				onclick={onCreatePlaylist}
				title={LIBRARY_NEW_PLAYLIST_LABEL}
				aria-label={LIBRARY_NEW_PLAYLIST_LABEL}>+</button
			>
		</div>
		{#if playlistStatus.status === 'loading' && playlists.length === 0}
			<p class="empty" role="status">{LIBRARY_PLAYLISTS_LOADING}</p>
		{:else if playlistStatus.status === 'error' && playlists.length === 0}
			<p class="empty" role="alert">{playlistStatus.error || LIBRARY_PLAYLISTS_ERROR}</p>
			<button class="retry-btn" onclick={() => loadPlaylists()}>{LIBRARY_RETRY_LABEL}</button>
		{:else if playlists.length === 0}
			<p class="empty">{LIBRARY_PLAYLISTS_EMPTY}</p>
		{:else}
			{#each orderedPlaylists as p (p.id)}
				<button
					class="playlist-row"
					class:selected={p.id === currentPlaylistId}
					onclick={() => selectPlaylistView(p.id)}
				>
					<span class="playlist-title">{p.title}</span>
					<span class="playlist-count">{p.entry_count}</span>
				</button>
			{/each}
		{/if}
		{#if playlistStatus.status === 'error' && playlists.length > 0}
			<p class="empty" role="alert">{playlistStatus.error || LIBRARY_PLAYLISTS_ERROR}</p>
			<button class="retry-btn" onclick={() => loadPlaylists()}>{LIBRARY_RETRY_LABEL}</button>
		{/if}
	{/if}
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
	.library-nav {
		display: flex;
		flex-direction: column;
		min-width: 0;
		flex-shrink: 0;
	}

	.search-bar {
		padding: 8px 12px;
		flex-shrink: 0;
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.sort-strip {
		display: flex;
		gap: 2px;
		flex-shrink: 0;
		flex-wrap: wrap;
		min-width: 0;
	}

	.sort-btn {
		border: 1px solid var(--border);
		background: var(--surface);
		color: var(--text-muted);
		border-radius: 999px;
		padding: 0.15rem 0.5rem;
		font-size: 0.68rem;
		font-family: var(--font-body);
		cursor: pointer;
	}

	.sort-btn.active {
		color: var(--text);
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 14%, var(--surface));
	}

	.search {
		flex: 1;
		padding: 6px 10px;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 4px;
		color: var(--text);
		font-size: var(--label-font-size);
		outline: none;
		min-width: 0;
	}

	.new-btn {
		color: var(--text-muted);
		font-size: 1rem;
		font-family: var(--font-body);
		line-height: 1;
	}

	.new-btn:hover {
		color: var(--primary);
	}

	.search:focus {
		border-color: var(--accent);
		box-shadow: 0 0 8px rgba(160, 32, 240, 0.2);
	}

	.search::placeholder {
		color: var(--text-subtle);
	}

	.section-nav {
		display: flex;
		width: 100%;
		min-width: 0;
		border-bottom: 1px solid var(--border);
	}

	.section-tab {
		flex: 1;
		min-width: 0;
		padding: 8px 6px;
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		color: var(--text-muted);
		font-size: 0.7rem;
		font-family: var(--font-display);
		text-transform: uppercase;
		letter-spacing: 1px;
		cursor: pointer;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.section-tab.active {
		color: var(--text);
		border-bottom-color: var(--accent);
	}

	.section-tab:hover {
		color: var(--text);
	}

	.library-browse {
		flex: 1;
		min-width: 0;
		min-height: 0;
		overflow-x: hidden;
		overflow-y: auto;
		padding: 0;
	}

	.album-overview {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
	}

	.section-toolbar {
		display: flex;
		justify-content: flex-end;
		padding: 8px 12px;
	}

	.playlist-row {
		display: flex;
		align-items: center;
		width: 100%;
		min-width: 0;
		padding: 8px 12px;
		background: none;
		border: none;
		color: var(--text-light);
		font-size: var(--label-font-size);
		cursor: pointer;
		text-align: left;
	}

	.playlist-row:hover {
		background: var(--surface-hover);
		color: var(--text);
	}

	.playlist-row.selected {
		color: var(--primary);
		background: var(--surface-hover);
	}

	.share-filters {
		display: flex;
		flex-wrap: wrap;
		gap: 2px;
		padding: 8px 12px;
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

	.playlist-title {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.playlist-count {
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
		.search {
			font-size: 1rem;
			padding: 8px 12px;
		}

		.section-tab {
			padding: 10px 4px;
		}
	}
</style>
