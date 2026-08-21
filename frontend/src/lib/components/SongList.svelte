<script lang="ts">
	interface Props {
		onNewSong?: () => void;
	}

	let { onNewSong }: Props = $props();

	import { albumList, songList, selectedAlbumId } from '$lib/stores/player';
	import {
		persistLibraryHistory,
		selectAlbumOverview,
		selectLibrarySection,
		selectPlaylistView,
		selectSong
	} from '$lib/stores/navigation';
	import { searchQuery } from '$lib/stores/filter';
	import {
		createNewPlaylist,
		playlistList,
		playlistLoad,
		loadPlaylists,
		selectedPlaylistId
	} from '$lib/stores/playlists';
	import {
		albumIsExpanded,
		captureLibraryScroll,
		expandedAlbumIds,
		libraryScrollAnchor,
		librarySection,
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
	import type { SongItem, AlbumItem } from '$lib/api/types';
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
		LIBRARY_SHARED_EMPTY,
		LIBRARY_SHARED_LOADING,
		type LibrarySection
	} from '$lib/constants';

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

	interface SharedItem {
		id: string;
		type: 'album' | 'song' | 'generation' | 'playlist';
		label: string;
		parentSongId?: string;
	}

	const sharedItems = $derived.by(() => {
		const items: SharedItem[] = [];
		for (const a of albums) {
			if (a.is_shared) items.push({ id: a.id, type: 'album', label: a.title });
		}
		for (const s of songs) {
			if (s.is_shared) items.push({ id: s.id, type: 'song', label: s.title });
			for (const g of s.generations) {
				if (g.is_shared) {
					items.push({
						id: g.id,
						type: 'generation',
						label: `Gen #${g.generation_number} — ${s.title}`,
						parentSongId: s.id
					});
				}
			}
		}
		for (const p of playlists) {
			if (p.is_shared) items.push({ id: p.id, type: 'playlist', label: p.title });
		}
		return items;
	});

	$effect(() => {
		syncLibrarySearch(search);
	});

	$effect(() => {
		if (browseEl && browseEl.scrollTop !== restoredScroll) {
			browseEl.scrollTop = restoredScroll;
		}
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
		searchQuery.set((event.target as HTMLInputElement).value);
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

	function onSharedItem(item: SharedItem): void {
		if (item.type === 'album') selectAlbumOverview(item.id);
		else if (item.type === 'song') selectSong(item.id);
		else if (item.type === 'playlist') selectPlaylistView(item.id);
		else if (item.parentSongId) selectSong(item.parentSongId);
	}

	const panelSection = $derived(searching ? 'search' : section);
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
				class:active={section === item}
				role="tab"
				id="library-tab-{item}"
				aria-selected={section === item}
				aria-controls="library-panel"
				tabindex={section === item ? 0 : -1}
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
				ontoggle={() => onToggleAlbum(group.album.id)}
				onselect={() => hydrateAndOpenAlbum(group.album)}
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
				onclick={() => loadMoreLibrarySearch()}
				disabled={searchState.status === 'loading'}
			>
				{LIBRARY_LOAD_MORE}
			</button>
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
					ontoggle={() => onToggleAlbum(group.album.id)}
					onselect={() => hydrateAndOpenAlbum(group.album)}
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
				onclick={() => loadLibraryBrowse({ reset: false })}
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
	{:else if section === 'shared'}
		{#if playlistStatus.status === 'loading' && sharedItems.length === 0}
			<p class="empty" role="status">{LIBRARY_SHARED_LOADING}</p>
		{:else if sharedItems.length === 0 && playlistStatus.status === 'error'}
			<p class="empty" role="alert">{playlistStatus.error || LIBRARY_PLAYLISTS_ERROR}</p>
			<button class="retry-btn" onclick={() => loadPlaylists()}>{LIBRARY_RETRY_LABEL}</button>
		{:else if sharedItems.length === 0}
			<p class="empty">{LIBRARY_SHARED_EMPTY}</p>
		{:else}
			{#each sharedItems as item (item.type + item.id)}
				<button class="playlist-row shared-row" onclick={() => onSharedItem(item)}>
					<span class="shared-icon">&#128279;</span>
					<span class="playlist-title">{item.label}</span>
					<span class="playlist-count">{item.type}</span>
				</button>
			{/each}
		{/if}
		{#if playlistStatus.status === 'error' && sharedItems.length > 0}
			<p class="empty" role="alert">{playlistStatus.error || LIBRARY_PLAYLISTS_ERROR}</p>
			<button class="retry-btn" onclick={() => loadPlaylists()}>{LIBRARY_RETRY_LABEL}</button>
		{/if}
	{/if}
</div>

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

	.shared-icon {
		font-size: 0.7rem;
		flex-shrink: 0;
		margin-right: 8px;
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
